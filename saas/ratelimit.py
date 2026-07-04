"""
Redis-backed fixed-window rate limiting for abuse-prone endpoints
(login / signup / job generation). Fails OPEN if Redis is unavailable so a
transient cache outage never locks users out; logs the degradation.

Keyed by client IP + a route bucket. Uses the existing Redis (broker/SSE) — no
new dependency, no new infrastructure.
"""
from __future__ import annotations

import logging

from fastapi import Request

from .config import get_settings
from .responses import err

log = logging.getLogger("clippify")
_redis = None


def _client():
    global _redis
    if _redis is None:
        import redis  # noqa: PLC0415 — already a dependency (broker/SSE)
        _redis = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def _client_ip(request: Request) -> str:
    # Trust the first XFF hop only behind our own proxy; fall back to peer.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hit(r, key: str, limit: int, window_s: int) -> None:
    """Fixed-window increment; raises _RateLimited when over the limit."""
    n = r.incr(key)
    if n == 1:
        r.expire(key, window_s)
    if n > limit:
        ttl = r.ttl(key)
        raise _RateLimited(ttl if ttl and ttl > 0 else window_s)


def rate_limit(bucket: str, limit: int, window_s: int):
    """FastAPI dependency factory: allow `limit` requests per `window_s` per IP."""
    def _dep(request: Request):
        ip = _client_ip(request)
        try:
            _hit(_client(), f"clippify:rl:{bucket}:{ip}", limit, window_s)
        except _RateLimited:
            raise
        except Exception as exc:  # noqa: BLE001 — fail open on cache trouble
            log.warning("rate limiter degraded (fail-open): %s", exc)
    return _dep


# --------------------------------------------------------------------------- #
# Auth limiter — DUAL-KEY: per-IP AND per-account-identifier, both enforced.  #
# 5 attempts / 15 min. The account key is a salted hash (never the raw email  #
# in Redis), and the 429 is identical whether or not the account exists.      #
# --------------------------------------------------------------------------- #
AUTH_LIMIT = 5
AUTH_WINDOW_S = 15 * 60


def auth_rate_limit(bucket: str = "auth"):
    """Dependency factory for login/token routes: 5 per 15 min per IP + per
    account identifier (email). Reads the form field non-destructively (FastAPI
    caches the parsed body, so the endpoint still receives it)."""
    import hashlib

    from fastapi import Form

    def _dep(request: Request, email: str = Form(None)):
        try:
            r = _client()
            ip = _client_ip(request)
            _hit(r, f"clippify:rl:{bucket}:ip:{ip}", AUTH_LIMIT, AUTH_WINDOW_S)
            if email:
                acct = hashlib.sha256(f"clippify:{email.strip().lower()}".encode()).hexdigest()[:24]
                _hit(r, f"clippify:rl:{bucket}:acct:{acct}", AUTH_LIMIT, AUTH_WINDOW_S)
        except _RateLimited:
            raise
        except Exception as exc:  # noqa: BLE001 — fail open on cache trouble
            log.warning("auth rate limiter degraded (fail-open): %s", exc)
    return _dep


# --------------------------------------------------------------------------- #
# Global limiter — every endpoint, per IP. Generous ceiling; the point is     #
# abuse/flood protection, not throttling real users. Infra probes and static  #
# assets are exempt (Caddy fronts /static in production anyway).              #
# --------------------------------------------------------------------------- #
GLOBAL_LIMIT = 300
GLOBAL_WINDOW_S = 60
_EXEMPT_PREFIXES = ("/static",)
_EXEMPT_PATHS = {"/health", "/ready", "/metrics"}


class GlobalRateLimitMiddleware:
    """Pure-ASGI global limiter (no BaseHTTPMiddleware overhead on every call)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES):
            return await self.app(scope, receive, send)
        ip = "unknown"
        for name, value in scope.get("headers", []):
            if name == b"x-forwarded-for":
                ip = value.decode().split(",")[0].strip()
                break
        else:
            client = scope.get("client")
            if client:
                ip = client[0]
        retry = None
        try:
            _hit(_client(), f"clippify:rl:global:{ip}", GLOBAL_LIMIT, GLOBAL_WINDOW_S)
        except _RateLimited as exc:
            retry = exc.retry_after
        except Exception as exc:  # noqa: BLE001 — fail open
            log.warning("global rate limiter degraded (fail-open): %s", exc)
        if retry is not None:
            resp = err("rate_limited", "Too many requests — please slow down.",
                       status_code=429, retryAfter=retry)
            resp.headers["Retry-After"] = str(retry)
            return await resp(scope, receive, send)
        return await self.app(scope, receive, send)


class _RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


def rate_limit_handler(_request: Request, exc: _RateLimited):
    resp = err("rate_limited", "Too many requests — please slow down.",
               status_code=429, retryAfter=exc.retry_after)
    resp.headers["Retry-After"] = str(exc.retry_after)
    return resp
