from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..billing_core import tier_by_key
from ..db import get_db
from ..deps import current_user
from ..models import CreditLedger, User
from ..responses import err, ok
from ..security import SESSION_COOKIE, hash_password, issue_session, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Pragmatic email check — RFC-perfect validation is a rabbit hole; this rejects
# the obvious garbage while accepting anything Stripe/Postgres will happily store.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD = 8


def _issue_session_cookie(resp: JSONResponse, user_id: str) -> None:
    """Single place that sets the frozen httponly mf_session cookie (login + signup)."""
    resp.set_cookie(
        SESSION_COOKIE, issue_session(user_id),
        httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7, path="/",
    )


@router.post("/signup")
def signup(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
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

    user = User(email=email, password_hash=hash_password(password), credits=grant, tier="free")
    db.add(user)
    db.flush()
    db.add(CreditLedger(user_id=user.id, delta=grant, reason="signup_trial"))
    db.commit()

    resp = ok({"id": user.id, "email": user.email, "credits": user.credits}, status_code=201)
    _issue_session_cookie(resp, user.id)
    return resp


@router.post("/login")
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
