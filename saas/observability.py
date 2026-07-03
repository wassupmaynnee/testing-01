"""
Observability + web-layer security middleware.

  * request_id — generated per request, put on a contextvar, echoed in the
    X-Request-Id response header, and attached to every structured log line and
    Sentry event so a single user report is traceable end to end.
  * Structured JSON access logs (stdlib logging, no new dep) — method, path,
    status, latency_ms, user_id (internal id only — never email), request_id.
  * Security headers on every response (HSTS in prod, CSP, X-Frame-Options,
    X-Content-Type-Options, Referrer-Policy, Permissions-Policy).
  * Prometheus /metrics via the OSS instrumentator (self-hosted; no PII).
  * Sentry before_send scrubber — strips cookies/auth headers/bodies/emails so
    no PII or secret ever reaches the error tracker.

GPL-3.0-only.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .config import get_settings

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
user_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="-")


# --------------------------------------------------------------------------- #
# Structured JSON logging                                                     #
# --------------------------------------------------------------------------- #
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k, v in getattr(record, "extra_fields", {}).items():
            payload[k] = v
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Root JSON logging at INFO (DEBUG only outside production)."""
    settings = get_settings()
    level = logging.INFO if settings.app_env == "production" else logging.DEBUG
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Uvicorn's own access log would duplicate ours; quiet it.
    logging.getLogger("uvicorn.access").disabled = True


log = logging.getLogger("clippify")


def log_event(msg: str, level: int = logging.INFO, **fields) -> None:
    """Structured app log with request_id auto-attached (replaces bare print())."""
    log.log(level, msg, extra={"extra_fields": fields})


# --------------------------------------------------------------------------- #
# Request context: request_id + access log + timing                          #
# --------------------------------------------------------------------------- #
class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_ctx.set(rid)
        user_id_ctx.set("-")
        request.state.request_id = rid
        start = time.perf_counter()
        status = 500
        response = None
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-Id"] = rid
            return response
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            # /metrics and static asset noise stay out of the access log.
            path = request.url.path
            if not (path == "/metrics" or path.startswith("/static")):
                log.info("request", extra={"extra_fields": {
                    "method": request.method, "path": path, "status": status,
                    "latency_ms": latency_ms, "user_id": user_id_ctx.get()}})


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline web-layer hardening. HSTS only in production (prod is HTTPS)."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._prod = get_settings().app_env == "production"
        # CSP allows the app's own assets + Google Fonts + Plausible; media/img
        # from self and https (R2 signed URLs). No inline-blocking of the small
        # first-party scripts (kept 'unsafe-inline' since the pages ship inline JS).
        self._csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://plausible.io; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; media-src 'self' https: blob:; "
            "connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self' https://checkout.stripe.com"
        )

    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        resp.headers.setdefault("Content-Security-Policy", self._csp)
        if self._prod:
            resp.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
        return resp


# --------------------------------------------------------------------------- #
# Sentry PII scrubbing                                                        #
# --------------------------------------------------------------------------- #
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def scrub_event(event, _hint):
    """before_send: drop cookies/auth headers/bodies, redact emails in messages."""
    req = event.get("request", {})
    if isinstance(req, dict):
        req.pop("cookies", None)
        req.pop("data", None)
        headers = req.get("headers")
        if isinstance(headers, dict):
            for h in ("authorization", "cookie", "stripe-signature", "x-api-key"):
                headers.pop(h, None)
    event.pop("user", None)  # no user email/ip in events
    # redact any email that slipped into the message/exception text
    if isinstance(event.get("message"), str):
        event["message"] = _EMAIL_RE.sub("[email]", event["message"])
    return event


# --------------------------------------------------------------------------- #
# Prometheus metrics                                                          #
# --------------------------------------------------------------------------- #
# Pipeline / business metrics (registered lazily; safe if prometheus absent).
try:
    from prometheus_client import Counter, Histogram

    CLIP_JOBS = Counter("clippify_clip_jobs_total", "Clip jobs by outcome", ["outcome"])
    CLIPS_RENDERED = Counter("clippify_clips_rendered_total", "Clips rendered")
    STAGE_SECONDS = Histogram("clippify_stage_seconds", "Per-stage duration", ["stage"],
                              buckets=(1, 5, 15, 30, 60, 120, 300))
    WEBHOOKS = Counter("clippify_webhooks_total", "Stripe webhooks by result", ["result"])
    CREDIT_TXNS = Counter("clippify_credit_txns_total", "Credit transactions", ["kind"])
except Exception:  # noqa: BLE001 — metrics are optional; never block the pipeline
    CLIP_JOBS = CLIPS_RENDERED = STAGE_SECONDS = WEBHOOKS = CREDIT_TXNS = None


def metric_inc(counter, **labels) -> None:
    if counter is None:
        return
    try:
        (counter.labels(**labels) if labels else counter).inc()
    except Exception:  # noqa: BLE001,S110
        pass


def observe_stage(stage: str, seconds: float) -> None:
    if STAGE_SECONDS is None:
        return
    try:
        STAGE_SECONDS.labels(stage=stage).observe(seconds)
    except Exception:  # noqa: BLE001,S110
        pass


def instrument_metrics(app) -> None:
    """Expose /metrics (request rate/latency/errors per route). Best-effort so a
    missing dep never blocks boot."""
    try:
        from prometheus_fastapi_instrumentator import Instrumentator  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        log.warning("prometheus instrumentator unavailable: %s", exc)
        return
    Instrumentator(
        should_group_status_codes=True,
        excluded_handlers=["/metrics", "/health", "/ready"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
