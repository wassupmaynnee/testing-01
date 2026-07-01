"""Single-pass strategy: ingest -> ASR -> score -> select -> render -> persist."""
from __future__ import annotations

import re
from pathlib import Path

from ..config import get_settings
from ..db import SessionLocal
from ..models import Clip, CreditLedger, Job, JobStatus, User
from ..render import ffmpeg, reframe, subtitles
from ..scoring import Signals, engagement_score
from ..sse import publish
from ..storage import store_clip
from .asr import transcribe
from .base import PipelineStrategy, get_ingest_source

_STRONG = {"amazing", "incredible", "never", "best", "worst", "love", "hate",
           "wow", "crazy", "huge", "secret", "wrong", "shocking", "insane"}
_TARGET_LEN = 30.0
_STEP = 5.0


def _update(db, job: Job, *, stage=None, progress=None, status=None,
            message="", **extra) -> None:
    if stage is not None:
        job.stage = stage
    if progress is not None:
        job.progress = progress
    if status is not None:
        job.status = status
    db.commit()
    publish(job.id, stage if stage is not None else job.stage,
            progress if progress is not None else job.progress,
            status.value if status else job.status.value, message, **extra)


def _words(segments: list[dict], a: float, b: float) -> list[dict]:
    return [s for s in segments if s["end"] > a and s["start"] < b]


def _signals(segments: list[dict], src: str, a: float, b: float) -> Signals:
    win = _words(segments, a, b)
    text = " ".join(s["text"] for s in win).lower()
    n_words = len(re.findall(r"\w+", text))
    duration = max(b - a, 0.1)

    # hook: front-loaded interest — first segment punch + question/number presence
    first = win[0]["text"].lower() if win else ""
    hook = min(1.0, 0.4 * ("?" in first or any(c.isdigit() for c in first))
               + 0.6 * min(len(first.split()) / 12.0, 1.0))
    # pace: words per second, normalized to a 3 wps ceiling
    pace = min(1.0, (n_words / duration) / 3.0)
    # sentiment: density of strong/emotive tokens + exclamations
    strong_hits = sum(text.count(w) for w in _STRONG) + text.count("!")
    sentiment = min(1.0, strong_hits / 5.0)
    # face: real YuNet presence sampling over the window
    face = reframe.face_presence(src, a, b)
    return Signals(hook=hook, pace=pace, sentiment=sentiment, face=face)


def _select_windows(segments, src, duration, n) -> list[tuple[float, float, Signals, float]]:
    """Top-N non-overlapping windows by the FROZEN engagement score, returned in
    chronological order. Reuses _signals()/engagement_score() unchanged — the
    weights (hook 0.35 / pace 0.20 / sentiment 0.25 / face 0.20) are untouched."""
    target = min(_TARGET_LEN, duration)
    if duration <= target + 0.01:
        sig = _signals(segments, src, 0.0, duration)
        return [(0.0, duration, sig, engagement_score(sig))]

    cands: list[tuple[float, float, Signals, float]] = []
    start = 0.0
    while start + target <= duration + 0.01:
        sig = _signals(segments, src, start, start + target)
        cands.append((start, start + target, sig, engagement_score(sig)))
        start += _STEP

    cands.sort(key=lambda c: c[3], reverse=True)
    chosen: list[tuple[float, float, Signals, float]] = []
    for c in cands:
        if len(chosen) >= n:
            break
        if all(c[1] <= ch[0] or c[0] >= ch[1] for ch in chosen):  # non-overlapping
            chosen.append(c)
    chosen.sort(key=lambda c: c[0])
    return chosen


