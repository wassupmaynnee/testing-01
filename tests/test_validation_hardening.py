"""Phase-4 validation hardening: 422 envelope without input echo, oversized
inputs, malformed bodies, injection strings neutralized, traversal blocked."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from saas.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _signup(client, email="vh@x.dev"):
    client.post("/api/auth/signup", data={"email": email, "password": "password123"})


# ---- 422s use the envelope and never echo submitted values ----
def test_validation_error_enveloped_no_echo(client):
    secret_value = "hunter2-super-secret"
    r = client.post("/api/auth/login", data={"email": secret_value})  # password missing
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == "validation_error"
    assert "fields" in body["error"] and body["error"]["fields"]
    assert secret_value not in r.text  # no input reflection
    assert "detail" not in body       # not FastAPI's default shape


def test_malformed_body_enveloped(client):
    r = client.post("/api/auth/login", content=b"\xff\xfe\x00garbage",
                    headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422)
    body = r.json()
    assert body["ok"] is False and "code" in body["error"]


# ---- oversized inputs ----
def test_oversized_password_rejected(client):
    r = client.post("/api/auth/signup",
                    data={"email": "big@x.dev", "password": "x" * 5000})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "weak_password"


def test_oversized_url_rejected(client):
    _signup(client, "url@x.dev")
    r = client.post("/api/jobs", data={"url": "https://youtube.com/watch?v=" + "a" * 3000})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_url"


def test_oversized_body_rejected_413(client):
    _signup(client, "body@x.dev")
    r = client.post("/api/auth/login", content=b"a" * 2_100_000,
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "Content-Length": "2100000"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


# ---- injection strings neutralized ----
def test_sql_injection_string_is_inert(client):
    inj = "x' OR '1'='1 --@x.dev"
    r = client.post("/api/auth/login", data={"email": inj, "password": "password123"})
    # parameterized ORM: behaves exactly like any unknown account
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_xss_string_stored_not_reflected_raw(client):
    _signup(client, "xss@x.dev")
    r = client.post("/api/jobs", data={"url": "https://youtube.com/watch?v=<script>x</script>"})
    assert r.status_code == 400  # fails the strict URL pattern
    assert "<script>" not in r.text  # never echoed back


# ---- path traversal ----
def test_path_traversal_clip_id_blocked(client):
    _signup(client, "trav@x.dev")
    for cid in ("..%2F..%2Fetc%2Fpasswd", "....//....//secret"):
        r = client.get(f"/api/clips/{cid}")
        assert r.status_code in (404, 422), f"traversal id {cid!r} -> {r.status_code}"
        assert r.json()["ok"] is False


def test_referral_code_sanitized_in_redirect(client):
    r = client.get("/r/abc%22%3E%3Cscript%3E", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert "<" not in loc and '"' not in loc and loc.startswith("/signup?ref=")
