# Clippify — Production Provisioning Checklist (your manual steps)

Everything the agent can pre-build is committed under `deploy/`. This is the
ordered list of the account/credential steps only you can do. Do them top to
bottom; each says the exact console location and the exact value to record into
`/opt/clippify/.env` (built from `deploy/.env.production.template`).

**Cost flags (approve before starting):** the **Droplet (~$48/mo)** is the only
guaranteed charge. **Cloudflare R2** is free to 10 GB storage + 1M ops/mo, then
~$0.015/GB — you'll exceed the free tier only with real clip volume. **Stripe**
= per-transaction fees, no fixed cost. **Sentry** free tier (or self-host
GlitchTip = free). Cloudflare DNS = free. Domain registration (if you don't own
one) = ~$10/yr.

---

## 0. Domain
You need a domain (or subdomain) you control the DNS for. Record it:
`CLIPPIFY_DOMAIN = ______________________`  (e.g. `clippify.app` or `app.yourdomain.com`)

## 1. DigitalOcean — Droplet
- **Console:** cloud.digitalocean.com → Create → Droplets.
- **Recommended spec (justified):** **Regular / Premium Intel, 4 vCPU / 8 GB RAM / 160 GB SSD (~$48/mo)**, **Ubuntu 24.04 LTS**, region nearest your audience (e.g. NYC3/SFO3).
  - *Why:* Whisper transcription + ffmpeg H.264 encoding are CPU-bound; 4 vCPU keeps a clip render to ~1–2 min. 8 GB holds the Whisper model + OpenCV + Postgres + Redis comfortably. 2 vCPU/4 GB works for light use but renders queue up; 8 vCPU only helps with heavy concurrency.
  - *Open decision — DB:* **self-hosted Postgres in the compose stack (default, $0)** vs **DO Managed Postgres (+$15/mo, automated backups/failover)**. Default self-hosted; switch to managed later if uptime/durability matters (point `DATABASE_URL` at it, drop the `db` service).
- **SSH:** add your SSH public key during creation (not password auth).
- **Deploy user (not root):** after first login as root:
  ```
  adduser clippify && usermod -aG sudo clippify
  rsync --archive --chown=clippify:clippify ~/.ssh /home/clippify
  ```
  Hand the agent (or use yourself): SSH access as **`clippify`**, plus the **droplet's public IP**: `______________________`

## 2. Cloudflare — DNS + R2
- **DNS (console:** dash.cloudflare.com → your domain → DNS → Records):
  - Add **A record**: name `@` (or your subdomain) → **droplet IP** (from §1), **Proxy status: Proxied (orange cloud)**.
  - **SSL/TLS → Overview → set mode to "Full (strict)"**.
- **R2 (console:** dash.cloudflare.com → R2):
  - Create a bucket, e.g. **`clippify-clips`** → record `R2_BUCKET`.
  - Record your **Account ID** (R2 overview page) → `R2_ACCOUNT_ID`.
  - **Manage R2 API Tokens → Create API Token**, scope **Object Read & Write**, restricted to that bucket → record the **Access Key ID** (`R2_ACCESS_KEY_ID`) and **Secret Access Key** (`R2_SECRET_ACCESS_KEY`).
  - **Bucket → Settings → CORS policy**, paste (replace domain):
    ```json
    [{"AllowedOrigins":["https://<CLIPPIFY_DOMAIN>"],
      "AllowedMethods":["GET"],
      "AllowedHeaders":["*"],
      "MaxAgeSeconds":3600}]
    ```
  - Leave the bucket **private** (the app serves clips via presigned URLs; only `featured` clips are public, streamed through the API).

## 3. Stripe — live checkout + webhook
- **Console:** dashboard.stripe.com. **Toggle OFF "Test mode"** (top-right) to work in **live**.
- **Developers → API keys** → reveal + copy the **Secret key** (`sk_live_…`) → `STRIPE_SECRET_KEY`.
- **Developers → Webhooks → Add endpoint:**
  - **Endpoint URL:** `https://<CLIPPIFY_DOMAIN>/api/billing/webhook`
  - **Events to send:** `checkout.session.completed` (only this is needed).
  - After creating, click the endpoint → **Signing secret** → reveal (`whsec_…`) → `STRIPE_WEBHOOK_SECRET`.
- *(Optional, cleaner reporting)* create live recurring **Prices** for each tier/interval and paste their IDs into the `STRIPE_PRICE_*` vars; otherwise the app builds inline prices from the frozen catalog (works, but creates ad-hoc prices).

## 4. Error tracker — DSN
- **Sentry (sentry.io, free tier):** create a project (platform: FastAPI) → **Settings → Client Keys (DSN)** → copy the DSN → `SENTRY_DSN`.
- *(or self-host GlitchTip — same DSN format, $0; point DSN at your instance.)*
- Leave `SENTRY_DSN` blank to ship without error tracking (it's a no-op).

## 5. Fill `/opt/clippify/.env`
On the droplet: `cp deploy/.env.production.template /opt/clippify/.env`, then set every `<FILL_ME>`:
| Var | From |
|---|---|
| `APP_BASE_URL`, `YOUTUBE_OAUTH_REDIRECT_URI` | §0 domain |
| `APP_SECRET` | **the agent generated this — paste the value it handed you** |
| `DATABASE_URL`, `POSTGRES_PASSWORD` | a strong password you invent (same in both) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | §3 |
| `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | §2 |
| `SENTRY_DSN` | §4 (or blank) |
Leave YouTube/Plausible blank unless you're enabling them.

## 6. Deploy + smoke (one run each)
As `clippify` on the droplet:
```bash
export CLIPPIFY_DOMAIN=<your-domain>
cd /opt/clippify   # or run deploy.sh which clones it there
git clone https://github.com/wassupmaynnee/testing-01.git . 2>/dev/null || git pull
bash deploy/deploy.sh v1.0.0        # installs Docker+Caddy, brings the stack up, migrates, health-gates
bash deploy/smoke.sh https://<your-domain>   # live checks; stops at Stripe checkout render (no charge)
```
Then, once, in the browser: sign up → upload a short video → watch it generate → play → download; and in the Stripe dashboard, **Send test webhook** to the endpoint and confirm **200**.

**Rollback if needed:** `bash deploy/rollback.sh <previous-tag>` (restores the pre-migration DB dump on prompt).
