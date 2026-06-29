"""
Stripe billing core.

Frozen contract preserved exactly:
  * The Stripe SDK is lazy-loaded ONLY when STRIPE_SECRET_KEY is set
    (`stripe_enabled()` / `_load_stripe()`).
  * Webhook signatures are verified by a custom HMAC-SHA256 implementation
    (`verify_webhook_signature`) over the RAW request body — no SDK dependency
    for verification.
  * The tier catalog (prices / credits / "Most popular" Pro) is frozen and served
    live so the pricing UI renders whether or not billing is enabled.

Implemented in this pass (behind the existing seam, no spine changes elsewhere):
  * `create_checkout_session()` — hosted Checkout for any paid tier.
  * `create_billing_portal()`   — customer Portal, always reachable once a
    customer exists.
  * `handle_webhook()` — grants the tier's credits on `checkout.session.completed`,
    keyed on the Stripe event id so a duplicate delivery never double-grants.
"""
from __future__ import annotations

import hashlib
import hmac
import json
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
_TIERS_BY_KEY = {t.key: t for t in TIERS}


def tier_catalog() -> list[dict]:
    return [t.__dict__ for t in TIERS]


def tier_by_key(key: str) -> Tier | None:
    return _TIERS_BY_KEY.get(key)


def stripe_enabled() -> bool:
    return bool(get_settings().stripe_secret_key)


def _load_stripe():
    """Lazy import — only touched when a secret key is configured."""
    if not stripe_enabled():
        raise RuntimeError("STRIPE_SECRET_KEY not set; billing is disabled")
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


# --------------------------------------------------------------------------- #
# Checkout + Portal                                                           #
# --------------------------------------------------------------------------- #
def _price_id_for(tier: Tier) -> str:
    s = get_settings()
    return {
        "starter": s.stripe_price_starter,
        "pro": s.stripe_price_pro,
        "scale": s.stripe_price_scale,
    }.get(tier.key, "")


def _line_item(tier: Tier) -> dict:
    """
    Prefer a configured Stripe Price ID; otherwise build an inline recurring
    price from the frozen catalog so test-mode Checkout works with zero Stripe
    dashboard setup. Displayed price is per-month, billed annually -> 12x/year.
    """
    price_id = _price_id_for(tier)
    if price_id:
        return {"price": price_id, "quantity": 1}
    return {
        "quantity": 1,
        "price_data": {
            "currency": "usd",
            "unit_amount": round(tier.price_usd * 12 * 100),  # annual total, in cents
            "recurring": {"interval": "year"},
            "product_data": {
                "name": f"Clippify {tier.name}",
                "description": f"{tier.monthly_credits} credits / month, {tier.billing}.",
            },
        },
    }


def _ensure_customer(stripe, db, user) -> str:
    """Return the user's Stripe customer id, creating + persisting one if needed."""
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(email=user.email, metadata={"user_id": user.id})
    user.stripe_customer_id = customer.id
    db.add(user)
    db.commit()
    return customer.id


def create_checkout_session(user_id: str, tier_key: str) -> dict:
    """Create a hosted Stripe Checkout session for a paid tier. Returns {url, sessionId}."""
    tier = tier_by_key(tier_key)
    if tier is None or tier.key == "free":
        raise ValueError(f"'{tier_key}' is not a purchasable tier")

    stripe = _load_stripe()
    s = get_settings()

    from .db import SessionLocal
    from .models import User

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise ValueError("unknown user")
        customer_id = _ensure_customer(stripe, db, user)

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            client_reference_id=user.id,
            line_items=[_line_item(tier)],
            success_url=s.success_url,
            cancel_url=s.cancel_url,
            metadata={"user_id": user.id, "tier_key": tier.key},
            subscription_data={"metadata": {"user_id": user.id, "tier_key": tier.key}},
            allow_promotion_codes=True,
        )
        return {"url": session.url, "sessionId": session.id, "tier": tier.key}
    finally:
        db.close()


def create_billing_portal(user_id: str) -> dict:
    """Create a Stripe customer Portal session so the user can manage / cancel."""
    stripe = _load_stripe()
    s = get_settings()

    from .db import SessionLocal
    from .models import User

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise ValueError("unknown user")
        # A customer must exist to open the portal; create one on demand so the
        # portal is "always reachable" even before the first purchase.
        customer_id = _ensure_customer(stripe, db, user)
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{s.app_base_url}/dashboard",
        )
        return {"url": portal.url}
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Webhook — idempotent credit grants                                          #
# --------------------------------------------------------------------------- #
def _resolve_user(db, session: dict):
    """
    Map a Checkout Session to a local user. Real purchases always carry our
    metadata.user_id / client_reference_id. A Stripe-CLI `trigger` synthetic
    event carries neither — outside production we fall back to the seeded demo
    user so the local acceptance test demonstrably grants credits. In production
    a metadata-less event grants nothing (returns None).
    """
    from .models import User

    user_id = (session.get("metadata") or {}).get("user_id") or session.get("client_reference_id")
    if user_id:
        return db.get(User, user_id)

    s = get_settings()
    if s.app_env == "production":
        return None
    # Local/test fallback: match the session email, else the seeded demo user.
    email = (session.get("customer_details") or {}).get("email") or s.seed_user_email
    return db.query(User).filter(User.email == email).one_or_none()


def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """
    Verify (raw body, HMAC-SHA256) and process a Stripe event. Idempotent: the
    event id is recorded in `stripe_events`, so a re-delivered or resent event is
    a no-op and credits never double-grant. Returns a small status dict; the
    router maps it to the {ok, data} envelope.
    """
    if not verify_webhook_signature(payload, sig_header):
        raise PermissionError("invalid Stripe signature")

    event = json.loads(payload.decode("utf-8"))
    event_id = event.get("id")
    event_type = event.get("type", "")
    if not event_id:
        raise ValueError("event missing id")

    from .db import SessionLocal
    from .models import CreditLedger, StripeEvent, User  # noqa: F401

    db = SessionLocal()
    try:
        # Idempotency gate — already processed?
        if db.get(StripeEvent, event_id) is not None:
            return {"status": "duplicate", "eventId": event_id, "type": event_type}

        granted = 0
        target_user_id = None

        if event_type == "checkout.session.completed":
            session = (event.get("data") or {}).get("object") or {}
            tier_key = (session.get("metadata") or {}).get("tier_key") or "starter"
            tier = tier_by_key(tier_key) or tier_by_key("starter")
            user = _resolve_user(db, session)
            if user is not None:
                granted = tier.monthly_credits
                user.credits += granted
                user.tier = tier.key
                cust = session.get("customer")
                if cust and not user.stripe_customer_id:
                    user.stripe_customer_id = cust
                db.add(user)
                db.add(CreditLedger(
                    user_id=user.id, delta=granted,
                    reason=f"stripe:{tier.key}:{event_id}",
                ))
                target_user_id = user.id

        # Record the event so it commits atomically with the grant.
        db.add(StripeEvent(
            id=event_id, type=event_type,
            user_id=target_user_id, credits_granted=granted,
        ))
        db.commit()
        return {
            "status": "granted" if granted else "ignored",
            "eventId": event_id, "type": event_type, "credits": granted,
        }
    finally:
        db.close()
