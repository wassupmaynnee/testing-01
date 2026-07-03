"""Referral program: attribution at signup, credit grant ONLY via the verified
webhook on first paid subscription, idempotency against retries, fraud guards."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

from saas.billing_core import (
    REFERRAL_CREDITS_REFERRED,
    REFERRAL_CREDITS_REFERRER,
    handle_webhook,
    tier_by_key,
)
from saas.db import SessionLocal
from saas.models import Referral, User

SECRET = "whsec_test_secret"  # matches conftest STRIPE_WEBHOOK_SECRET


def _sign(payload: bytes) -> str:
    ts = int(time.time())
    sig = hmac.new(SECRET.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _event(event_id: str, user_id: str, tier: str = "pro") -> bytes:
    return json.dumps({
        "id": event_id, "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_x", "customer": "cus_x",
                            "metadata": {"user_id": user_id, "tier_key": tier,
                                         "interval": "monthly"}}},
    }).encode()


def _mk_users(db) -> tuple[User, User]:
    referrer = User(email="ref@x.dev", password_hash="h", credits=0,
                    referral_code="refcode1")
    referred = User(email="new@x.dev", password_hash="h", credits=30,
                    referral_code="newcode1")
    db.add_all([referrer, referred])
    db.flush()
    db.add(Referral(referrer_id=referrer.id, referred_user_id=referred.id))
    db.commit()
    return referrer, referred


def test_grant_fires_once_on_first_paid_subscription():
    db = SessionLocal()
    referrer, referred = _mk_users(db)
    pro = tier_by_key("pro")

    payload = _event("evt_ref_1", referred.id)
    out = handle_webhook(payload, _sign(payload))
    assert out["status"] == "granted"

    db.expire_all()
    assert db.get(User, referrer.id).credits == REFERRAL_CREDITS_REFERRER
    assert db.get(User, referred.id).credits == 30 + pro.monthly_credits + REFERRAL_CREDITS_REFERRED
    r = db.query(Referral).filter_by(referred_user_id=referred.id).one()
    assert r.status == "credited" and r.credited_at is not None
    db.close()


def test_duplicate_webhook_delivery_is_a_noop():
    db = SessionLocal()
    referrer, referred = _mk_users(db)
    payload = _event("evt_ref_dup", referred.id)
    assert handle_webhook(payload, _sign(payload))["status"] == "granted"
    assert handle_webhook(payload, _sign(payload))["status"] == "duplicate"
    db.expire_all()
    assert db.get(User, referrer.id).credits == REFERRAL_CREDITS_REFERRER  # not doubled
    db.close()


def test_second_payment_never_regrants():
    db = SessionLocal()
    referrer, referred = _mk_users(db)
    p1 = _event("evt_ref_m1", referred.id)
    p2 = _event("evt_ref_m2", referred.id)  # renewal: NEW event id
    handle_webhook(p1, _sign(p1))
    handle_webhook(p2, _sign(p2))
    db.expire_all()
    assert db.get(User, referrer.id).credits == REFERRAL_CREDITS_REFERRER  # once, ever
    db.close()


def test_no_referral_no_bonus():
    db = SessionLocal()
    solo = User(email="solo@x.dev", password_hash="h", credits=0, referral_code="solocode")
    db.add(solo)
    db.commit()
    payload = _event("evt_solo", solo.id)
    handle_webhook(payload, _sign(payload))
    db.expire_all()
    assert db.get(User, solo.id).credits == tier_by_key("pro").monthly_credits  # tier only
    db.close()
