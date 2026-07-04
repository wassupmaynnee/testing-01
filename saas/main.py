"""FastAPI application entrypoint. Multi-router surface + static frontend."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .observability import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    log_event,
    SecurityHeadersMiddleware,
    configure_logging,
    instrument_metrics,
    scrub_event,
)
from .ratelimit import GlobalRateLimitMiddleware, _RateLimited, rate_limit_handler
from .responses import err
from .routers import auth, billing, clips, jobs, publish, referrals, stream
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
        before_send=scrub_event,
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
    configure_logging()
    _prod = settings.app_env == "production"
    app = FastAPI(
        title=f"{settings.app_name} SaaS", version="0.1.0", lifespan=lifespan,
        docs_url=None if _prod else "/docs",
        redoc_url=None if _prod else "/redoc",
        openapi_url=None if _prod else "/openapi.json",
    )

    # Web-layer hardening + request tracing (outermost first).
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    # Global per-IP limiter on every endpoint (auth routes add a stricter dual-key
    # limit on top). Redis-backed: survives restarts, shared across workers.
    app.add_middleware(GlobalRateLimitMiddleware)
    app.add_exception_handler(_RateLimited, rate_limit_handler)
    instrument_metrics(app)

    # Multi-router surface — pinned FastAPI keeps every include_router sub-route.
    app.include_router(auth.router)
    app.include_router(jobs.router)
    app.include_router(clips.router)
    app.include_router(stream.router)
    app.include_router(billing.router)
    app.include_router(publish.router)
    app.include_router(referrals.router)

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/health")
    def health():
        return {"ok": True, "data": {"status": "healthy", "service": settings.app_name}}

    @app.get("/ready")
    def ready():
        """Readiness: Postgres + Redis (+ R2 when configured) reachable, so the
        deploy host / Caddy can gate traffic until dependencies are up."""
        from sqlalchemy import text

        from .db import engine
        checks, healthy = {}, True
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["db"] = "up"
        except Exception as exc:  # noqa: BLE001
            log_event("readiness: db down", level=40, error=str(exc))
            checks["db"] = "down"
            healthy = False
        try:
            import redis
            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
            checks["redis"] = "up"
        except Exception as exc:  # noqa: BLE001
            log_event("readiness: redis down", level=40, error=str(exc))
            checks["redis"] = "down"
            healthy = False
        if settings.r2_enabled:
            try:
                from .storage import _client
                _client().head_bucket(Bucket=settings.r2_bucket)
                checks["r2"] = "up"
            except Exception as exc:  # noqa: BLE001
                log_event("readiness: r2 down", level=40, error=str(exc))
                checks["r2"] = "down"
                healthy = False
        if healthy:
            return {"ok": True, "data": {"status": "ready", **checks}}
        return JSONResponse(
            {"ok": False, "error": {"code": "not_ready", "message": "dependency down",
                                    "checks": checks}}, status_code=503)

    @app.get("/")
    def index():
        return FileResponse(str(WEB_DIR / "index.html"))

    @app.get("/signup")
    def signup_page():
        return FileResponse(str(WEB_DIR / "signup.html"))

    @app.get("/dashboard")
    def dashboard():
        return FileResponse(str(WEB_DIR / "dashboard.html"))

    @app.get("/r/{code}", include_in_schema=False)
    def referral_link(code: str):
        """Shareable refer-a-friend link -> signup with the code pre-applied."""
        from fastapi.responses import RedirectResponse
        safe = "".join(ch for ch in code if ch.isalnum())[:16]
        return RedirectResponse(url=f"/signup?ref={safe}", status_code=303)

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

    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_envelope(request, exc: RequestValidationError):  # noqa: ANN001
        """422s in the frozen envelope. Reports WHICH fields failed and why —
        but never echoes the submitted values back (no `input` reflection)."""
        fields = [
            {"field": ".".join(str(x) for x in e.get("loc", []) if x != "body"),
             "issue": e.get("type", "invalid")}
            for e in exc.errors()[:10]
        ]
        return JSONResponse(
            {"ok": False, "error": {"code": "validation_error",
                                    "message": "Invalid input.", "fields": fields}},
            status_code=422)


    @app.exception_handler(HTTPException)
    async def http_exc_envelope(request, exc: HTTPException):  # noqa: ANN001
        """Render HTTPExceptions (401 auth, etc.) in the frozen {ok,error}
        envelope instead of FastAPI's default {"detail": ...}."""
        detail = exc.detail if isinstance(exc.detail, str) else "request_failed"
        code = detail if detail.replace("_", "").isalnum() else "error"
        return JSONResponse(
            {"ok": False, "error": {"code": code, "message": detail}},
            status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(404)
    async def not_found(request, exc):  # noqa: ANN001
        if request.url.path.startswith("/api/"):
            return err("not_found", "Resource not found.", status_code=404)
        return JSONResponse({"ok": False, "error": {"code": "not_found",
                             "message": "Not found"}}, status_code=404)

    return app


app = create_app()
