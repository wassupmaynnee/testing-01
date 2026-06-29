from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import IngestKind, Job, JobStatus, User
from ..responses import err, ok
from ..sse import enqueue_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_ALLOWED = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


@router.post("")
def create_job(file: UploadFile, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.credits <= 0:
        return err("no_credits", "You are out of credits.", status_code=402)

    name = (file.filename or "upload.mp4").lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in _ALLOWED:
        return err("bad_format", f"Unsupported file type '{ext}'. Upload an MP4.", status_code=415)

    settings = get_settings()
    settings.ensure_dirs()
    job = Job(user_id=user.id, kind=IngestKind.upload, source_ref="", status=JobStatus.queued)
    db.add(job)
    db.flush()

    dest = settings.uploads_dir / f"{job.id}{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    job.source_ref = str(dest)

    # Deduct one credit on accept (real credit accounting in DB).
    from ..models import CreditLedger
    user.credits -= 1
    db.add(CreditLedger(user_id=user.id, delta=-1, reason=f"job:{job.id}"))
    db.commit()

    enqueue_job(job.id)
    return ok({"id": job.id, "status": job.status.value, "stage": job.stage}, status_code=201)


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