class SinglePassStrategy(PipelineStrategy):
    def run(self, job_id: str) -> None:
        settings = get_settings()
        settings.ensure_dirs()
        db = SessionLocal()
        try:
            job = db.get(Job, job_id)
            if job is None:
                return
            _update(db, job, stage=0, progress=0.0, status=JobStatus.running,
                    message="Job dequeued")

            # Stage 1 — ingest + probe
            src = get_ingest_source(job.kind).prepare(job)
            meta = ffmpeg.probe(src)
            duration = meta["duration"] or 1.0
            _update(db, job, stage=1, progress=0.12, message=f"Media {duration:.1f}s")

            # Stage 2 — ASR
            segments = transcribe(src)
            _update(db, job, stage=2, progress=0.4,
                    message=f"{len(segments)} transcript segments")

            # Stage 3 — scoring + Stage 4 — boundary selection (top-N windows)
            _update(db, job, stage=3, progress=0.55, message="Scoring engagement")
            n_target = settings.clips_per_video_clamped()
            windows = _select_windows(segments, src, duration, n_target)
            _update(db, job, stage=4, progress=0.65,
                    message=f"Selected {len(windows)} window(s)")

            # Stage 5 — render each window into its own clip. Credits = clips: one
            # credit per rendered clip, stopping if the user runs out mid-job.
            user = db.get(User, job.user_id)
            made: list[Clip] = []
            total = max(len(windows), 1)
            for i, (start_s, end_s, sig, score) in enumerate(windows):
                if user is not None and user.credits <= 0:
                    break
                base = 0.72 + 0.23 * (i / total)
                _update(db, job, stage=5, progress=round(base, 3),
                        message=f"Rendering clip {i + 1}/{len(windows)} (cut)")
                cut_path = str(settings.clips_dir / f"{job.id}_{i}_cut.mp4")
                ffmpeg.cut(src, cut_path, start_s, end_s - start_s)

                _update(db, job, stage=5, progress=round(base + 0.05, 3),
                        message=f"Rendering clip {i + 1}/{len(windows)} (reframe 9:16)")
                vert_path = str(settings.clips_dir / f"{job.id}_{i}_vert.mp4")
                try:
                    reframe.reframe_vertical(cut_path, vert_path)
                except Exception as exc:  # noqa: BLE001
                    print(f"[render] reframe fallback ({exc})")
                    vert_path = cut_path

                _update(db, job, stage=5, progress=round(base + 0.1, 3),
                        message=f"Rendering clip {i + 1}/{len(windows)} (captions)")
                final_path = str(settings.clips_dir / f"{job.id}_{i}.mp4")
                win_segments = _words(segments, start_s, end_s)
                if win_segments:
                    ass_path = str(settings.clips_dir / f"{job.id}_{i}.ass")
                    subtitles.build_ass(win_segments, ass_path, start_s)
                    try:
                        subtitles.burn(vert_path, ass_path, final_path)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[render] subtitle burn fallback ({exc})")
                        Path(vert_path).replace(final_path)
                else:
                    Path(vert_path).replace(final_path)

                # Store (R2 when configured, else local) then persist the record.
                ref = store_clip(final_path, f"clips/{job.id}_{i}.mp4")
                clip = Clip(
                    job_id=job.id, title=f"Highlight {start_s:.0f}-{end_s:.0f}s",
                    file_path=ref, start_s=start_s, end_s=end_s, score=score,
                    hook=sig.hook, pace=sig.pace, sentiment=sig.sentiment, face=sig.face,
                )
                db.add(clip)
                if user is not None:
                    user.credits -= 1
                    db.add(CreditLedger(user_id=user.id, delta=-1, reason=f"clip:{job.id}_{i}"))
                db.flush()
                made.append(clip)

            if not made:
                raise RuntimeError("No clips rendered (out of credits or no valid windows).")

            _update(db, job, stage=6, progress=1.0, status=JobStatus.completed,
                    message=f"Complete — {len(made)} clip(s)",
                    clip_id=made[0].id, clipCount=len(made))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.get(Job, job_id)
            if job:
                job.status = JobStatus.failed
                job.error = str(exc)
                db.commit()
                publish(job.id, job.stage, job.progress, "failed", str(exc))
        finally:
            db.close()
