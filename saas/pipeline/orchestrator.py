"""Single-pass strategy: ingest -> ASR -> score -> select -> render -> persist."""
from __future__ import annotations

import re
from pathlib import Path

from ..config import get_settings
from ..db import SessionLocal
from ..models import Clip, Job, JobStatus
from ..render import ffmpeg, reframe, subtitles
from ..scoring import Signals, engagement_score
from ..sse import publish
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


def _select_window(segments, src, duration) -> tuple[float, float, Signals, float]:
    target = min(_TARGET_LEN, duration)
    if duration <= target + 0.01:
        sig = _signals(segments, src, 0.0, duration)
        return 0.0, duration, sig, engagement_score(sig)
    best = None
    start = 0.0
    while start + target <= duration + 0.01:
        sig = _signals(segments, src, start, start + target)
        score = engagement_score(sig)
        if best is None or score > best[3]:
            best = (start, start + target, sig, score)
        start += _STEP
    return best


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

            # Stage 3 — scoring + Stage 4 — boundary selection
            _update(db, job, stage=3, progress=0.55, message="Scoring engagement")
            start_s, end_s, sig, score = _select_window(segments, src, duration)
            _update(db, job, stage=4, progress=0.65,
                    message=f"Window {start_s:.1f}-{end_s:.1f}s score={score:.3f}",
                    score=round(score, 4))

            # Stage 5 — render: cut -> reframe -> subtitles
            _update(db, job, stage=5, progress=0.72, message="Cutting (NVENC pass)")
            cut_path = str(settings.clips_dir / f"{job.id}_cut.mp4")
            ffmpeg.cut(src, cut_path, start_s, end_s - start_s)

            _update(db, job, stage=5, progress=0.84, message="Reframing 9:16 (YuNet)")
            vert_path = str(settings.clips_dir / f"{job.id}_vert.mp4")
            try:
                reframe.reframe_vertical(cut_path, vert_path)
            except Exception as exc:  # noqa: BLE001
                print(f"[render] reframe fallback ({exc})")
                vert_path = cut_path

            _update(db, job, stage=5, progress=0.93, message="Burning ASS subtitles")
            final_path = str(settings.clips_dir / f"{job.id}.mp4")
            win_segments = _words(segments, start_s, end_s)
            if win_segments:
                ass_path = str(settings.clips_dir / f"{job.id}.ass")
                subtitles.build_ass(win_segments, ass_path, start_s)
                try:
                    subtitles.burn(vert_path, ass_path, final_path)
                except Exception as exc:  # noqa: BLE001
                    print(f"[render] subtitle burn fallback ({exc})")
                    Path(vert_path).replace(final_path)
            else:
                Path(vert_path).replace(final_path)

            clip = Clip(
                job_id=job.id, title=f"Highlight {start_s:.0f}-{end_s:.0f}s",
                file_path=final_path, start_s=start_s, end_s=end_s, score=score,
                hook=sig.hook, pace=sig.pace, sentiment=sig.sentiment, face=sig.face,
            )
            db.add(clip)
            db.flush()
            _update(db, job, stage=6, progress=1.0, status=JobStatus.completed,
                    message="Complete", clip_id=clip.id)
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
