"""Refer-a-friend: my code/link, my referrals, totals. Rewards are granted only
by the HMAC-verified Stripe webhook (saas/billing_core.py) — this router is
read-only reporting plus the shareable-link surface."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..billing_core import REFERRAL_CREDITS_REFERRED, REFERRAL_CREDITS_REFERRER
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import Referral, User
from ..responses import ok

router = APIRouter(prefix="/api/referrals", tags=["referrals"])


def _mask(email: str) -> str:
    """user@example.com -> u***@example.com (never leak referred emails whole)."""
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


@router.get("")
def my_referrals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Older accounts predating the referral column get a code on first visit.
    if not user.referral_code:
        user.referral_code = uuid.uuid4().hex[:8]
        db.add(user)
        db.commit()

    rows = (
        db.query(Referral, User)
        .join(User, Referral.referred_user_id == User.id)
        .filter(Referral.referrer_id == user.id)
        .order_by(Referral.created_at.desc())
        .all()
    )
    earned = sum(r.credits_referrer for r, _ in rows if r.status == "credited")
    return ok({
        "code": user.referral_code,
        "link": f"{get_settings().app_base_url}/r/{user.referral_code}",
        "rewards": {"referrer": REFERRAL_CREDITS_REFERRER,
                    "referred": REFERRAL_CREDITS_REFERRED},
        "referrals": [
            {
                "email": _mask(ru.email),
                "status": r.status,  # pending | credited
                "signedUpAt": r.created_at.isoformat() if r.created_at else None,
                "creditedAt": r.credited_at.isoformat() if r.credited_at else None,
                "creditsEarned": r.credits_referrer,
            }
            for r, ru in rows
        ],
        "totalEarned": earned,
    })
