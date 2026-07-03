#!/usr/bin/env bash
#
# Clippify production deploy — idempotent server bootstrap + release.
# Run as the `clippify` deploy user (must be in the `docker` group; needs sudo
# for the one-time package install). Safe to re-run: each step checks state.
#
#   ./deploy.sh [TAG]        TAG defaults to v1.0.0
#
# What it does: install packages (Docker, Caddy) -> clone/pull the tag ->
# pre-migration DB backup (if a DB already exists) -> bring the stack up (the
# api container runs migrations via its entrypoint) -> install/enable the
# systemd unit + Caddyfile -> health-check /ready before declaring success.
set -euo pipefail

TAG="${1:-v1.0.0}"
APP_DIR="/opt/clippify"
REPO="https://github.com/wassupmaynnee/testing-01.git"
DOMAIN="${CLIPPIFY_DOMAIN:?set CLIPPIFY_DOMAIN, e.g. export CLIPPIFY_DOMAIN=clippify.example.com}"

log() { echo -e "\n\033[1;33m[deploy]\033[0m $*"; }

# ── 1. Packages (Docker + Caddy). Idempotent. ───────────────────────────────
if ! command -v docker >/dev/null; then
  log "installing Docker"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  log "added $USER to docker group — you may need to re-login before continuing"
fi
if ! command -v caddy >/dev/null; then
  log "installing Caddy"
  sudo apt-get update
  sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update && sudo apt-get install -y caddy
fi

# ── 2. Clone / update to the release tag ────────────────────────────────────
if [ ! -d "$APP_DIR/.git" ]; then
  log "cloning $REPO -> $APP_DIR"
  sudo mkdir -p "$APP_DIR" && sudo chown "$USER":"$USER" "$APP_DIR"
  git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"
git fetch --tags --force
git checkout -q "$TAG"
log "checked out $TAG ($(git rev-parse --short HEAD))"

# ── 3. Env file must exist (never committed) ────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
  log "ERROR: $APP_DIR/.env missing. Copy deploy/.env.production.template to"
  log "       $APP_DIR/.env and fill it in (see DEPLOY_CHECKLIST.md). Aborting."
  exit 1
fi

# ── 4. Pre-migration DB backup (only if a DB container already has data) ─────
if docker ps --format '{{.Names}}' | grep -q clippify-saas-db-1; then
  BK="$APP_DIR/backups"; mkdir -p "$BK"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  log "backing up Postgres before migrating -> $BK/pre-migrate-$STAMP.sql.gz"
  docker exec clippify-saas-db-1 pg_dump -U clippify clippify | gzip > "$BK/pre-migrate-$STAMP.sql.gz"
  echo "$STAMP" > "$BK/.last-backup"
fi

# ── 5. Bring the stack up (api entrypoint runs alembic upgrade head) ─────────
log "docker compose up --build (migrations run in the api entrypoint)"
docker compose -f docker-compose.saas.yml up -d --build --remove-orphans

# ── 6. Systemd unit (boot persistence) ──────────────────────────────────────
if [ ! -f /etc/systemd/system/clippify.service ]; then
  log "installing systemd unit"
  sudo cp deploy/clippify.service /etc/systemd/system/clippify.service
  sudo systemctl daemon-reload
  sudo systemctl enable clippify
fi

# ── 7. Caddy ────────────────────────────────────────────────────────────────
log "installing Caddyfile for $DOMAIN"
sudo mkdir -p /var/log/caddy
CLIPPIFY_DOMAIN="$DOMAIN" caddy validate --config deploy/Caddyfile --adapter caddyfile
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i "s|{\$CLIPPIFY_DOMAIN:clippify.example.com}|$DOMAIN|" /etc/caddy/Caddyfile
sudo systemctl reload caddy || sudo systemctl restart caddy

# ── 8. Health gate ──────────────────────────────────────────────────────────
log "waiting for /ready (max ~90s)"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8011/ready >/dev/null 2>&1; then
    log "READY after ${i} checks. Deploy of $TAG complete. Live at https://$DOMAIN"
    exit 0
  fi
  sleep 3
done
log "ERROR: /ready never came up. Logs: docker compose -f docker-compose.saas.yml logs api"
exit 1
