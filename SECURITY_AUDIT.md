# SECURITY_AUDIT.md — Clippify pre-launch hardening pass (2026-07-04)

Scope: full repo + running dev stack (docker-in-WSL, `:8011`). Branch
`feat/security-hardening` off `main`@`v1.0.0`. All controls below are
implemented and test-proven (80 pytest green, incl. 15 new security tests) —
no stubs. Frozen contracts untouched.

---

## A. Fixed in this pass (Phases 1–4)

| # | Control | Where | Proof |
|---|---|---|---|
| 1 | **Global rate limiting on every endpoint** — Redis fixed-window, 300/min/IP, pure-ASGI middleware; exempt: `/health` `/ready` `/metrics` `/static/*` (infra probes/assets); fail-open on Redis outage (logged) | `saas/ratelimit.py` (`GlobalRateLimitMiddleware`), wired in `saas/main.py` | `tests/test_ratelimit.py::test_global_limit_enforced`, `::test_health_exempt` |
| 2 | **Dual-key auth limiter** — login: **5 attempts / 15 min per IP AND per account** (salted-hash account key in Redis; both enforced independently); 429 + `Retry-After` + envelope; **no account-existence leak** (identical 429 either way) | `saas/ratelimit.py` (`auth_rate_limit`), `saas/routers/auth.py` login | `test_sixth_login_attempt_rejected_by_ip`, `test_account_key_enforced_across_ips`, `test_429_does_not_leak_account_existence`, `test_window_resets` |
| 3 | **422s now in the frozen envelope, zero input echo** — FastAPI's default `RequestValidationError` returned `{"detail":[...]}` with the submitted `input` values reflected back. Custom handler returns `{ok:false,error:{code:"validation_error",fields:[{field,issue}]}}` — field names only | `saas/main.py` (`validation_envelope`) | `test_validation_error_enveloped_no_echo`, `test_malformed_body_enveloped` |
| 4 | **Password length cap (8–256)** — unbounded password reached PBKDF2-240k (hash-DoS vector) | `saas/routers/auth.py` (`_MAX_PASSWORD`) | `test_oversized_password_rejected` |
| 5 | **URL input cap (2048)** on job submission | `saas/routers/jobs.py` | `test_oversized_url_rejected` |
| 6 | **Secret scanner + CI gate** — pattern (Stripe/AWS/GitHub/JWT/conn-string/private-key) + entropy scan of all tracked files; `--history` mode walks every commit; masked output only; wired as a blocking CI step | `scripts/secret_scan.py`, `.github/workflows/ci.yml` (security-audit job) | gate run: tracked files **clean**, exit 0 |
| 7 | **Local-test webhook value scrubbed from `handoff.md`** (was written into a tracked file last session) | `handoff.md` §2 | scanner clean; value now referenced by location only |
| 8 | **pytest CVE-2025-71176** — dev-only dep bumped 8.4.2 → 9.1.1 (pin `>=9.0.3,<10`); full suite re-verified | `requirements-dev.txt` | 80 passed on 9.1.1; pip-audit clean for pytest |

Carried over from the v1.0.0 hardening (verified still in force this pass):
security headers (CSP/XFO/XCTO/Referrer/Permissions[+HSTS prod]), request-id
tracing, JSON logs (internal user-id only), Sentry PII scrubber, body-size
middleware (2 MB non-multipart) + 500 MB streaming upload cap + UUID filenames,
`/docs|/redoc|/openapi.json` off in production, cookie `Secure` in prod
(HttpOnly+SameSite always), HMAC-SHA256 raw-body webhook w/ event-id idempotency,
object-level authz on clips/jobs/referrals (cross-user = 404, test-proven),
mass-assignment blocked, arg-list-only subprocess calls, ORM-parameterized SQL,
XSS eliminated (zero `innerHTML` on user data paths; `tier` param allowlisted).

## B. Phase-2 findings table (scan run 2026-07-04, `--history` included)

| Location | Type | Verdict |
|---|---|---|
| `.env` (gitignored, untracked) | Stripe **test** key + local-forgery webhook secret | In the right place. Never in git history (verified incl. `sk_test_` pattern). **Rotate/replace before production** (test key was also shared in chat). |
| `handoff.md` (tracked; local commit `05469a6`, **never pushed**) | local-forgery `whsec_…` value | **Fixed** — scrubbed on this branch. Value is a local dummy, never left this machine; no rotation impact on Stripe (not a Stripe-issued secret). |
| `tests/*` `whsec_test_secret` | documented test dummy | Accepted (allowlisted); not a credential. |
| `docker-compose.saas.yml` conn string | `${POSTGRES_PASSWORD:-clippify}` interpolation | False positive — parameterized with dev-only fallback; prod overrides via env. |
| git history (all branches) | — | **Clean** — no live keys, tokens, or private keys ever committed. |

