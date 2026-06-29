from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from ..billing_core import (
    create_billing_portal,
    create_checkout_session,
    handle_webhook,
    stripe_enabled,
    tier_catalog,
)
from ..deps import current_user
from ..models import User
from ..responses import deferred, err, ok

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/tiers")
def tiers():
    # Real, frozen pricing data — served live so the pricing UI works.
    return ok({"tiers": tier_catalog(), "stripeEnabled": stripe_enabled()})


@router.post("/checkout")
def checkout(tier: str = Form(...), user: User = Depends(current_user)):
    """Start hosted Stripe Checkout for a paid tier. Returns {url} to redirect to."""
    if not stripe_enabled():
        # Graceful degrade: app still boots & pricing still renders without Stripe.
        return deferred("Stripe checkout", "set STRIPE_SECRET_KEY to enable billing")
    try:
        return ok(create_checkout_session(user.id, tier))
    except ValueError as exc:
        return err("bad_tier", str(exc), status_code=400)
    except Exception as exc:  # noqa: BLE001 — surface Stripe/network errors cleanly
        return err("checkout_failed", f"Could not start checkout: {exc}", status_code=502)


@router.post("/portal")
def portal(user: User = Depends(current_user)):
    """Open the Stripe customer Portal (manage / cancel). Returns {url}."""
    if not stripe_enabled():
        return deferred("Stripe billing portal", "set STRIPE_SECRET_KEY to enable billing")
    try:
        return ok(create_billing_portal(user.id))
    except Exception as exc:  # noqa: BLE001
        return err("portal_failed", f"Could not open billing portal: {exc}", status_code=502)


@router.post("/webhook")
async def webhook(request: Request):
    """
    Stripe webhook sink. Reads the RAW body for HMAC-SHA256 verification (never a
    re-serialized model — that would change the bytes and fail the signature),
    then grants credits idempotently on checkout.session.completed.
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        result = handle_webhook(payload, sig)
    except PermissionError:
        return err("bad_signature", "Stripe signature verification failed.", status_code=400)
    except Exception as exc:  # noqa: BLE001
        return err("webhook_error", f"Webhook processing error: {exc}", status_code=400)
    return ok(result)
