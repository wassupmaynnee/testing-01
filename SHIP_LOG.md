# SHIP LOG — Clippify v1.0.0

Consolidation of all feature work into `main`, tagged `v1.0.0`. Times are the run's sequence.

## Phase 1 — Merge (dependency order, linear stack)

| Step | Action | Result |
|---|---|---|
| Inventory | 4 open feature PRs, linearly stacked: #19 ui-polish → #20 clip-generation → #21 ux-upgrade → #22 hardening (tip). Tip CI fully green. | plan printed |
| Pre-merge fixes | CodeQL flagged 5 real alerts (1 HIGH XSS, 1 HIGH ReDoS, 3 MED stack-trace-exposure). Fixed all at the tip + added input-validation/OWASP hardening before merging. | 65 tests green |
| Merge #19 | `feat/ui-polish-pass` → main (merge commit `695c697`) | merged |
| Merge #20 | `feat/clip-generation` → main (`afebfd6`) | merged |
| Merge #21 | `feat/ux-upgrade` → main (`e352ca4`) | merged |
| Merge #22 | `feat/hardening` → main (`0a0f0bf`) | merged |
| Integration verify | `ruff` clean, **pytest 65 passed**, migration chain 0001→0006 linear | green |
| Tag | `v1.0.0` pushed | done |

*Note:* the stack is **linear** (each PR based on the previous), so bottom-up merges reproduce the tip's tree. CodeQL findings introduced in lower branches were fixed at the tip before any merge, so the final `main` state carries the fixes. Any transient intermediate state was never a release candidate — v1.0.0 = post-#22 `main`.

## Phase 2 — Blockers closed
- **Signup:** live at `/signup`, linked from every marketing CTA; `/r/<code>` pre-applies referral codes; email validated + rate-limited (5/min).
- **Stripe checkout:** live via `sk_test`; all 3 paid tiers × both intervals create real `checkout.stripe.com` sessions (verified in prior PRs + release smoke); HMAC webhook idempotent; referral grant fires on first paid sub.
- **Dead CTAs:** audit of `web/*.html` → **0** dead hrefs.

## Phase 3 — Input validation & sanitization
- Backend enforcement: email length-cap + regex, weak-password reject, mass-assignment blocked (injected `credits/tier/is_admin` ignored — test-proven), pagination clamped server-side, upload allowlist + streaming size cap (500 MB) + server-generated UUID filenames (no traversal), YouTube URL host-allowlisted (SSRF-limited), all `subprocess` arg-lists (no shell).
- Output: reflected-XSS via `tier` param fixed (allowlist + DOM nodes); Sentry scrubs PII; generic client errors.

## Phase 4 — OWASP API Top 10
See the PR #22 / this-run findings table. API1 (object-level authz tests), API2 (PBKDF2-240k [frozen], rate limits, secure cookie), API3 (whitelist responses + mass-assignment block), API4 (rate + size + pagination caps), API5/API8 (docs disabled in prod), API7 (URL allowlist), API10 (HMAC webhook) — all verified or fixed.

## Phase 5 — Integration QA
- Full suite: **65 passed**, ruff clean.
- Live release smoke on consolidated `main`: **18/18** (journey + CodeQL-fix-live + security posture).

## Phase 6 — Production deploy: BLOCKED (not attempted)
See the final report / this run's Phase-6 section. No production infrastructure or secrets exist (0 repo secrets, empty `production` environment; no Droplet/SSH/live-Stripe/R2/Cloudflare). Deploy requires the human to provision these. **Nothing was deployed. No production data touched.**

## Rollback procedure (for when a deploy does happen)
1. **App:** redeploy the previous release tag — `docker compose pull && up -d --no-build` pointed at the prior image tag (GHCR keeps `type=sha` tags per build).
2. **DB:** restore from the pre-migration dump taken in pre-flight (`pg_dump` before `alembic upgrade head`); migrations 0005/0006 are additive but `downgrade` is defined on each if a schema rollback is needed.
3. **DNS/Cloudflare:** unchanged by app deploys; no rollback needed unless DNS was edited (it wasn't).
