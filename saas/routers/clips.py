from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Clip, Job, User
from ..responses import err, ok
from ..storage import is_r2_ref, presigned_url

router = APIRouter(prefix="/api/clips", tags=["clips"])


def _owned_clip(clip_id: str, user: User, db: Session) -> Clip | None:
    clip = db.get(Clip, clip_id)
    if not clip:
        return None
    job = db.get(Job, clip.job_id)
    if not job or job.user_id != user.id:
        return None
    return clip


def _serve(clip: Clip, *, download: bool = False):
    """Serve a clip from R2 (presigned redirect) or the local volume."""
    if is_r2_ref(clip.file_path):
        return RedirectResponse(presigned_url(clip.file_path), status_code=307)
    if not Path(clip.file_path).exists():
        return err("not_found", "Clip file not found.", status_code=404)
    if download:
        return FileResponse(clip.file_path, media_type="video/mp4",
                            filename=f"{clip.title or 'clip'}.mp4")
    return FileResponse(clip.file_path, media_type="video/mp4")


@router.get("")
def list_clips(
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Paginated, newest-first list of THIS user's rendered clips (across all jobs)."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    q = (
        db.query(Clip, Job)
        .join(Job, Clip.job_id == Job.id)
        .filter(Job.user_id == user.id)
        .order_by(Clip.created_at.desc())
    )
    total = q.count()
    items = []
    for clip, job in q.limit(limit).offset(offset).all():
        items.append({
            "id": clip.id,
            "title": clip.title,
            "score": round(clip.score, 4),
            "startS": clip.start_s,
            "endS": clip.end_s,
            "createdAt": clip.created_at.isoformat() if clip.created_at else None,
            # Never leak local upload paths; only the YouTube URL is user-facing.
            "source": {
                "kind": job.kind.value,
                "ref": job.source_ref if job.kind.value == "youtube" else "Uploaded video",
                "jobId": job.id,
            },
            "jobStatus": job.status.value,
            "fileUrl": f"/api/clips/{clip.id}/file",
            "downloadUrl": f"/api/clips/{clip.id}/download",
        })
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/{clip_id}")
def clip_meta(clip_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = _owned_clip(clip_id, user, db)
    if not clip:
        return err("not_found", "Clip not found.", status_code=404)
    return ok({
        "id": clip.id, "title": clip.title, "score": round(clip.score, 4),
        "startS": clip.start_s, "endS": clip.end_s,
        "fileUrl": f"/api/clips/{clip.id}/file",
        "downloadUrl": f"/api/clips/{clip.id}/download",
    })


@router.get("/{clip_id}/file")
def clip_file(clip_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = _owned_clip(clip_id, user, db)
    if not clip:
        return err("not_found", "Clip file not found.", status_code=404)
    return _serve(clip)


@router.get("/{clip_id}/download")
def clip_download(clip_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = _owned_clip(clip_id, user, db)
    if not clip:
        return err("not_found", "Clip file not found.", status_code=404)
    return _serve(clip, download=True)
