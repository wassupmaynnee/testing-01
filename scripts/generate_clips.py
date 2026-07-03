"""
Batch clip generator — reference-style profile.

Turns every video in SOURCE_DIR into 2-5 finished, social-ready clips:
word-timed opus-style captions (current word emphasized), speaker-centered
framing with aspect fallback (9:16 -> 3:4 / 1:1, blurred pad, never black
bars), -14 LUFS audio, 30fps H.264 CRF23 +faststart, poster thumbnail per
clip. Ranks with the FROZEN engagement weights via saas.scoring and registers
every clip in the DB through the repo's storage seam (R2 when configured,
local otherwise).

Run inside the api container (deps + DB live there):
  docker compose -f docker-compose.saas.yml exec api \
      python scripts/generate_clips.py /app/data/uploads/sources /app/data/clips/generated \
      --owner demo@clippify.dev --feature-top 4

GPL-3.0-only (see LICENSE).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saas.config import get_settings  # noqa: E402
from saas.render import reframe  # noqa: E402
from saas.scoring import Signals, engagement_score  # noqa: E402

# ---- Reference profile constants -------------------------------------------
TARGET_MIN, TARGET_MAX = 18.0, 64.0     # preferred window
HARD_MIN, HARD_MAX = 10.0, 150.0        # absolute bounds
MAX_OVERLAP = 0.10                      # between selected windows
FPS = 30
CRF = "23"
PRESET = "medium"
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"
ACCENT_ASS = "&H00007AFF&"              # #FF7A00 in ASS BGR

_STRONG = {"amazing", "incredible", "never", "best", "worst", "love", "hate",
           "wow", "crazy", "huge", "secret", "wrong", "shocking", "insane",
           "literally", "actually", "honestly", "insanely"}


def ffbin() -> tuple[str, str]:
    s = get_settings()
    return s.ffmpeg_bin, s.ffprobe_bin


def probe(path: str) -> dict:
    _, fp = ffbin()
    out = subprocess.run(
        [fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=True)
    info = json.loads(out.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    num, _, den = (v.get("r_frame_rate", "30/1").partition("/"))
    return {
        "duration": float(info["format"].get("duration", 0) or 0),
        "width": int(v.get("width", 0)), "height": int(v.get("height", 0)),
        "fps": (float(num) / float(den or 1)) if den else 30.0,
        "has_audio": a is not None,
    }


# ---- Transcription with WORD timestamps -------------------------------------
def transcribe_words(path: str) -> tuple[list[dict], list[dict]]:
    """Return (segments, words); words = [{'start','end','word'}]."""
    from faster_whisper import WhisperModel
    s = get_settings()
    model = WhisperModel(s.asr_model, device=s.asr_device, compute_type="int8")
    seg_iter, _ = model.transcribe(path, vad_filter=True, word_timestamps=True)
    segments, words = [], []
    for seg in seg_iter:
        segments.append({"start": float(seg.start), "end": float(seg.end),
                         "text": seg.text.strip()})
        for w in (seg.words or []):
            token = w.word.strip()
            if token:
                words.append({"start": float(w.start), "end": float(w.end), "word": token})
    return segments, words


# ---- Moment detection / scoring ---------------------------------------------
def _win_words(words, a, b):
    return [w for w in words if w["end"] > a and w["start"] < b]


def _text_signals(words, a, b) -> Signals:
    win = _win_words(words, a, b)
    text = " ".join(w["word"] for w in win).lower()
    n = len(win)
    dur = max(b - a, 0.1)
    first2 = " ".join(w["word"] for w in win if w["start"] < a + 2.0).lower()
    hook = min(1.0, 0.5 * bool(re.search(r"\?|!|\d", first2))
               + 0.5 * min(len(first2.split()) / 6.0, 1.0))
    pace = min(1.0, (n / dur) / 3.0)
    strong = sum(text.count(t) for t in _STRONG) + text.count("!")
    sentiment = min(1.0, strong / 5.0)
    return Signals(hook=hook, pace=pace, sentiment=sentiment, face=0.0)


def select_windows(segments, words, src, duration) -> list[dict]:
    """Complete-beat windows snapped to segment boundaries, ranked by the
    frozen engagement score. Face signal sampled only for finalists (slow)."""
    if not segments:
        return []
    talk = sum(s["end"] - s["start"] for s in segments)
    n_target = max(1, min(5, max(2 if talk > 90 else 1, round(talk / 75))))

    cands = []
    for i, seg in enumerate(segments):
        start = seg["start"]
        j = i
        while j < len(segments) and segments[j]["end"] - start < TARGET_MAX:
            end = segments[j]["end"]
            dur = end - start
            if dur >= TARGET_MIN or (j == len(segments) - 1 and dur >= HARD_MIN):
                sig = _text_signals(words, start, end)
                cands.append({"start": start, "end": end,
                              "sig": sig, "score": engagement_score(sig)})
            j += 1
    if not cands:  # short source: whole thing if it clears the floor
        end = segments[-1]["end"]
        if end - segments[0]["start"] >= HARD_MIN:
            sig = _text_signals(words, segments[0]["start"], end)
            cands = [{"start": segments[0]["start"], "end": end,
                      "sig": sig, "score": engagement_score(sig)}]

    cands.sort(key=lambda c: c["score"], reverse=True)

    # face pass for the finalists only, then re-rank with the frozen formula
    for c in cands[: n_target * 3]:
        face = reframe.face_presence(src, c["start"], c["end"], samples=6)
        c["sig"] = Signals(hook=c["sig"].hook, pace=c["sig"].pace,
                           sentiment=c["sig"].sentiment, face=face)
        c["score"] = engagement_score(c["sig"])
    cands.sort(key=lambda c: c["score"], reverse=True)

    chosen: list[dict] = []
    for c in cands:
        if len(chosen) >= n_target:
            break
        dur = c["end"] - c["start"]
        ok = True
        for ch in chosen:
            inter = max(0.0, min(c["end"], ch["end"]) - max(c["start"], ch["start"]))
            if inter / min(dur, ch["end"] - ch["start"]) > MAX_OVERLAP:
                ok = False
                break
        if ok:
            chosen.append(c)
    chosen.sort(key=lambda c: c["start"])
    return chosen


# ---- Captions: word-by-word, current word emphasized -------------------------
def _ass_ts(t: float) -> str:
    t = max(t, 0.0)
    return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"


def build_word_ass(words, clip_start, clip_end, out_path, play_w, play_h) -> bool:
    win = [w for w in words if w["start"] >= clip_start - 0.2 and w["end"] <= clip_end + 0.2]
    if not win:
        return False
    margin_v = int(play_h * 0.22)          # keep bottom ~20% clear for platform UI
    fontsize = max(48, int(play_h * 0.042))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,Arial,{fontsize},&H00FFFFFF,&H00000000,&H00000000,-1,1,{max(4, fontsize//14)},0,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Phrases of <=4 words; one event per word with the current word accented.
    def emit(phrase: list[dict], sink: list[str]) -> None:
        for k, cur in enumerate(phrase):
            parts = []
            for m, ww in enumerate(phrase):
                token = ww["word"].replace("{", "(").replace("}", ")")
                if m == k:
                    parts.append(f"{{\\1c{ACCENT_ASS}\\b1}}{token}{{\\1c&H00FFFFFF&}}")
                else:
                    parts.append(token)
            start = cur["start"] - clip_start
            end = max(cur["end"], cur["start"] + 0.12) - clip_start
            sink.append(f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Word,,0,0,0,, " +
                        " ".join(parts))

    lines = [header]
    phrase: list[dict] = []
    for w in win:
        phrase.append(w)
        if w["word"].rstrip().endswith((".", "!", "?", ",")) or len(phrase) == 4:
            emit(phrase, lines)
            phrase = []
    if phrase:
        emit(phrase, lines)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


# ---- Aspect + render ----------------------------------------------------------
def plan_aspect(w: int, h: int) -> tuple[str, int, int]:
    ar = w / h if h else 1.78
    if ar >= 1.4:
        return "9:16", 1080, 1920          # crop-pan from wide source
    if 0.85 <= ar <= 1.15:
        return "1:1", 1080, 1080
    if 0.65 <= ar < 0.85:
        return "3:4", 1080, 1440
    return "9:16", 1080, 1920              # already narrow/vertical


def render_clip(src, dst, start, dur, meta, ass_path, out_w, out_h) -> None:
    """One-pass cut + frame + captions + loudness, per the reference encode."""
    ff, _ = ffbin()
    w, h = meta["width"], meta["height"]
    src_ar, dst_ar = w / h, out_w / out_h
    sub_f = None
    if ass_path:
        ass_escaped = str(ass_path).replace("\\", "/").replace(":", r"\:")
        sub_f = f"subtitles='{ass_escaped}'"

    pad = not (src_ar >= 1.4 and dst_ar < 1) and abs(src_ar - dst_ar) >= 0.02
    if pad:
        # blurred-background pad (never black bars) — needs filter_complex + map
        chain = (
            f"[0:v]split[main][bg];"
            f"[bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur=24:2[bgb];"
            f"[main]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fg];"
            f"[bgb][fg]overlay=(W-w)/2:(H-h)/2[framed];"
            + (f"[framed]{sub_f}[vout]" if sub_f else "[framed]null[vout]")
        )
        filter_args = ["-filter_complex", chain, "-map", "[vout]", "-map", "0:a"]
    else:
        if src_ar >= 1.4 and dst_ar < 1:  # wide -> vertical: face-tracked crop
            cx, _, _ = reframe._average_face_x(src)  # noqa: SLF001 — repo helper
            crop_w = min(w, int(round(h * dst_ar)))
            x = max(0, min(int(round(cx - crop_w / 2)), w - crop_w))
            frame_f = f"crop={crop_w}:{h}:{x}:0,scale={out_w}:{out_h}:flags=lanczos"
        else:  # matching aspect: plain scale
            frame_f = f"scale={out_w}:{out_h}:flags=lanczos"
        vf = f"{frame_f},{sub_f}" if sub_f else frame_f
        filter_args = ["-vf", vf]

    cmd = [ff, "-y", "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}",
           *filter_args,
           "-r", str(FPS), "-c:v", "libx264", "-preset", PRESET, "-crf", CRF,
           "-pix_fmt", "yuv420p", "-af", LOUDNORM, "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", dst]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def poster(src_clip: str, dst_jpg: str, at: float = 1.2) -> None:
    ff, _ = ffbin()
    subprocess.run([ff, "-y", "-ss", f"{at:.2f}", "-i", src_clip, "-frames:v", "1",
                    "-q:v", "4", dst_jpg], check=True, capture_output=True)


def verify(path: str) -> bool:
    try:
        info = probe(path)
        return info["duration"] > 1 and info["width"] > 0 and info["has_audio"]
    except Exception:  # noqa: BLE001
        return False


# ---- DB registration through the repo seam -----------------------------------
def register(db_items: list[dict], owner_email: str, feature_top: int) -> None:
    from saas.db import SessionLocal
    from saas.models import Clip, IngestKind, Job, JobStatus, User
    from saas.storage import store_clip

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == owner_email).one_or_none()
        if user is None:
            raise SystemExit(f"owner user {owner_email!r} not found — create it first")
        by_source: dict[str, list[dict]] = {}
        for it in db_items:
            by_source.setdefault(it["source"], []).append(it)
        created = []
        for source, items in by_source.items():
            job = Job(user_id=user.id, kind=IngestKind.upload, source_ref=source,
                      status=JobStatus.completed, stage=6, progress=1.0)
            db.add(job)
            db.flush()
            for it in items:
                ref = store_clip(it["file"], f"generated/{Path(it['file']).name}")
                thumb_ref = store_clip(it["thumb"], f"generated/{Path(it['thumb']).name}")
                clip = Clip(job_id=job.id, title=it["title"], file_path=ref,
                            start_s=it["start"], end_s=it["end"], score=it["score"],
                            hook=it["sig"].hook, pace=it["sig"].pace,
                            sentiment=it["sig"].sentiment, face=it["sig"].face,
                            thumb_path=thumb_ref, aspect=it["aspect"])
                db.add(clip)
                db.flush()
                created.append(clip)
        created.sort(key=lambda c: c.score, reverse=True)
        aspects_seen = set()
        featured = 0
        for c in created:  # ensure aspect variety among featured
            if featured >= feature_top:
                break
            if c.aspect not in aspects_seen or featured < feature_top - 1:
                c.featured = True
                aspects_seen.add(c.aspect)
                featured += 1
        db.commit()
        print(f"[db] registered {len(created)} clips; featured {featured}")
    finally:
        db.close()


# ---- Main ---------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_dir")
    ap.add_argument("output_dir")
    ap.add_argument("--owner", default="demo@clippify.dev")
    ap.add_argument("--feature-top", type=int, default=4)
    ap.add_argument("--no-db", action="store_true")
    args = ap.parse_args()

    src_dir, out_dir = Path(args.source_dir), Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(p for p in src_dir.iterdir()
                     if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"})

    print("== INVENTORY ==")
    inventory = {}
    for p in sources:
        try:
            m = probe(str(p))
            inventory[p] = m
            print(f"  {p.name:32} {m['duration']:7.1f}s  {m['width']}x{m['height']}"
                  f"  {m['fps']:.0f}fps  audio={'y' if m['has_audio'] else 'N'}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {p.name:32} PROBE FAILED: {exc}")

    manifest, failures, db_items = [], [], []
    for p, meta in inventory.items():
        if not meta["has_audio"]:
            failures.append({"source": p.name, "reason": "no audio stream"})
            continue
        try:
            print(f"== {p.name}: transcribe (word timestamps) ==")
            segments, words = transcribe_words(str(p))
            (out_dir / f"{p.stem}.transcript.json").write_text(
                json.dumps({"segments": segments, "words": words}, indent=1))
            wins = select_windows(segments, words, str(p), meta["duration"])
            print(f"   {len(segments)} segments -> {len(wins)} windows")
            aspect, out_w, out_h = plan_aspect(meta["width"], meta["height"])
            for i, wsel in enumerate(wins):
                dur = wsel["end"] - wsel["start"]
                stem = f"{p.stem}_clip{i+1:02d}_{int(round(dur))}s"
                dst = out_dir / f"{stem}.mp4"
                thumb = out_dir / f"{stem}_thumb.jpg"
                ass = out_dir / f"{stem}.ass"
                has_caps = build_word_ass(words, wsel["start"], wsel["end"],
                                          str(ass), out_w, out_h)
                try:
                    render_clip(str(p), str(dst), wsel["start"], dur, meta,
                                str(ass) if has_caps else None, out_w, out_h)
                    poster(str(dst), str(thumb))
                    if not verify(str(dst)):
                        raise RuntimeError("output failed ffprobe verification")
                except Exception as exc:  # noqa: BLE001
                    failures.append({"source": p.name, "clip": stem, "reason": str(exc)[:300]})
                    continue
                win_text = " ".join(w["word"] for w in _win_words(words, wsel["start"], wsel["start"] + 6))
                title = (win_text[:60] + "…") if len(win_text) > 60 else (win_text or f"Clip {i+1}")
                entry = {"source": p.name, "file": str(dst), "thumb": str(thumb),
                         "start": round(wsel["start"], 1), "end": round(wsel["end"], 1),
                         "duration": round(dur, 1), "aspect": aspect,
                         "score": round(wsel["score"], 4),
                         "signals": {"hook": round(wsel["sig"].hook, 3),
                                     "pace": round(wsel["sig"].pace, 3),
                                     "sentiment": round(wsel["sig"].sentiment, 3),
                                     "face": round(wsel["sig"].face, 3)},
                         "title": title}
                manifest.append(entry)
                db_items.append({**entry, "sig": wsel["sig"]})
                print(f"   OK {dst.name}  {dur:.0f}s {aspect} score={wsel['score']:.3f}")
        except Exception as exc:  # noqa: BLE001
            failures.append({"source": p.name, "reason": str(exc)[:300]})

    (out_dir / "manifest.json").write_text(json.dumps(
        {"clips": manifest, "failures": failures}, indent=1))
    print(f"== DONE: {len(manifest)} clips, {len(failures)} failures ==")

    if db_items and not args.no_db:
        register(db_items, args.owner, args.feature_top)


if __name__ == "__main__":
    main()
