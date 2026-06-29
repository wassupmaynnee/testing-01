from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Job, User
from ..responses import err
from ..sse import stream

router = APIRouter(prefix="/api/stream", tags=["sse"])


@router.get("/{job_id}")
def job_stream(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or job.user_id != user.id:
        return err("not_found", "Job not found.", status_code=404)
    return StreamingResponse(
        stream(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
