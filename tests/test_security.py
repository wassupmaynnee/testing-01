"""Web-layer + data-leak protections: security headers, request-id tracing,
cookie flags, Sentry PII scrubbing, and referral-email masking."""
from __future__ import annotations

from starlette.testclient import TestClient

from saas.main import app
from saas.observability import scrub_event


def _c():
    return TestClient(app)


def test_security_headers_present():
    r = _c().get("/health")
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "content-security-policy" in h and "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"


def test_request_id_header_and_echo():
    r = _c().get("/health", headers={"X-Request-Id": "trace-me-123"})
    assert r.headers["x-request-id"] == "trace-me-123"
    r2 = _c().get("/health")
    assert r2.headers.get("x-request-id")  # auto-generated when not supplied


def test_session_cookie_is_httponly():
    c = _c()
    c.post("/api/auth/signup", data={"email": "cookie@x.dev", "password": "password123"})
    setc = " ".join(v for k, v in c.headers.items())  # cookies applied to jar
    # inspect the raw Set-Cookie from a fresh login
    r = c.post("/api/auth/login", data={"email": "cookie@x.dev", "password": "password123"})
    raw = r.headers.get("set-cookie", "")
    assert "mf_session=" in raw
    assert "httponly" in raw.lower()
    assert "samesite=lax" in raw.lower()
    _ = setc


def test_sentry_scrub_strips_pii():
    event = {
        "request": {
            "cookies": {"mf_session": "secret"},
            "data": {"password": "hunter2"},
            "headers": {"authorization": "Bearer x", "cookie": "mf_session=x", "user-agent": "ok"},
        },
        "user": {"email": "victim@x.dev", "ip_address": "1.2.3.4"},
        "message": "failure for user victim@example.com doing thing",
    }
    out = scrub_event(event, None)
    assert "cookies" not in out["request"]
    assert "data" not in out["request"]
    assert "authorization" not in out["request"]["headers"]
    assert "cookie" not in out["request"]["headers"]
    assert out["request"]["headers"]["user-agent"] == "ok"  # non-sensitive kept
    assert "user" not in out
    assert "victim@example.com" not in out["message"] and "[email]" in out["message"]


def test_referral_emails_are_masked():
    c = _c()
    c.post("/api/auth/signup", data={"email": "owner@x.dev", "password": "password123"})
    code = c.get("/api/referrals").json()["data"]["code"]
    # a referred user signs up under the code
    c2 = TestClient(app)
    c2.post("/api/auth/signup",
            data={"email": "referred.person@x.dev", "password": "password123", "ref": code})
    listing = c.get("/api/referrals").json()["data"]["referrals"]
    assert listing, "referral not recorded"
    shown = listing[0]["email"]
    assert "referred.person@x.dev" != shown and shown.startswith("r") and "***" in shown
