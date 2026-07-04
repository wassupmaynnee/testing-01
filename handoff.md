# handoff.md — session handoff (2026-07-04)

## 1. Goal
- **In-flight task:** produce a full visual preview of the shipped `v1.0.0` build — Playwright/browser screenshots of every route+state at 375/768/1440px, a 2–4 min walkthrough video of the core journey, seeded realistic demo data (3 personas), `PREVIEW.md` gallery, a running local instance the user can click, and a zip of `preview/`. Rendered UI only; capture failures too (before/after in PREVIEW.md). Stripe test mode; stop at hosted checkout render.
- **Session-wide objective (already done):** consolidate PRs #19→#22 into `main`, tag `v1.0.0`, fix CodeQL findings, pre-stage the deploy kit (PR #23).
- **Frozen contracts (never violate):** FastAPI `>=0.115,<0.116`; port **8011**; `{ok, data|error}` envelope everywhere; SSE stages 0–6 with exact labels ("Queued", "Probing media", "Transcribing (ASR)", "Scoring engagement", "Selecting clip boundaries", "Rendering (cut · reframe · subtitles)", "Complete"); engagement weights 0.35/0.20/0.25/0.20; HMAC-SHA256 raw-body Stripe webhook; tiers Free $0/30 · Starter $14.99/200 · Pro $29.99/500 · Scale $59.99/1200; PBKDF2-240k + `mf_session` httpOnly cookie; OAuth-only private-default publishing; GPL-3.0. Human owns all merges (guardrail re-engaged post-ship).

## 2. Current State
- **Branch:** `main` @ `1d251bb` (= tag `v1.0.0`, force-updated to include security fixes). **Working tree: clean** (this file is the only new artifact).
- **Working:** Docker stack (docker-in-WSL Ubuntu; Docker Desktop was uninstalled) healthy on :8011 — `/health` + `/ready` green (db+redis up), migrations at `0006_referrals (head)`. 65 pytest green, ruff clean, CI green on main except the `deploy` job (expected: no deploy secrets exist). Live QA scripts previously passed 18/18 (release), 13/13 (hardening), 18/18 (UX).
- **Data present but messy:** 15 users, 31 clips (4 featured), 1 referral — residue from QA runs, NOT the clean 3-persona seed the preview task requires.
- **Broken/blocked:** `mcp__claude-in-chrome__list_connected_browsers` → `[]` (no Chrome extension connected) — the intended screenshot path is dead until the user connects a browser OR Playwright is installed. Neither Playwright nor a recording pipeline is set up yet. Nothing captured; `preview/` does not exist; `PREVIEW.md` not started.
- **Untested:** production frontend build via local Caddy (stack serves web/ directly from the image — that IS the production way for this app; note this in PREVIEW.md instead of adding Caddy locally).
- **Storage mode:** local `./data` volume (R2 env vars blank — no credentials exist). State this in the preview report.
- **Stripe:** test key (`sk_test_…`) present in `clippify/.env` (gitignored); checkout creates real `cs_test_` sessions. `STRIPE_WEBHOOK_SECRET` holds the local test-forgery value (see gitignored `.env`; QA scripts read the same value).
- **Open PRs:** #23 `feat/deploy-kit` → main (unmerged, human's). 14 Dependabot PRs open (#8/#9 closed as frozen-pin violations).

## 3. Active Files
- `web/index.html` — served landing (`/`); showcase feed reads `/api/clips/featured` w/ static fallback; zero innerHTML (XSS-hardened).
- `web/dashboard.html` + `web/app.js` — dashboard views/states to capture (skeletons, optimistic card, tooltips, onboarding, referrals panel, library grid); `app.js` holds the SWR cache (`clippify.cache.v1`), tooltip engine, SSE reconnect.
- `web/signup.html` — plain + referral-banner states (`/signup`, `/signup?ref=<code>` via `/r/<code>`).
- `saas/main.py` — route list source of truth for the capture inventory (page routes: `/`, `/signup`, `/dashboard`, `/r/{code}`; no settings page exists — do not invent one).
- `saas/seed.py` — existing idempotent demo-user seeder (demo@clippify.dev / clippify-demo).
- `scripts/generate_clips.py` — generator that produced the 10 reference clips; its outputs live in `data/clips/generated/` with thumbs (already in DB under the demo user).
- `data/clips/generated/*` + `web/showcase/*` — real clip MP4s/thumbnails for populated-library and homepage-showcase shots (gitignored media).
- `docker-compose.saas.yml` — the running stack; rebuild with `up -d --build` after web/ edits (web/ is baked into the image, NOT bind-mounted).
- `deploy/` + `DEPLOY_CHECKLIST.md`, `SHIP_LOG.md`, `OBSERVABILITY.md`, `QA_FINDINGS.md` — context docs from prior phases.
- Scratchpad QA scripts (outside repo, still useful): `...Temp/claude/.../scratchpad/qa_release.sh`, `qa_ux.sh`, `qa_harden.sh`, `qa_library.sh`.

