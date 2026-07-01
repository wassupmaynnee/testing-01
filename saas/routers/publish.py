from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import publish_core
from ..db import get_db
from ..deps import current_user
from ..models import Clip, Job, User
from ..responses import deferred, err, ok

router = APIRouter(prefix="/api/publish", tags=["publish"])


def _owned_clip(clip_id: str, user: User, db: Session) -> Clip | None:
    clip = db.get(Clip, clip_id)
    if not clip:
        return None
    job = db.get(Job, clip.job_id)
    if not job or job.user_id != user.id:
        return None
    return clip


@router.get("/providers")
def list_providers(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Publishing destinations + this user's connected accounts."""
    return ok({
        "providers": publish_core.providers(),
        "accounts": publish_core.connected_accounts(db, user),
    })


@router.get("/analytics")
def analytics(force: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Read-only analytics for the user's OWN connected YouTube channel. Cached to
    respect quotas; ?force=true refreshes. Prompts reconnect if the stored token
    predates the analytics scope."""
    if not publish_core.youtube_enabled():
        return deferred("YouTube analytics",
                        "set YOUTUBE_OAUTH_CLIENT_ID / _SECRET to enable publishing")
    return ok(publish_core.channel_analytics(db, user, force=force))


@router.get("/youtube/connect")
def youtube_connect(user: User = Depends(current_user)):
    """Return the Google consent URL the dashboard redirects the user to."""
    if not publish_core.youtube_enabled():
        return deferred("YouTube publishing",
                        "set YOUTUBE_OAUTH_CLIENT_ID / _SECRET to enable publishing")
    return ok({"url": publish_core.authorize_url(user.id)})


@router.get("/youtube/callback")
def youtube_callback(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """OAuth redirect target. Verifies state, stores encrypted tokens, returns to app."""
    if not publish_core.youtube_enabled():
        return deferred("YouTube publishing",
                        "set YOUTUBE_OAUTH_CLIENT_ID / _SECRET to enable publishing")

    params = request.query_params
    if params.get("error"):
        return RedirectResponse(url="/dashboard?connect=youtube&error=denied", status_code=303)

    code = params.get("code", "")
    state = params.get("state", "")
    if not code or not publish_core.verify_state(state, user.id):
        return RedirectResponse(url="/dashboard?connect=youtube&error=bad_state", status_code=303)

    try:
        publish_core.connect_account(db, user, code)
    except Exception:  # noqa: BLE001 — surface a clean redirect, never a 500 page
        return RedirectResponse(url="/dashboard?connect=youtube&error=exchange_failed",
                                status_code=303)
    return RedirectResponse(url="/dashboard?connect=youtube&ok=1", status_code=303)


@router.post("/youtube/disconnect")
def youtube_disconnect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    removed = publish_core.disconnect(db, user, publish_core.PROVIDER_YOUTUBE)
    return ok({"disconnected": removed, "provider": publish_core.PROVIDER_YOUTUBE})


@router.post("/{clip_id}")
def publish_clip(clip_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """
    Explicit, user-initiated publish of one owned clip. Uploads at PRIVATE
    visibility ONLY (enforced in publish_core.video_insert_body). Never auto-runs.
    """
    if not publish_core.youtube_enabled():
        return deferred("OAuth publishing", "saas/publish_core.py:publish_private()")

    clip = _owned_clip(clip_id, user, db)
    if not clip:
        return err("not_found", "Clip not found.", status_code=404)

    try:
        result = publish_core.publish_private(db, user, clip)
    except LookupError:
        return err("not_connected",
                   "Connect a YouTube account before publishing.", status_code=409)
    except FileNotFoundError:
        return err("clip_missing", "Clip file is no longer available.", status_code=404)
    except Exception as exc:  # noqa: BLE001 — surface upload/network errors cleanly
        return err("publish_failed", f"Upload failed: {exc}", status_code=502)
    return ok(result)
