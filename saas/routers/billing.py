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
from ..observability import log_event
from ..responses import deferred, err, ok

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/tiers")
def tiers():
    # Real, frozen pricing data — served live so the pricing UI works.
    return ok({"tiers": tier_catalog(), "stripeEnabled": stripe_enabled()})


@router.post("/checkout")
def checkout(
    tier: str = Form(...),
    interval: str = Form("annual"),
    user: User = Depends(current_user),
):
    """Start hosted Stripe Checkout for a paid tier on the selected interval
    ("monthly" | "annual"). Returns {url} to redirect to."""
    if not stripe_enabled():
        # Graceful degrade: app still boots & pricing still renders without Stripe.
        return deferred("Stripe checkout", "set STRIPE_SECRET_KEY to enable billing")
    try:
        return ok(create_checkout_session(user.id, tier, interval))
    except ValueError:
        return err("bad_tier", "That plan is not available.", status_code=400)
    except Exception as exc:  # noqa: BLE001 — surface Stripe/network errors cleanly
        log_event("checkout failed", level=40, error=str(exc))
        return err("checkout_failed", "Could not start checkout. Please try again.", status_code=502)


@router.post("/portal")
def portal(user: User = Depends(current_user)):
    """Open the Stripe customer Portal (manage / cancel). Returns {url}."""
    if not stripe_enabled():
        return deferred("Stripe billing portal", "set STRIPE_SECRET_KEY to enable billing")
    try:
        return ok(create_billing_portal(user.id))
    except Exception as exc:  # noqa: BLE001
        log_event("portal failed", level=40, error=str(exc))
        return err("portal_failed", "Could not open the billing portal. Please try again.", status_code=502)


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
        log_event("webhook error", level=40, error=str(exc))
        return err("webhook_error", "Webhook could not be processed.", status_code=400)
    return ok(result)