## 4. Changes Made
*(this session = the preview task; nothing repo-visible yet)*
1. `git checkout main` — moved off `feat/deploy-kit` to the v1.0.0 state for capture. No file edits.
2. Verified stack health + counted seed data (see §2) via `docker exec` python one-liner.
3. Loaded claude-in-chrome MCP tools via ToolSearch; probed `list_connected_browsers` → `[]` (blocker, see §5).
4. Created this `handoff.md` (only new file).
*(Earlier same-day context, already committed/pushed on `main`: PRs #19–#22 merged in dependency order; CodeQL fixes `6f24f75`+`1d251bb`; `SHIP_LOG.md` `d95ae93`; tag `v1.0.0` force-moved to `1d251bb`. `deploy/` kit on PR #23. Docker Desktop uninstalled → C: free 0.49→36 GB.)*

## 5. Failed Attempts
- **Chrome-extension capture:** `list_connected_browsers` returned `[]` — no browser connected to the account; cannot screenshot via claude-in-chrome until the user opens Chrome with the extension. Don't retry blindly; check again only after user action.
- **(Recurring, avoid)** inline `wsl bash -lc '...'` with nested quotes/vars silently mangles args (Git Bash path-rewriting + quoting): write a `.sh` to scratchpad and run `wsl bash -lc 'bash "/mnt/c/.../script.sh"'` instead. `timeout N wsl bash file.sh` without `-lc` ALSO fails (Git Bash rewrites `/mnt/c` → `C:/Program Files/Git/mnt/c`).
- **(Recurring, avoid)** editing `web/` then testing against :8011 without `docker compose up -d --build` — the container serves the BAKED image copy; only `./data` is bind-mounted.
- **(Historical, relevant to video work)** C: drive filled to 0 bytes mid-render killing jobs with 0-byte files (ENOSPC); 36 GB now free but video recording + screenshots are disk-hungry — check `df` before large captures.
- **(Historical)** `prometheus-fastapi-instrumentator` 8.x pulled starlette 1.x breaking FastAPI 0.115 — pinned `<7`; don't "upgrade" it while installing Playwright deps.
- **(Historical)** curl cookie jars: Python `MozillaCookieJar` skips `#HttpOnly_` lines → 401s; use curl end-to-end or strip the prefix.

## 6. Next Steps
1. **Unblock capture (highest priority; pick one):** (a) ask the user to open Chrome with the Claude extension connected → use claude-in-chrome (`resize_window` for 375/768/1440, `computer screenshot save_to_disk:true`); or (b) `cd site && npm i -D playwright && npx playwright install chromium` and drive `http://localhost:8011` headless — Playwright also gives `recordVideo` for the walkthrough (compose 1080p via ffmpeg after). (b) is fully autonomous; prefer it if the extension stays disconnected.
2. **Clean-seed the 3 personas** (script via `docker exec`, direct DB like `scripts/generate_clips.py::register`): `maya@freshstudio.dev` (fresh Free, empty states), `jordan@podcraft.studio` (Pro, `tier="pro"`, `billing_interval="monthly"`, adopt the 10 existing generated clips + credit ledger entries + a `stripe_customer_id`, keep 4 featured), `sam@creatorlab.dev` (referrer with 1 pending + 1 credited referral, +100 ledger). Wipe the QA-noise users (`qa*/rel*/whdemo*/checkout*@clippify.dev`) first — DB only, don't touch `data/` media.
3. **Enumerate routes/states** from `saas/main.py` + dashboard views (no settings page exists — the prompt's list overshoots; document that). Capture matrix: ~10 pages/states × 3 breakpoints into `preview/<route>_<state>_<bp>.png`; states needing setup: skeleton (Playwright `route()` throttle), optimistic card mid-SSE (submit `data/uploads/sources/short_take_b.mp4`, screenshot during stage 2–5), error toast (submit bad URL), tooltip (hover + focus), mobile tooltip (tap).
4. **Walkthrough video:** Playwright context `recordVideo` at 1920×1080 through the journey (homepage → `/r/<sam's code>` signup → upload → stages → play → download → billing checkout render → referrals → logout/login cache restore); save `preview/walkthrough_v1.0.0.mp4`.
5. **Write `PREVIEW.md`** (gallery + captions + known-cosmetic-issues list — capture-then-fix pairs if anything breaks) and **zip** `preview/` (PowerShell `Compress-Archive`).
6. **Deliver:** local URL `http://localhost:8011` (keep WSL keepalive alive: `wsl bash -lc "sleep 100000"` background); optional tunnel only WITH basic auth (e.g. `caddy run` + `basic_auth` or cloudflared + access policy) — never unauthenticated.
7. After preview sign-off, the only remaining arc item is the user's provisioning per `DEPLOY_CHECKLIST.md` → then `deploy/deploy.sh v1.0.0`.
