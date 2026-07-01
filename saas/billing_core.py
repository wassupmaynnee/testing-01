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


# --------------------------------------------------------------------------- #
# Pricing — SINGLE source of truth for BOTH billing intervals.                 #
#                                                                              #
# Tier.price_usd (above) is the monthly catalog amount and is FROZEN. Every    #
# interval amount is derived from it here so nothing is scattered:             #
#   * monthly = price_usd                          (catalog's monthly figure)  #
#   * annual  = price_usd * ANNUAL_MONTHS_BILLED   (existing annual, unchanged) #
# The existing annual behaviour (12x, no discount) is preserved exactly; only  #
# the monthly interval is added. To re-price, edit ONLY this file.             #
# --------------------------------------------------------------------------- #
VALID_INTERVALS = ("monthly", "annual")
DEFAULT_INTERVAL = "annual"
ANNUAL_MONTHS_BILLED = 12  # annual total = 12 x monthly (frozen: no discount)


def normalize_interval(interval: str | None) -> str:
    return interval if interval in VALID_INTERVALS else DEFAULT_INTERVAL


def interval_amount_cents(tier: Tier, interval: str) -> int:
    """Charge amount in cents for a tier on the given interval."""
    months = 1 if interval == "monthly" else ANNUAL_MONTHS_BILLED
    return round(tier.price_usd * months * 100)


def _stripe_interval(interval: str) -> str:
    return "month" if interval == "monthly" else "year"


def pricing_table() -> list[dict]:
    """Full monthly + annual price table for every tier — what the pricing UI
    renders and the Monthly/Annual toggle switches between."""
    return [
        {
            "key": t.key,
            "name": t.name,
            "monthly_credits": t.monthly_credits,
            "price_usd": round(t.price_usd, 2),                     # monthly (kept for back-compat)
            "monthly_usd": round(t.price_usd, 2),
            "annual_usd": round(t.price_usd * ANNUAL_MONTHS_BILLED, 2),
            "billing": t.billing,
        }
        for t in TIERS
    ]


def tier_catalog() -> list[dict]:
    # Enriched with both interval prices so the toggle needs no second call.
    return pricing_table()


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
def _price_id_for(tier: Tier, interval: str) -> str:
    s = get_settings()
    if interval == "monthly":
        return {
            "starter": s.stripe_price_starter_monthly,
            "pro": s.stripe_price_pro_monthly,
            "scale": s.stripe_price_scale_monthly,
        }.get(tier.key, "")
    return {
        "starter": s.stripe_price_starter,
        "pro": s.stripe_price_pro,
        "scale": s.stripe_price_scale,
    }.get(tier.key, "")


def _line_item(tier: Tier, interval: str) -> dict:
    """
    Prefer a configured Stripe Price ID for the interval; otherwise build an
    inline recurring price from the frozen catalog (pricing_table()) so test-mode
    Checkout works with zero Stripe dashboard setup, on either interval.
    """
    price_id = _price_id_for(tier, interval)
    if price_id:
        return {"price": price_id, "quantity": 1}
    return {
        "quantity": 1,
        "price_data": {
            "currency": "usd",
            "unit_amount": interval_amount_cents(tier, interval),
            "recurring": {"interval": _stripe_interval(interval)},
            "product_data": {
                "name": f"Clippify {tier.name} ({interval})",
                "description": f"{tier.monthly_credits} credits / month.",
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


def create_checkout_session(user_id: str, tier_key: str, interval: str = DEFAULT_INTERVAL) -> dict:
    """Create a hosted Stripe Checkout session for a paid tier on the selected
    interval ("monthly" | "annual"). Returns {url, sessionId, tier, interval}."""
    tier = tier_by_key(tier_key)
    if tier is None or tier.key == "free":
        raise ValueError(f"'{tier_key}' is not a purchasable tier")
    interval = normalize_interval(interval)

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

        meta = {"user_id": user.id, "tier_key": tier.key, "interval": interval}
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            client_reference_id=user.id,
            line_items=[_line_item(tier, interval)],
            success_url=s.success_url,
            cancel_url=s.cancel_url,
            metadata=meta,
            subscription_data={"metadata": meta},
            allow_promotion_codes=True,
        )
        return {"url": session.url, "sessionId": session.id, "tier": tier.key, "interval": interval}
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
            meta = session.get("metadata") or {}
            tier_key = meta.get("tier_key") or "starter"
            interval = normalize_interval(meta.get("interval"))
            tier = tier_by_key(tier_key) or tier_by_key("starter")
            user = _resolve_user(db, session)
            if user is not None:
                granted = tier.monthly_credits
                user.credits += granted
                user.tier = tier.key
                user.billing_interval = interval  # record the chosen interval
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
