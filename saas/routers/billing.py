from __future__ import annotations

from fastapi import APIRouter, Depends

from ..billing_core import stripe_enabled, tier_catalog
from ..deps import current_user
from ..models import User
from ..responses import deferred, ok

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/tiers")
def tiers():
    # Real, frozen pricing data — served live so the pricing UI works.
    return ok({"tiers": tier_catalog(), "stripeEnabled": stripe_enabled()})


@router.post("/checkout")
def checkout(tier: str, user: User = Depends(current_user)):
    # DEFERRED seam — plugs in at saas/billing_core.py:create_checkout_session().
    return deferred("Stripe checkout", "saas/billing_core.py:create_checkout_session()")
