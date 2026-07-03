"""Idempotently seed the dev user so the acceptance test has a real login."""
from __future__ import annotations

from .config import get_settings
from .observability import log_event
from .db import SessionLocal
from .models import CreditLedger, User
from .security import hash_password


def seed() -> None:
    s = get_settings()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == s.seed_user_email).one_or_none()
        if existing:
            log_event("seed user already exists")
            return
        user = User(
            email=s.seed_user_email,
            password_hash=hash_password(s.seed_user_password),
            credits=s.seed_user_credits,
        )
        db.add(user)
        db.flush()
        db.add(CreditLedger(user_id=user.id, delta=s.seed_user_credits, reason="signup_trial"))
        db.commit()
        log_event("seed user created", credits=s.seed_user_credits)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
