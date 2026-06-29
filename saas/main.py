"""FastAPI application entrypoint. Multi-router surface + static frontend."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .responses import err
from .routers import auth, billing, clips, jobs, publish, stream
from .worker import start_worker

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _init_sentry() -> None:
    """Initialize error/performance monitoring only when a DSN is configured.
    Absent DSN is a complete no-op, so the app boots identically without it."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    import sentry_sdk  # noqa: PLC0415 — optional dependency, imported only when used
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    start_worker()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    _init_sentry()
    app = FastAPI(title=f"{settings.app_name} SaaS", version="0.1.0", lifespan=lifespan)

    # Multi-router surface — pinned FastAPI keeps every include_router sub-route.
    app.include_router(auth.router)
    app.include_router(jobs.router)
    app.include_router(clips.router)
    app.include_router(stream.router)
    app.include_router(billing.router)
    app.include_router(publish.router)

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/health")
    def health():
        return {"ok": True, "data": {"status": "healthy", "service": settings.app_name}}

    @app.get("/ready")
    def ready():
        """Readiness: confirms Postgres is reachable so the deploy host can gate traffic."""
        from sqlalchemy import text

        from .db import engine
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"ok": True, "data": {"status": "ready", "db": "up"}}
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"ok": False, "error": {"code": "not_ready", "message": str(exc)}},
                status_code=503,
            )

    @app.get("/")
    def index():
        return FileResponse(str(WEB_DIR / "index.html"))

    @app.get("/signup")
    def signup_page():
        return FileResponse(str(WEB_DIR / "signup.html"))

    @app.get("/dashboard")
    def dashboard():
        return FileResponse(str(WEB_DIR / "dashboard.html"))

    # Root-level SEO/asset routes (also available under /static, but crawlers and
    # browsers expect these at the origin root).
    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        return FileResponse(str(WEB_DIR / "robots.txt"), media_type="text/plain")

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap():
        return FileResponse(str(WEB_DIR / "sitemap.xml"), media_type="application/xml")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(str(WEB_DIR / "favicon.svg"), media_type="image/svg+xml")

    @app.get("/config.js", include_in_schema=False)
    def config_js():
        """Public, env-driven front-end config (no secrets — Sentry DSN and the
        Plausible domain are public values). Consumed by web/runtime.js."""
        cfg = {
            "sentryDsn": settings.sentry_dsn,
            "plausibleDomain": settings.plausible_domain,
            "appEnv": settings.app_env,
        }
        return Response(f"window.CLIPPIFY_CONFIG={json.dumps(cfg)};",
                        media_type="application/javascript")

    @app.exception_handler(404)
    async def not_found(request, exc):  # noqa: ANN001
        if request.url.path.startswith("/api/"):
            return err("not_found", "Resource not found.", status_code=404)
        return JSONResponse({"ok": False, "error": {"code": "not_found",
                             "message": "Not found"}}, status_code=404)

    return app


app = create_app()
