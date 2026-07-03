#!/usr/bin/env bash
#
# Clippify rollback — redeploy the previous release tag and restore the
# pre-migration DB dump taken by deploy.sh.
#
#   ./rollback.sh PREVIOUS_TAG [BACKUP_STAMP]
#
# BACKUP_STAMP defaults to the last one deploy.sh recorded. Restoring the DB is
# only needed if the newer release ran a schema migration you must undo; if the
# migrations were purely additive and compatible, an app-only rollback (skip the
# restore) is safer. You will be prompted before the destructive restore.
set -euo pipefail

APP_DIR="/opt/clippify"
PREV_TAG="${1:?usage: rollback.sh PREVIOUS_TAG [BACKUP_STAMP]}"
BK="$APP_DIR/backups"
STAMP="${2:-$(cat "$BK/.last-backup" 2>/dev/null || true)}"
DOMAIN="${CLIPPIFY_DOMAIN:?set CLIPPIFY_DOMAIN}"

log() { echo -e "\n\033[1;31m[rollback]\033[0m $*"; }
cd "$APP_DIR"

log "checking out previous tag: $PREV_TAG"
git fetch --tags --force
git checkout -q "$PREV_TAG"

log "rebuilding + restarting the stack on $PREV_TAG"
docker compose -f docker-compose.saas.yml up -d --build --remove-orphans

if [ -n "$STAMP" ] && [ -f "$BK/pre-migrate-$STAMP.sql.gz" ]; then
  read -r -p "Restore DB from pre-migrate-$STAMP.sql.gz? This OVERWRITES current data [y/N] " ans
  if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
    log "restoring $BK/pre-migrate-$STAMP.sql.gz"
    gunzip -c "$BK/pre-migrate-$STAMP.sql.gz" | \
      docker exec -i clippify-saas-db-1 psql -U clippify -d clippify
    docker compose -f docker-compose.saas.yml restart api
  else
    log "skipped DB restore (app-only rollback)"
  fi
else
  log "no backup stamp found — app-only rollback"
fi

log "waiting for /ready"
for i in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8011/ready >/dev/null 2>&1 && { log "READY. Rolled back to $PREV_TAG at https://$DOMAIN"; exit 0; }
  sleep 3
done
log "ERROR: /ready did not come up after rollback"; exit 1
