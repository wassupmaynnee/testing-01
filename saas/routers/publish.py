from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import current_user
from ..models import User
from ..responses import deferred

router = APIRouter(prefix="/api/publish", tags=["publish"])


@router.post("/{clip_id}")
def publish_clip(clip_id: str, user: User = Depends(current_user)):
    # DEFERRED seam. When implemented: OAuth 2.0 ONLY, visibility forced to
    # private / SELF_ONLY. Browser-automation upload hooks are prohibited.
    return deferred("OAuth publishing", "saas/publish_core.py:publish_private()")
