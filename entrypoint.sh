#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] waiting for postgres..."
python - <<'PY'
import os, time, sys
import psycopg
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
for i in range(60):
    try:
        with psycopg.connect(url, connect_timeout=2):
            print("[entrypoint] postgres is up"); sys.exit(0)
    except Exception as e:
        print(f"[entrypoint] db not ready ({i}): {e}"); time.sleep(2)
print("[entrypoint] postgres never came up"); sys.exit(1)
PY

echo "[entrypoint] running migrations..."
alembic upgrade head

echo "[entrypoint] seeding dev user..."
python -m saas.seed

echo "[entrypoint] starting API on :${APP_PORT:-8011}"
exec uvicorn saas.main:app --host 0.0.0.0 --port "${APP_PORT:-8011}"
