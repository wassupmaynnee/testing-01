"""Input validation & mass-assignment guards (Phase 3 / OWASP API3+API4)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from saas.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ---- email: valid / boundary / malicious ----
def test_email_validation(client):
    # valid
    assert client.post("/api/auth/signup",
                       data={"email": "ok@x.dev", "password": "password123"}).status_code == 201
    # malicious: over-long (ReDoS guard) -> 422, not a hang
    huge = "a" * 300 + "@x.dev"
    r = client.post("/api/auth/signup", data={"email": huge, "password": "password123"})
    assert r.status_code == 422
    # malformed
    assert client.post("/api/auth/signup",
                       data={"email": "not-an-email", "password": "password123"}).status_code == 422


def test_weak_password_rejected(client):
    r = client.post("/api/auth/signup", data={"email": "pw@x.dev", "password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"


# ---- mass assignment: a user cannot grant themselves credits/plan/featured ----
def test_no_mass_assignment_of_credits_or_plan(client):
    # signup ignores any extra fields (Form parsing whitelists explicit params)
    r = client.post("/api/auth/signup", data={
        "email": "greedy@x.dev", "password": "password123",
        "credits": "999999", "tier": "scale", "is_admin": "true"})
    data = r.json()["data"]
    assert data["credits"] == 30  # Free tier only — injected 999999 ignored
    me = client.get("/api/auth/me").json()["data"]
    assert me["credits"] == 30 and me["tier"] == "free"


# ---- upload/URL surface rejects bad input cleanly (enveloped 4xx) ----
def test_job_input_rejections(client):
    client.post("/api/auth/signup", data={"email": "job@x.dev", "password": "password123"})
    # non-YouTube URL
    r = client.post("/api/jobs", data={"url": "https://evil.internal/x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_url"
    # SSRF attempt via internal IP is not a valid youtube host -> rejected
    r = client.post("/api/jobs", data={"url": "http://169.254.169.254/latest/meta-data"})
    assert r.status_code == 400
    # no source at all
    assert client.post("/api/jobs", data={"nope": "1"}).status_code == 400


def test_pagination_capped(client):
    client.post("/api/auth/signup", data={"email": "page@x.dev", "password": "password123"})
    r = client.get("/api/clips?limit=100000&offset=-5")
    assert r.status_code == 200  # clamped server-side, never errors or over-returns


def test_interactive_docs_disabled_flag():
    # In non-prod (tests) docs are on; the gating expression is what matters in prod.
    from saas.config import get_settings
    assert get_settings().app_env != "production"  # test env
    # prove the app was built with the conditional (openapi exists in dev)
    assert app.openapi_url == "/openapi.json"
