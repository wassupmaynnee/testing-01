"""Unit tests for the frozen billing contracts: raw-body HMAC-SHA256 webhook
verification and idempotent, ledger-keyed credit grants."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from saas import billing_core
from saas.billing_core import (
    handle_webhook,
    tier_by_key,
    tier_catalog,
    verify_webhook_signature,
)
from saas.db import SessionLocal
from saas.models import CreditLedger, StripeEvent, User

SECRET = "whsec_test_secret"  # matches conftest STRIPE_WEBHOOK_SECRET


def _sign(payload: bytes, secret: str = SECRET, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    signed = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


# --------------------------- signature verification --------------------------
def test_signature_roundtrip_valid():
    body = b'{"hello":"world"}'
    assert verify_webhook_signature(body, _sign(body)) is True


def test_signature_rejects_tampered_body():
    body = b'{"amount":100}'
    header = _sign(body)
    assert verify_webhook_signature(b'{"amount":999}', header) is False


def test_signature_rejects_expired_timestamp():
    body = b"{}"
    old = _sign(body, ts=int(time.time()) - 10_000)
    assert verify_webhook_signature(body, old) is False


def test_signature_rejects_missing_header():
    assert verify_webhook_signature(b"{}", "") is False


# ------------------------------ catalog invariants ---------------------------
def test_frozen_tier_catalog():
    catalog = tier_catalog()
    assert [t["monthly_credits"] for t in catalog] == [30, 200, 500, 1200]
    assert [t["price_usd"] for t in catalog] == [0.00, 14.99, 29.99, 59.99]
    assert tier_by_key("free").monthly_credits == 30
    assert tier_by_key("pro").monthly_credits == 500
    assert tier_by_key("pro").price_usd == 29.99
    assert [t.monthly_credits for t in billing_core.TIERS] == [30, 200, 500, 1200]


# ------------------------------- webhook grants ------------------------------
def _completed_event(session_id: str, user_id: str, tier: str = "pro", event_id: str | None = None):
    return {
        "id": event_id or f"evt_{session_id}",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "client_reference_id": user_id,
            "customer": "cus_test_123",
            "metadata": {"tier_key": tier, "user_id": user_id},
        }},
    }


def _make_user(credits: int = 30) -> str:
    db = SessionLocal()
    try:
        u = User(email="buyer@example.com", password_hash="x", credits=credits)
        db.add(u)
        db.commit()
        return u.id
    finally:
        db.close()


def test_webhook_grants_credits_once():
    uid = _make_user(credits=30)
    event = _completed_event("cs_test_1", uid, event_id="evt_grant_1")
    payload = json.dumps(event).encode()
    result = handle_webhook(payload, _sign(payload))

    assert result["status"] == "granted"
    assert result["credits"] == 500
    db = SessionLocal()
    try:
        assert db.get(User, uid).credits == 530
        rows = db.query(CreditLedger).filter(
            CreditLedger.reason == "stripe:pro:evt_grant_1").all()
        assert len(rows) == 1
        assert db.get(StripeEvent, "evt_grant_1") is not None
    finally:
        db.close()


def test_webhook_is_idempotent_on_redelivery():
    uid = _make_user(credits=30)
    payload = json.dumps(_completed_event("cs_test_2", uid, event_id="evt_dupe")).encode()
    header = _sign(payload)
    first = handle_webhook(payload, header)
    second = handle_webhook(payload, header)  # exact same event re-fired

    assert first["status"] == "granted"
    assert second["status"] == "duplicate"
    db = SessionLocal()
    try:
        assert db.get(User, uid).credits == 530  # NOT 1030
        rows = db.query(CreditLedger).filter(CreditLedger.user_id == uid).all()
        assert len(rows) == 1
    finally:
        db.close()


def test_webhook_bad_signature_raises():
    payload = json.dumps(_completed_event("cs_x", "nope")).encode()
    with pytest.raises(PermissionError):
        handle_webhook(payload, "t=1,v1=deadbeef")


def test_webhook_ignores_other_event_types():
    payload = json.dumps({"id": "evt_inv", "type": "invoice.paid",
                          "data": {"object": {}}}).encode()
    result = handle_webhook(payload, _sign(payload))
    assert result["status"] == "ignored"
    assert result["credits"] == 0


def test_webhook_unresolved_identity_grants_nothing():
    # A synthetic event with no user_id/client_reference_id and no matching
    # demo user in the test DB resolves to no one -> no credits granted.
    payload = json.dumps({
        "id": "evt_syn", "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_syn", "metadata": {}}},
    }).encode()
    result = handle_webhook(payload, _sign(payload))
    assert result["status"] == "ignored"
    assert result["credits"] == 0
