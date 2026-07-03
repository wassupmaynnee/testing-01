# QA Findings — UI polish pass (`feat/ui-polish-pass`)

Functional sweep run against the live Docker stack on :8011 (39/40 scripted checks
passed; the one "failure" was a test artifact — unauthenticated access to a clip
returns 401 by design, cross-user access returns 404 via `_owned_clip`).

Repro for all: `scratchpad/qa_sweep.sh` (signup → auth edge cases → 6 checkout
combos → URL validation → upload → SSE → completion → credits → downloads → publish
deferral).

## Findings

| # | Severity | Finding | Repro | Status |
|---|---|---|---|---|
| 1 | High | **Served landing has no monthly/annual toggle.** The interval toggle shipped in `site/src/components/Pricing.tsx`, but `/` serves `web/index.html`, which shows only annual copy and its `startCheckout()` never sends `interval` — a buyer cannot choose monthly from the real landing page. | Open `/`, see pricing: "billed annually" only; click a paid CTA while logged in → checkout defaults to annual. | **Fixed** — toggle + interval param added to `web/index.html`. |
| 2 | Medium | **Free CTA doesn't say "No credit card — 30 free credits"** anywhere the Free tier appears (landing pricing, nav CTA, signup page). | Open `/#pricing`. | **Fixed** — copy added at every Free CTA. |
| 3 | Medium | **Credit cost not shown before processing.** Upload/URL panels say "one credit per clip" in prose but show no explicit pre-run cost line tied to the action. | Open `/dashboard`, select a file — button says "Generate clip" with no cost. | **Fixed** — explicit cost line on both actions; balance visibly refreshes after run. |
| 4 | Medium | **No styled 404 page.** Unknown paths return the JSON envelope (`{"ok":false,...}` 404). Correct for `/api/*`; for browser paths the spec expects a styled 404. | `GET /nope` → JSON. | **Blocked (backend)** — needs an HTML fallback handler for non-`/api` paths in `saas/main.py`; out of scope per "no backend changes." Documented in PR body. |
| 5 | Low | **Landing `<html>` missing `lang` check / skip link / focus-visible audit** and stepper lacked `aria-live` (async status not announced). | Inspect. | **Fixed** — a11y pass (aria-live on stepper + toast, focus-visible styles, landmarks, reduced-motion). |
| 6 | Low | **`site/` React marketing app is built but not served** — drift risk: its pricing already has the toggle while the live landing didn't. | `saas/main.py:78` serves `web/index.html`. | **Documented** — copy kept in sync this pass; consolidation proposal in PR body. |
| 7 | Info | Publish/analytics correctly return 501 `deferred` (OAuth unconfigured); Stripe checkout verified for all 6 paid tier×interval combos in test mode; webhook grant+idempotency previously verified (PR #18). | qa_sweep.sh | No action. |
