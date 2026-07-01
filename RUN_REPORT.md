# RUN REPORT — Ship Clippify

What was built, exactly what was executed, and the status of every §9 acceptance gate.
Honest about what ran on this machine vs. what needs the deploy environment / your keys.

## Environment

- Windows 11, `python` 3.14.6, Node v26.4.0 / npm 11.17.0, Docker CLI 29.5.3, git 2.54.
- **Docker Desktop's Linux engine would not start** on this host: it crashes during boot
  with `starting services: initializing Inference manager … dockerInference: The file
  cannot be accessed by the system` (a Docker Desktop *Model Runner / Inference* bug, not
  a stack problem). `docker compose config` works (no daemon needed); a full `up --build`
  could not be exercised locally.
- `gh` CLI is not installed, so the PR is prepared as a branch + commits (open command
  below).
- Verification that needs a clean dependency set was run in a throwaway venv with the
  pinned `fastapi 0.115.14` + `starlette 0.46.2` (the host's global site-packages had a
  mismatched `starlette 1.x`).

## Gate-by-gate status

### 1. `docker compose config` validates; `up --build` boots; `/health` healthy
- `docker compose -f docker-compose.saas.yml config` → **VALID** (ran, exit 0), including
  after the `image:`/healthcheck edits.
- Full Docker boot: **blocked by the Docker Desktop engine crash above** (environment, not
  code). Mitigation: booted the **real** FastAPI app via `uvicorn saas.main:app` against a
  SQLite DB and confirmed:
  - `GET /health` → `{"ok":true,"data":{"status":"healthy",...}}`
  - `GET /ready`  → `{"ok":true,"data":{"status":"ready","db":"up"}}`
- The CI `compose-and-smoke` job runs the real Docker boot + `/health` on Linux.

### 2. CI gates (FastAPI pin == 0.115, every sub-route present, lint)
Ran locally in the venv:
- FastAPI pin → `FastAPI pin OK: 0.115.14`
- Sub-router survival → `routes OK: 29 mounted; all required present` (includes the new
  `/api/auth/signup`, `/api/billing/checkout`, `/api/billing/webhook`, `/api/billing/portal`,
  plus `/ready`, `/config.js`, `/robots.txt`, `/sitemap.xml`). The CI required-routes list
  was extended to guard these.
- `ruff check saas` → `All checks passed!`

### 3. Marketing → signup grants 30 credits  ✅ (executed)
Against the running app:
```
POST /api/auth/signup (livetest@studio.com) →
  {"ok":true,"data":{"id":"…","email":"livetest@studio.com","credits":30}}
cookie set: mf_session
GET /api/auth/me → {"…","credits":30,"tier":"free"}
```
Plus a headless render of `/` and `/signup?tier=pro` (screenshots) — the landing's
**Start free** and the signup form (which posts to `/api/auth/signup`) render and work; the
signup page correctly shows "continue to **Pro** checkout" from the `?tier` param.

### 4. Core slice (upload → SSE 0→6 → captioned clip downloads)
**Not executed locally.** This is the one journey that needs the full running stack
(PostgreSQL 16 + Redis + ffmpeg + faster-whisper + YuNet), which requires either Docker
(blocked here) or a local Postgres/Redis install. The pipeline code is the **unchanged**
shipped walking skeleton — none of this pass's edits touch `saas/pipeline`, `saas/render`,
`saas/worker`, `saas/sse`, or the SSE `STEP_LABELS`. It runs in the stack and in CI. The
serving/auth/billing layers around it are fully verified above.

### 5. Billing (Stripe test mode) — grant + idempotency + degrade  ✅ (executed, no keys needed)
Because verification is our own HMAC (not the SDK), a valid `checkout.session.completed`
event was **forged and signed** with `STRIPE_WEBHOOK_SECRET` and POSTed to the real
`/api/billing/webhook`. Results (21/21 checks pass — see harness in §"How to reproduce"):
- webhook returns **200**, `status:"granted"`, Pro grant = **500**, user `30 → 530`.
- **idempotency**: replay the same event id → `status:"duplicate"`, credits unchanged (530).
- bad signature → **400**; stale timestamp (replay window) → **400**; no grant on either.
- graceful degrade: with `STRIPE_SECRET_KEY` unset, app boots, `GET /api/billing/tiers`
  renders the frozen catalog with `stripeEnabled:false`, and `POST /api/billing/checkout`
  → `501 deferred` (does not crash).

The full Stripe-CLI round-trip (`stripe listen` + `stripe trigger` + the `4242` test card +
portal) needs **your** `sk_test_…` key and is documented step-by-step in
[STRIPE_LOCAL_TESTING.md](./STRIPE_LOCAL_TESTING.md). The raw-body HMAC + idempotency — the
parts the frozen contract pins — are proven above without any Stripe account.

### 6. No dead links; landing and dashboard visually consistent  ✅
- Every marketing CTA resolves to a real route: Nav/Hero **Start free** → `/signup`,
  **Sign in** → `/dashboard`, paid tiers → smart checkout (logged-in → Stripe; else
  `/signup?tier=KEY`), Free → `/signup`, footer links to `/dashboard` + `/signup`.