**Secrets requiring rotation (owner action):**
1. `STRIPE_SECRET_KEY` (`sk_test_…` in `.env`) — was pasted in chat; regenerate in the Stripe dashboard before production (and never reuse it as a live pattern).
2. `APP_SECRET` — the generated value was surfaced in chat during deploy-kit handoff; generate a fresh one for production (`python -c "import secrets;print(secrets.token_urlsafe(48))"`).
3. `whsec_localtest_forgedemo` — replace with the real Stripe endpoint secret at deploy (already the documented plan).

## C. Phase-3 environment posture

- All secrets/config flow through pydantic `Settings` (`saas/config.py`) from env/`.env`. No hardcoded credentials in code.
- `.env` gitignored (verified) and **excluded from the Docker image** via `.dockerignore` (fixed in v1.0.0; re-verified in-container).
- `.env.example` (dev) + `deploy/.env.production.template` (prod) contain placeholders only.
- **Frontend exposure: none.** `site/src` uses no `VITE_`/`import.meta.env`/`process.env` at all; built bundles and `web/*.js` contain no key patterns; `/config.js` exposes only public values (Sentry DSN, Plausible domain, app env).
- Forward protection: `scripts/secret_scan.py` blocks CI on any committed secret.

## D. Remaining risks (ranked)

| Sev | Risk | Remediation |
|---|---|---|
| **High** | `starlette 0.46.2` — 8 advisories (multipart/DoS class: PYSEC-2026-161/248/249, CVE-2025-54121/62727, CVE-2026-48817/48818). **Unfixable under the frozen FastAPI `>=0.115,<0.116` pin** (requires starlette ≥0.47). | Mitigated by: global+auth rate limits, 2 MB body cap + Caddy 550 MB edge cap, upload streaming cap. **Remediate by unfreezing the FastAPI pin post-launch** (bump FastAPI → starlette ≥1.3.1), re-run the route-survival CI assert. CI pip-audit ignores these IDs with this documented justification. |
| Med | `X-Forwarded-For` trusted unconditionally for rate-limit keys — spoofable if the app port is ever exposed directly (bypasses per-IP limits; per-account key still holds) | Bind 8011 to localhost on the droplet (Caddy fronts it — already the deploy-kit design); optionally validate that the peer is loopback before honoring XFF. |
| Med | PBKDF2-HMAC-SHA256 @ 240k (frozen contract) instead of argon2/bcrypt | OWASP-acceptable (≥210k). If the contract is ever unfrozen, migrate to argon2id with rehash-on-login. |
| Low | Stateless `mf_session` tokens can't be revoked server-side before 7-day expiry (logout clears the cookie only) | Acceptable at this scale; add a Redis session-denylist keyed by token hash if revocation becomes a requirement. |
| Low | Global limiter is fixed-window (burst at window edges up to 2× limit) | Acceptable; swap to sliding-window (Redis ZSET) if abuse observed. |
| Low | `whsec_test_secret` literal in test files | Dummy value, allowlisted; no action. |

## E. Checks performed (nothing silently skipped)

- Auth/session: PBKDF2 + signed cookie flags ✔ (tests) · authz on every owned-resource route ✔ (tests) · CORS: no `CORSMiddleware` = same-origin only, nothing to lock down ✔ · security headers ✔ (tests + live) · webhook HMAC + idempotency ✔ (tests) · dependency audits: pip-audit (above) + `npm audit` → **0 vulnerabilities** ✔ · TLS/cookies: `Secure` gated on `APP_ENV=production`; TLS terminates at Caddy/Cloudflare per deploy kit ✔ · error handling: generic client messages, details to logs w/ request-id ✔ (CodeQL stack-trace alerts closed in v1.0.0) · logging: JSON, internal user-id only, Sentry scrubber test-proven ✔.
- **Not performable here:** live TLS/HSTS verification on a public domain (no production deployment exists yet) — covered by `deploy/smoke.sh` at deploy time. Gitleaks/trufflehog binaries unavailable on this host; `scripts/secret_scan.py` (pattern+entropy+history) served as the equivalent, and is now the permanent CI gate.

## F. Preview-workstream impact note

Changes that the parked preview/capture task should know about: login now rate-limits at 5/15 min (dual-key) — repeated manual login attempts during capture can trip it (flush the `clippify:rl:*` Redis keys if needed); 422 responses changed shape (envelope, field list). No routes, page markup, or seed data were altered.
