# Testing Stripe billing locally

How to exercise the Clippify billing path (Checkout → webhook → credit grant) on
your machine in **test mode**, so the billing acceptance gate passes for real
instead of being stubbed.

> Frozen contract: the Stripe SDK is **lazy-loaded only when `STRIPE_SECRET_KEY`
> is set**, and webhook signatures are verified by the **custom HMAC-SHA256**
> check in `saas/billing_core.py` (`verify_webhook_signature()`) — not the Stripe
> SDK. The webhook route reads the **raw request body** and the grant is keyed on
> the Stripe **event id** so a re-delivered event never double-grants.

## Prerequisites

- The stack runs locally: `docker compose -f docker-compose.saas.yml up --build`,
  API reachable at `http://localhost:8011`.
- The **Stripe CLI** installed and authenticated:
  - Windows: `scoop install stripe` (or the release binary); macOS/WSL:
    `brew install stripe/stripe-cli/stripe`.
  - `stripe login` once to link it to your account.

## 1. Get your test secret key

Stripe Dashboard → switch to **Test mode** → **Developers → API keys** → copy the
**Secret key** (`sk_test_…`). Hosted Checkout is created server-side with this
key, so no publishable key is needed.

## 2. Start the local webhook listener

Point it at the implemented route, `/api/billing/webhook`. Leave it running:

```bash
stripe listen --forward-to localhost:8011/api/billing/webhook \
  --events checkout.session.completed
```

On start it prints:

```
Ready! Your webhook signing secret is whsec_xxxxxxxxxxxxxxxxxxxxxxxx
```

**Copy that `whsec_…`.** It is the CLI's *own* signing secret for local
forwarding — **different** from any secret in the Dashboard webhook settings.

## 3. Set the two env vars

In `.env` (never commit it — only `.env.example` is tracked):

```dotenv
STRIPE_SECRET_KEY=sk_test_...      # from step 1
STRIPE_WEBHOOK_SECRET=whsec_...    # the CLI secret from step 2, NOT the dashboard one
```

Setting `STRIPE_SECRET_KEY` flips `stripe_enabled()` to true and lazy-loads the
SDK, so checkout + portal go live.

## 4. Reload the API so it reads the new .env

```bash
docker compose -f docker-compose.saas.yml up -d --build
```

## 5. Test — synthetic, then real

**Synthetic** (fastest loop): send a real test event straight to the handler.

```bash
stripe trigger checkout.session.completed
```

Watch the `stripe listen` terminal show a **`200`**. A CLI-triggered event carries
no `metadata.user_id`, so outside production the handler grants the (default
`starter`) credits to the **seeded demo user** — you'll see the credit appear in
its ledger. (In production a metadata-less event grants nothing.)

**Real round-trip:** from a paid-tier CTA on the marketing page (logged in),
complete Stripe Checkout with the test card:

| Field | Value |
|---|---|
| Card number | `4242 4242 4242 4242` |
| Expiry | any future date |
| CVC | any 3 digits |
| ZIP | any |

A real checkout carries our `metadata.user_id` + `tier_key`, so the listener
returns `200` and **that** user's credits increment by the tier's monthly amount
(Pro = 500). The **billing portal** opens from the dashboard's *Billing* button
(`POST /api/billing/portal`).

**Idempotency check:** re-deliver the exact same event:

```bash
stripe events resend evt_...    # same event id
```

The listener still returns `200`, but the handler records `"status":"duplicate"`
and **credits do not change** — the event id is unique in the `stripe_events`
table.

## 6. Confirm graceful degrade

Comment out `STRIPE_SECRET_KEY` in `.env`, reload, and confirm the app still
boots and the pricing UI still renders — `POST /api/billing/checkout` and
`/portal` return a clean `deferred` (501) instead of crashing.

---

## Two gotchas that silently break signature verification

1. **Verify against the raw body.** `verify_webhook_signature()` recomputes
   HMAC-SHA256 over `f"{timestamp}.".encode() + payload`. The route reads
   `await request.body()` (raw bytes) and passes **those** — never a parsed model
   or re-serialized JSON. Reserializing changes the bytes and the
   `hmac.compare_digest` fails.
2. **Be fast and idempotent.** Stripe doesn't guarantee order or single delivery.
   The handler returns `2xx` quickly and keys the grant on the **event id** in the
   `stripe_events` ledger, so a duplicate can't double-grant.

## Useful extras

- `stripe trigger checkout.session.completed` — re-fire the success event.
- `stripe events resend evt_...` — replay one exact event by id (idempotency test).
- The CLI signing secret is stable across `stripe listen` restarts, so step 3 is a
  one-time edit per machine.

## Verifying without the Stripe CLI

Because verification is our own HMAC (not the SDK), you can forge a valid event
locally and prove the full grant + idempotency path with no Stripe account — see
the harness described in `RUN_REPORT.md` (`scripts`-style script that signs a
`checkout.session.completed` payload with `STRIPE_WEBHOOK_SECRET` and POSTs it).