- Tokens unified: `web/tokens.css` is canonical; the landing/dashboard link it and the
  React `tailwind.config.js` consumes its `--rgb-*` vars. Rendered checks confirmed
  `--color-accent #FF7A00`, `--rgb-accent 255 122 0`, featured tier = **Pro**.

### 7. SEO + integrations present  ✅
Served and content-type-correct (verified): `/` (full crawlable HTML + OG/Twitter/JSON-LD/
canonical), `/robots.txt` (text/plain), `/sitemap.xml` (application/xml), `/favicon.ico`
(image/svg+xml), `/config.js` (env-driven). Files added: Sentry (backend `main.py` +
frontend `web/runtime.js`), Plausible analytics (DNT-respecting), `.github/dependabot.yml`,
`.github/workflows/codeql.yml`, `.github/workflows/deploy.yml`.

### 8. `git grep -nE "TODO|FIXME|implement later|placeholder"` clean in the live path  ✅
Only hits are HTML `placeholder=""` input hints on the signup form (legitimate UX, not
stub code). No `TODO`/`FIXME`/`implement later` anywhere in the live path.

### 9. No secret committed  ✅
`.env` is gitignored (`git check-ignore .env` → `.env`); only `.env.example` (example
values) is tracked. No `sk_`/`whsec_` real keys in the repo.

### 10. OAuth publishing (private-default) + test suite  ✅ (this pass — executed)
The previously-deferred publishing seam is now **fully implemented**, and a `pytest`
suite was added. Verified in the clean venv:
- New backend: `saas/crypto.py` (Fernet token encryption, key derived from `APP_SECRET`,
  `cryptography` lazy-loaded), `saas/publish_core.py` (YouTube OAuth 2.0 flow, channel-label
  fetch, encrypted-token upsert, auto-refresh, **`video_insert_body()` hard-codes
  `privacyStatus="private"`** — there is no public/unlisted code path), a real
  `saas/routers/publish.py` (`/providers`, `/youtube/connect`, `/youtube/callback`,
  `/youtube/disconnect`, `POST /{clip_id}`), the `OAuthAccount` model, and migration
  `0003_oauth_accounts` (additive, introspective, linear after `0002_billing`).
- Frozen guardrails honored: **OAuth 2.0 only** (no browser automation), uploads **always
  private**, **nothing auto-publishes** (upload happens only on an explicit `POST` from a
  deliberate dashboard click), tokens **encrypted at rest**, Google libs **lazy-loaded only
  when `YOUTUBE_OAUTH_CLIENT_ID/_SECRET` are set** (the app boots and degrades to a clean
  `501 deferred` without them).
- Dashboard: a Publish panel (Connect YouTube + "Publish (private)") wired into the existing
  single delegated `[data-action]` switch and the `{ok,data|error}` `api()` helper.
- **`pytest -q` → 25 passed** in the clean venv. `tests/test_contracts.py` (frozen weights
  0.35/0.20/0.25/0.20, the 7 SSE `STEP_LABELS`, the envelope), `tests/test_billing.py`
  (raw-body HMAC verify, idempotent ledger-keyed grants), `tests/test_publish.py`
  (private-default body, token encrypt/decrypt roundtrip, CSRF `state`, graceful `deferred`).
- `ruff check saas` → **All checks passed!** Sub-router survival now also asserts
  `/api/publish/providers` and `/api/publish/youtube/connect`. CI gained a `pytest` step.

## Deferred seams left in place (out of scope, by design)
- **URL ingest** (`YouTubeSource`/`TwitchSource`) and **long-video map-reduce** — unchanged
  typed interfaces returning a clean `deferred`.

Signup, Stripe billing, and OAuth publishing were deferred seams and are now **fully
implemented**.

## How to reproduce the local verification (no Docker, no Stripe keys)
A clean venv runs the real auth + billing routers against SQLite and forges a signed Stripe
event:
```bash
python -m venv venv && venv/Scripts/python -m pip install \
  "fastapi>=0.115,<0.116" "uvicorn[standard]>=0.30,<0.31" python-multipart \
  "pydantic-settings>=2.4,<3" "SQLAlchemy>=2.0,<2.1" "httpx<0.28" redis ruff
# point DATABASE_URL at sqlite, create_all(), then:
#  - POST /api/auth/signup  -> 201, 30 credits, mf_session
#  - POST /api/billing/webhook with an HMAC-signed checkout.session.completed
#    -> granted 500, replay -> duplicate (no double grant), bad sig -> 400
```
The exact harness used is `verify_app.py` (signs with `STRIPE_WEBHOOK_SECRET`); 21/21
assertions passed.

Run the unit suite (no Docker, no Stripe/Google keys needed):
```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements-dev.txt   # or the subset above + pytest
DATABASE_URL="sqlite:///./test.db" APP_SECRET=test venv/Scripts/python -m pytest -q
# -> 25 passed  (contracts + billing + publishing)
```

## Open the PR (gh not installed here)
```bash
git push -u origin feat/ship-clippify
gh pr create --title "feat: ship Clippify — unify marketing + app, signup, Stripe billing" \
  --body-file RUN_REPORT.md   # or the PR description
```
Do **not** self-merge — open for human review.
