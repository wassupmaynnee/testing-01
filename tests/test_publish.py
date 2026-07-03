"""Tests for the OAuth publishing contracts:
  * uploads are ALWAYS private (privacyStatus hard-coded, no public path),
  * OAuth tokens encrypt/decrypt losslessly at rest,
  * the OAuth `state` is bound to the user (CSRF),
  * publishing degrades to a clean `deferred` when unconfigured (never a 500),
  * nothing publishes without an explicit call.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from saas import crypto, publish_core
from saas.db import SessionLocal
from saas.deps import current_user
from saas.models import User
from saas.routers import publish


# ------------------------------ private-default ------------------------------
def test_video_body_is_always_private():
    body = publish_core.video_insert_body("My clip", "desc")
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["selfDeclaredMadeForKids"] is False


def test_video_body_has_no_public_visibility_anywhere():
    body = publish_core.video_insert_body("x" * 300, "y")
    # The frozen constant is the only visibility, and the title is clamped to 100.
    assert publish_core.PRIVATE_VISIBILITY == "private"
    assert "public" not in str(body).lower()
    assert "unlisted" not in str(body).lower()
    assert len(body["snippet"]["title"]) <= 100


# ------------------------------ token encryption -----------------------------
def test_crypto_roundtrip():
    token = "ya29.super-secret-refresh-token"
    enc = crypto.encrypt(token)
    assert enc and enc != token            # actually encrypted, not stored plain
    assert crypto.decrypt(enc) == token


def test_crypto_empty_in_empty_out():
    assert crypto.encrypt("") == ""
    assert crypto.decrypt("") == ""


# --------------------------------- CSRF state --------------------------------
def test_state_is_bound_to_user():
    s = publish_core.make_state("user-abc")
    assert publish_core.verify_state(s, "user-abc") is True
    assert publish_core.verify_state(s, "user-xyz") is False
    assert publish_core.verify_state("garbage", "user-abc") is False


# ----------------------------- provider catalog ------------------------------
def test_youtube_disabled_without_credentials():
    assert publish_core.youtube_enabled() is False
    yt = next(p for p in publish_core.providers() if p["key"] == "youtube")
    assert yt["enabled"] is False


# -------------------- route-level: graceful deferral -------------------------
def _client_with_user():
    """Isolated app with just the publish router so no Redis/worker is needed."""
    db = SessionLocal()
    try:
        user = User(email="pub@example.com", password_hash="x", credits=30)
        db.add(user)
        db.commit()
        uid = user.id
    finally:
        db.close()

    app = FastAPI()
    app.include_router(publish.router)
    app.dependency_overrides[current_user] = lambda: SessionLocal().get(User, uid)
    return TestClient(app), uid


def test_providers_endpoint_envelope():
    client, _uid = _client_with_user()
    resp = client.get("/api/publish/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert any(p["key"] == "youtube" for p in body["data"]["providers"])
    assert body["data"]["accounts"] == []


def test_connect_is_deferred_when_unconfigured():
    client, _uid = _client_with_user()
    resp = client.get("/api/publish/youtube/connect")
    assert resp.status_code == 501
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "deferred"


def test_publish_is_deferred_when_unconfigured():
    client, _uid = _client_with_user()
    # youtube_enabled() is checked first, so this is deferred even for a bad id.
    resp = client.post("/api/publish/nonexistent-clip")
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "deferred"
