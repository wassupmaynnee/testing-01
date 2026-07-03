from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..billing_core import tier_by_key
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import CreditLedger, Referral, User
from ..ratelimit import rate_limit
from ..responses import err, ok
from ..security import SESSION_COOKIE, hash_password, issue_session, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Pragmatic email check — RFC-perfect validation is a rabbit hole; this rejects
# the obvious garbage while accepting anything Stripe/Postgres will happily store.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD = 8


def _issue_session_cookie(resp: JSONResponse, user_id: str) -> None:
    """Single place that sets the frozen httponly mf_session cookie (login + signup).
    Secure is enabled in production so the session never rides plain HTTP."""
    resp.set_cookie(
        SESSION_COOKIE, issue_session(user_id),
        httponly=True, samesite="lax",
        secure=get_settings().app_env == "production",
        max_age=60 * 60 * 24 * 7, path="/",
    )


@router.post("/signup", dependencies=[Depends(rate_limit("signup", 5, 60))])
def signup(
    email: str = Form(...),
    password: str = Form(...),
    ref: str = Form(None),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return err("invalid_email", "Enter a valid email address.", status_code=422)
    if len(password) < _MIN_PASSWORD:
        return err("weak_password",
                   f"Password must be at least {_MIN_PASSWORD} characters.", status_code=422)
    if db.query(User).filter(User.email == email).one_or_none() is not None:
        return err("email_taken", "An account with that email already exists.", status_code=409)

    # Free tier's one-time trial credits come straight from the frozen catalog.
    free = tier_by_key("free")
    grant = free.monthly_credits

    user = User(email=email, password_hash=hash_password(password), credits=grant,
                tier="free", referral_code=uuid.uuid4().hex[:8])
    db.add(user)
    db.flush()
    db.add(CreditLedger(user_id=user.id, delta=grant, reason="signup_trial"))

    # Referral attribution (PENDING only — credits are granted exclusively by the
    # HMAC-verified Stripe webhook on the referred user's first paid subscription;
    # see saas/billing_core.py). Guards: referrer must exist and not be this
    # account/email; the unique constraint on referred_user_id caps rewards at
    # one per referred user, ever.
    referred_by = None
    if ref:
        referrer = db.query(User).filter(User.referral_code == ref.strip()).one_or_none()
        if referrer is not None and referrer.id != user.id and referrer.email != email:
            db.add(Referral(referrer_id=referrer.id, referred_user_id=user.id))
            referred_by = referrer.referral_code

    db.commit()

    resp = ok({"id": user.id, "email": user.email, "credits": user.credits,
               "referredBy": referred_by}, status_code=201)
    _issue_session_cookie(resp, user.id)
    return resp


@router.post("/login", dependencies=[Depends(rate_limit("login", 10, 60))])
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return err("invalid_credentials", "Email or password is incorrect.", status_code=401)
    resp = ok({"id": user.id, "email": user.email, "credits": user.credits})
    _issue_session_cookie(resp, user.id)
    return resp


@router.post("/logout")
def logout():
    resp = ok({"loggedOut": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me")
def me(user: User = Depends(current_user)):
    return ok({"id": user.id, "email": user.email, "credits": user.credits, "tier": user.tier})
