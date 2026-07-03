"""API access-control + envelope contract across every route.

Proves: unauthenticated requests to protected routes get 401; one user cannot
reach another user's clip (object-level authz); every response is the
{ok, data XOR error} envelope. Uses the real app + real SQLite DB (conftest),
not ORM mocks.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from saas.db import SessionLocal
from saas.main import app
from saas.models import Clip, Job, JobStatus, User
from saas.security import hash_password


@pytest.fixture
def client():
    return TestClient(app)


def _envelope_ok(body: dict) -> bool:
    """Exactly one of data/error, keyed by ok."""
    if "ok" not in body:
        return False
    if body["ok"]:
        return "data" in body and "error" not in body
    return "error" in body and "data" not in body and "code" in body["error"]


# ----- unauthenticated access is rejected on every protected route -----
PROTECTED = [
    ("get", "/api/auth/me"),
    ("get", "/api/jobs"),
    ("post", "/api/jobs"),
    ("get", "/api/clips"),
    ("get", "/api/clips/abc123"),
    ("get", "/api/clips/abc123/file"),
    ("get", "/api/clips/abc123/download"),
    ("get", "/api/clips/abc123/thumb"),
    ("post", "/api/clips/abc123/feature"),
    ("post", "/api/billing/checkout"),
    ("post", "/api/billing/portal"),
    ("get", "/api/publish/providers"),
    ("get", "/api/publish/analytics"),
    ("post", "/api/publish/abc123"),
    ("get", "/api/referrals"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_reject_anonymous(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401, f"{method} {path} allowed anon ({resp.status_code})"
    body = resp.json()
    assert _envelope_ok(body) and body["ok"] is False


# ----- public routes stay public and enveloped -----
def test_public_routes_ok(client):
    for path in ("/health", "/api/billing/tiers", "/api/clips/featured"):
        r = client.get(path)
        assert r.status_code == 200
        assert _envelope_ok(r.json())


# ----- object-level authorization: user B cannot touch user A's clip -----
def _mk_user_with_clip(email: str):
    db = SessionLocal()
    u = User(email=email, password_hash=hash_password("password123"), credits=30,
             referral_code=email[:6])
    db.add(u)
    db.flush()
    job = Job(user_id=u.id, kind="upload", source_ref="x", status=JobStatus.completed, stage=6)
    db.add(job)
    db.flush()
    clip = Clip(job_id=job.id, title="secret", file_path="/tmp/x.mp4", score=0.9)
    db.add(clip)
    db.commit()
    cid = clip.id
    db.close()
    return cid


def test_cross_user_clip_access_blocked(client):
    victim_clip = _mk_user_with_clip("victim@x.dev")
    # attacker logs in as a DIFFERENT user
    client.post("/api/auth/signup", data={"email": "attacker@x.dev", "password": "password123"})
    for suffix in ("", "/file", "/download", "/thumb"):
        r = client.get(f"/api/clips/{victim_clip}{suffix}")
        assert r.status_code == 404, f"leaked {suffix} -> {r.status_code}"
        assert _envelope_ok(r.json())
    # and cannot feature (make public) someone else's clip
    r = client.post(f"/api/clips/{victim_clip}/feature", data={"on": "true"})
    assert r.status_code == 404


def test_signup_response_has_no_sensitive_fields(client):
    r = client.post("/api/auth/signup", data={"email": "leak@x.dev", "password": "password123"})
    data = r.json()["data"]
    for banned in ("password_hash", "password", "stripe_customer_id", "referral_code"):
        assert banned not in data
