"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import SESSION_COOKIE, read_session


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_session(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="not_authenticated")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return user
