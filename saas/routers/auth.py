from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..responses import err, ok
from ..security import SESSION_COOKIE, issue_session, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return err("invalid_credentials", "Email or password is incorrect.", status_code=401)
    resp = ok({"id": user.id, "email": user.email, "credits": user.credits})
    resp.set_cookie(
        SESSION_COOKIE, issue_session(user.id),
        httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7, path="/",
    )
    return resp


@router.post("/logout")
def logout():
    resp = ok({"loggedOut": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me")
def me(user: User = Depends(current_user)):
    return ok({"id": user.id, "email": user.email, "credits": user.credits})
