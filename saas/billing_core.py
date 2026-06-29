"""
Stripe billing core — DEFERRED seam in the walking-skeleton pass.

The tier catalog below is REAL (frozen prices/credits) and served live so the
pricing UI works. The purchase + webhook flow is deferred: the Stripe SDK is
lazy-loaded only when STRIPE_SECRET_KEY is present, and webhook signatures are
verified with a custom HMAC-SHA256 implementation (no SDK dependency for verify).

Next pass implements: hosted checkout, customer portal, and credit grants on
`checkout.session.completed`. It plugs in at create_checkout_session() and
handle_webhook() without touching any other module.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

from .config import get_settings


@dataclass(frozen=True)
class Tier:
    key: str
    name: str
    monthly_credits: int
    price_usd: float  # 0 for free; others billed annually
    billing: str


# FROZEN tier catalog.
TIERS: list[Tier] = [
    Tier("free", "Free", 30, 0.00, "one-time trial on signup"),
    Tier("starter", "Starter", 200, 14.99, "billed annually"),
    Tier("pro", "Pro", 500, 29.99, "billed annually"),
    Tier("scale", "Scale", 1200, 59.99, "billed annually"),
]


def tier_catalog() -> list[dict]:
    return [t.__dict__ for t in TIERS]


def stripe_enabled() -> bool:
    return bool(get_settings().stripe_secret_key)


def _load_stripe():
    """Lazy import — only touched when a secret key is configured."""
    if not stripe_enabled():
        raise RuntimeError("STRIPE_SECRET_KEY not set; billing is deferred")
    import stripe  # noqa: PLC0415  (intentional lazy load)
    stripe.api_key = get_settings().stripe_secret_key
    return stripe


def verify_webhook_signature(payload: bytes, sig_header: str, tolerance: int = 300) -> bool:
    """
    Custom HMAC-SHA256 verification of Stripe's `t=...,v1=...` signature header.
    Reimplemented deliberately so verification has no SDK dependency.
    """
    secret = get_settings().stripe_webhook_secret
    if not secret or not sig_header:
        return False
    parts = dict(
        kv.split("=", 1) for kv in sig_header.split(",") if "=" in kv
    )
    timestamp = parts.get("t")
    v1 = parts.get("v1")
    if not timestamp or not v1:
        return False
    if abs(time.time() - int(timestamp)) > tolerance:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


def create_checkout_session(user_id: str, tier_key: str) -> dict:
    """DEFERRED: next pass implements hosted checkout via _load_stripe()."""
    raise NotImplementedError("checkout deferred; implement at create_checkout_session()")


def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """DEFERRED: next pass grants credits on checkout.session.completed."""
    raise NotImplementedError("webhook handling deferred; implement at handle_webhook()")
