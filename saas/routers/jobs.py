from __future__ import annotations


from fastapi import APIRouter, Depends, Form, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import IngestKind, Job, JobStatus, User
from ..pipeline.ingest_url import is_youtube_url
from ..ratelimit import rate_limit
from ..responses import err, ok
from ..sse import enqueue_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_ALLOWED = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


@router.post("", dependencies=[Depends(rate_limit("generate", 20, 60))])
def create_job(
    file: UploadFile | None = None,
    url: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Create a clip job from EITHER an uploaded video OR a YouTube URL. Credits
    are charged per rendered clip in the pipeline (credits = clips), so a single
    URL that yields N clips costs N credits; we only gate on having at least one."""
    if user.credits <= 0:
        return err("no_credits", "You are out of credits.", status_code=402)

    settings = get_settings()
    settings.ensure_dirs()

    # --- YouTube URL path ---
    if url:
        if not is_youtube_url(url):
            return err("bad_url", "Enter a valid YouTube URL.", status_code=400)
        job = Job(user_id=user.id, kind=IngestKind.youtube, source_ref=url.strip(),
                  status=JobStatus.queued)
        db.add(job)
        db.commit()
        enqueue_job(job.id)
        return ok({"id": job.id, "status": job.status.value, "stage": job.stage,
                   "kind": job.kind.value}, status_code=201)

    # --- Uploaded file path ---
    if file is None or not file.filename:
        return err("no_source", "Provide a video file or a YouTube URL.", status_code=400)

    name = file.filename.lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in _ALLOWED:
        return err("bad_format", f"Unsupported file type '{ext}'. Upload an MP4.", status_code=415)

    job = Job(user_id=user.id, kind=IngestKind.upload, source_ref="", status=JobStatus.queued)
    db.add(job)
    db.flush()

    dest = settings.uploads_dir / f"{job.id}{ext}"  # server-generated name (no traversal)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    written = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                db.delete(job)
                db.commit()
                return err("file_too_large",
                           f"File exceeds the {settings.max_upload_mb} MB limit.",
                           status_code=413)
            out.write(chunk)
    job.source_ref = str(dest)
    db.commit()

    enqueue_job(job.id)
    return ok({"id": job.id, "status": job.status.value, "stage": job.stage,
               "kind": job.kind.value}, status_code=201)


@router.get("")
def list_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    jobs = (
        db.query(Job).filter(Job.user_id == user.id).order_by(Job.created_at.desc()).all()
    )
    return ok([_job_dict(j) for j in jobs])


@router.get("/{job_id}")
def get_job(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or job.user_id != user.id:
        return err("not_found", "Job not found.", status_code=404)
    return ok(_job_dict(job, with_clips=True))


def _job_dict(job: Job, with_clips: bool = False) -> dict:
    d = {
        "id": job.id,
        "kind": job.kind.value,
        "status": job.status.value,
        "stage": job.stage,
        "progress": job.progress,
        "error": job.error,
        "createdAt": job.created_at.isoformat(),
    }
    if with_clips:
        d["clips"] = [
            {
                "id": c.id, "title": c.title, "score": round(c.score, 4),
                "startS": c.start_s, "endS": c.end_s,
                "signals": {"hook": c.hook, "pace": c.pace,
                            "sentiment": c.sentiment, "face": c.face},
            }
            for c in job.clips
        ]
    return d
