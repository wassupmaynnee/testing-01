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


def rate_limit(bucket: str, limit: int, window_s: int):
    """FastAPI dependency factory: allow `limit` requests per `window_s` per IP."""
    def _dep(request: Request):
        ip = _client_ip(request)
        key = f"clippify:rl:{bucket}:{ip}"
        try:
            r = _client()
            n = r.incr(key)
            if n == 1:
                r.expire(key, window_s)
            if n > limit:
                ttl = r.ttl(key)
                raise _RateLimited(ttl if ttl and ttl > 0 else window_s)
        except _RateLimited:
            raise
        except Exception as exc:  # noqa: BLE001 — fail open on cache trouble
            log.warning("rate limiter degraded (fail-open): %s", exc)
    return _dep


class _RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


def rate_limit_handler(_request: Request, exc: _RateLimited):
    resp = err("rate_limited", "Too many requests — please slow down.",
               status_code=429, retryAfter=exc.retry_after)
    resp.headers["Retry-After"] = str(exc.retry_after)
    return resp
