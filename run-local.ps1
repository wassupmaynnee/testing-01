# run-local.ps1 — boot Clippify natively on Windows (no Docker).
#
# Prereqs you must have running/installed first:
#   * PostgreSQL 16 on localhost:5432 with role "clippify" / db "clippify"
#       psql -U postgres -c "CREATE ROLE clippify LOGIN PASSWORD 'clippify';"
#       psql -U postgres -c "CREATE DATABASE clippify OWNER clippify;"
#   * Redis on localhost:6379  (Memurai service, or `redis-server` in WSL)
#   * FFmpeg at C:\ffmpeg\bin\ffmpeg.exe + ffprobe.exe  (or set FFMPEG_BIN/FFPROBE_BIN)
#   * .env present with localhost DATABASE_URL/REDIS_URL (this script seeds one if missing)
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\run-local.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"

# 1. Virtual environment (clean deps — avoids a globally-broken starlette).
if (-not (Test-Path $py)) {
    Write-Host "[run-local] creating .venv ..." -ForegroundColor Cyan
    python -m venv .venv
}
Write-Host "[run-local] installing requirements ..." -ForegroundColor Cyan
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements.txt

# 2. .env — default to localhost services for native (non-Docker) hosts.
if (-not (Test-Path ".\.env")) {
    Write-Host "[run-local] creating .env from template (localhost services) ..." -ForegroundColor Cyan
    Copy-Item ".env.example" ".env"
    (Get-Content ".env") `
        -replace 'postgresql\+psycopg://clippify:clippify@db:5432/clippify', 'postgresql+psycopg://clippify:clippify@localhost:5432/clippify' `
        -replace 'redis://redis:6379/0', 'redis://localhost:6379/0' |
        Set-Content ".env" -Encoding utf8
    Write-Host "[run-local] EDIT .env if your Postgres/Redis differ, then re-run." -ForegroundColor Yellow
}

# 3. Migrate -> seed -> serve (the worker runs in-process inside the API).
Write-Host "[run-local] alembic upgrade head ..." -ForegroundColor Cyan
& ".\.venv\Scripts\alembic.exe" upgrade head

Write-Host "[run-local] seeding demo user ..." -ForegroundColor Cyan
& $py -m saas.seed

Write-Host "[run-local] starting API on http://localhost:8011 (Ctrl+C to stop) ..." -ForegroundColor Green
& $py -m uvicorn saas.main:app --port 8011
