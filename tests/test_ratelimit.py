"""Rate limiting: dual-key auth limiter (5/15min per IP AND per account),
window reset, global per-IP limiter, 429 shape (Retry-After + envelope), and
no account-existence leak. Uses fakeredis so no live Redis is required."""
from __future__ import annotations

import fakeredis
import pytest
from starlette.testclient import TestClient

from saas import ratelimit
from saas.main import app


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Point the limiter at a fresh fakeredis for every test (fail-open never
    triggers, so limits are actually enforced)."""
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(ratelimit, "_redis", r)
    return r


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email="limit@x.dev", ip="9.9.9.9"):
    return client.post("/api/auth/login",
                       data={"email": email, "password": "wrong-password"},
                       headers={"X-Forwarded-For": ip})


# ---- (a) 6th auth attempt within the window is rejected ----
def test_sixth_login_attempt_rejected_by_ip(client):
    for i in range(ratelimit.AUTH_LIMIT):
        assert _login(client).status_code == 401, f"attempt {i+1} should pass the limiter"
    r = _login(client)
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == "rate_limited"


def test_account_key_enforced_across_ips(client):
    # same account from 5 DIFFERENT IPs -> the per-account key still trips
    for i in range(ratelimit.AUTH_LIMIT):
        assert _login(client, ip=f"10.0.0.{i}").status_code == 401
    r = _login(client, ip="10.0.0.99")  # fresh IP, same email
    assert r.status_code == 429, "per-account key must trip independently of IP"


def test_429_does_not_leak_account_existence(client):
    # exhaust for a REAL account and a NONEXISTENT one; 429 bodies identical
    client.post("/api/auth/signup", data={"email": "real@x.dev", "password": "password123"})
    for _ in range(ratelimit.AUTH_LIMIT):
        _login(client, email="real@x.dev", ip="7.7.7.7")
        _login(client, email="ghost@x.dev", ip="8.8.8.8")
    real = _login(client, email="real@x.dev", ip="7.7.7.7")
    ghost = _login(client, email="ghost@x.dev", ip="8.8.8.8")
    assert real.status_code == ghost.status_code == 429
    assert real.json()["error"]["code"] == ghost.json()["error"]["code"]
    assert real.json()["error"]["message"] == ghost.json()["error"]["message"]


# ---- (b) window resets ----
def test_window_resets(fake_redis):
    r = fake_redis
    key = "clippify:rl:test:ip:1.2.3.4"
    for _ in range(3):
        ratelimit._hit(r, key, 3, 60)
    with pytest.raises(ratelimit._RateLimited):
        ratelimit._hit(r, key, 3, 60)
    r.delete(key)  # window expiry == key expiry in a fixed-window limiter
    ratelimit._hit(r, key, 3, 60)  # allowed again — no exception


# ---- (c) global limiter on non-auth endpoints ----
def test_global_limit_enforced(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "GLOBAL_LIMIT", 3)
    h = {"X-Forwarded-For": "6.6.6.6"}
    for _ in range(3):
        assert client.get("/api/billing/tiers", headers=h).status_code == 200
    r = client.get("/api/billing/tiers", headers=h)
    assert r.status_code == 429
    assert r.headers.get("retry-after")
    assert r.json()["error"]["code"] == "rate_limited"


def test_health_exempt_from_global_limit(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "GLOBAL_LIMIT", 1)
    h = {"X-Forwarded-For": "5.5.5.5"}
    for _ in range(5):
        assert client.get("/health", headers=h).status_code == 200
