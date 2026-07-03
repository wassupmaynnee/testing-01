from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form
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


def _serve_ref(ref: str, *, media: str = "video/mp4", download_name: str | None = None):
    """Serve a stored ref from R2 (presigned redirect) or the local volume."""
    if is_r2_ref(ref):
        return RedirectResponse(presigned_url(ref), status_code=307)
    if not Path(ref).exists():
        return err("not_found", "File not found.", status_code=404)
    if download_name:
        return FileResponse(ref, media_type=media, filename=download_name)
    return FileResponse(ref, media_type=media)


def _serve(clip: Clip, *, download: bool = False):
    return _serve_ref(
        clip.file_path,
        download_name=f"{clip.title or 'clip'}.mp4" if download else None,
    )


def _clip_dict(clip: Clip, job: Job | None = None) -> dict:
    d = {
        "id": clip.id,
        "title": clip.title,
        "score": round(clip.score, 4),
        "signals": {"hook": round(clip.hook, 3), "pace": round(clip.pace, 3),
                    "sentiment": round(clip.sentiment, 3), "face": round(clip.face, 3)},
        "startS": clip.start_s,
        "endS": clip.end_s,
        "duration": round(max(clip.end_s - clip.start_s, 0.0), 1),
        "aspect": clip.aspect or "9:16",
        "featured": bool(clip.featured),
        "createdAt": clip.created_at.isoformat() if clip.created_at else None,
        "fileUrl": f"/api/clips/{clip.id}/file",
        "downloadUrl": f"/api/clips/{clip.id}/download",
        "thumbUrl": f"/api/clips/{clip.id}/thumb" if clip.thumb_path else None,
    }
    if job is not None:
        # Never leak local upload paths; only the YouTube URL is user-facing.
        d["source"] = {
            "kind": job.kind.value,
            "ref": job.source_ref if job.kind.value == "youtube" else "Uploaded video",
            "jobId": job.id,
        }
        d["jobStatus"] = job.status.value
    return d


# --------------------------------------------------------------------------- #
# PUBLIC featured showcase — the homepage reads these WITHOUT auth. Featuring  #
# a clip is the explicit act of making it public; nothing else is exposed.    #
# NOTE: defined before the /{clip_id} routes so "featured" never matches as   #
# a clip id.                                                                  #
# --------------------------------------------------------------------------- #
@router.get("/featured")
def featured_clips(db: Session = Depends(get_db)):
    """Public: clips explicitly flagged for the homepage showcase, best first."""
    rows = (
        db.query(Clip).filter(Clip.featured.is_(True))
        .order_by(Clip.score.desc()).limit(12).all()
    )
    items = []
    for c in rows:
        d = _clip_dict(c)
        d["fileUrl"] = f"/api/clips/featured/{c.id}/file"
        d["thumbUrl"] = f"/api/clips/featured/{c.id}/thumb" if c.thumb_path else None
        d.pop("downloadUrl", None)
        items.append(d)
    return ok({"items": items})


@router.get("/featured/{clip_id}/file")
def featured_file(clip_id: str, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip or not clip.featured:
        return err("not_found", "Clip not found.", status_code=404)
    return _serve(clip)


@router.get("/featured/{clip_id}/thumb")
def featured_thumb(clip_id: str, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip or not clip.featured or not clip.thumb_path:
        return err("not_found", "Thumbnail not found.", status_code=404)
    return _serve_ref(clip.thumb_path, media="image/jpeg")


@router.get("")
def list_clips(
    limit: int = 20,
    offset: int = 0,
    featured: bool | None = None,
    sort: str = "score",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Paginated list of THIS user's rendered clips, engagement-score-first by
    default (sort=recent for newest-first). featured=true filters to showcase picks."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    q = (
        db.query(Clip, Job)
        .join(Job, Clip.job_id == Job.id)
        .filter(Job.user_id == user.id)
    )
    if featured is not None:
        q = q.filter(Clip.featured.is_(featured))
    q = q.order_by(Clip.created_at.desc() if sort == "recent" else Clip.score.desc())
    total = q.count()
    items = [_clip_dict(clip, job) for clip, job in q.limit(limit).offset(offset).all()]
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/{clip_id}")
def clip_meta(clip_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = _owned_clip(clip_id, user, db)
    if not clip:
        return err("not_found", "Clip not found.", status_code=404)
    return ok(_clip_dict(clip, db.get(Job, clip.job_id)))


@router.post("/{clip_id}/feature")
def toggle_feature(
    clip_id: str,
    on: bool = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Owner-only: opt a clip in/out of the PUBLIC homepage showcase. Featuring
    is the explicit act of making that clip publicly viewable."""
    clip = _owned_clip(clip_id, user, db)
    if not clip:
        return err("not_found", "Clip not found.", status_code=404)
    clip.featured = bool(on)
    db.add(clip)
    db.commit()
    return ok({"id": clip.id, "featured": clip.featured})


@router.get("/{clip_id}/thumb")
def clip_thumb(clip_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = _owned_clip(clip_id, user, db)
    if not clip or not clip.thumb_path:
        return err("not_found", "Thumbnail not found.", status_code=404)
    return _serve_ref(clip.thumb_path, media="image/jpeg")


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
