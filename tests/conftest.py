"""Test bootstrap: point the app at a throwaway SQLite DB and known secrets
BEFORE any saas module imports, so db.py binds its engine to SQLite and
get_settings() caches the test values."""
from __future__ import annotations

import os
import tempfile

_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_DB.name}")
os.environ.setdefault("APP_SECRET", "test-app-secret")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
# Stripe stays "disabled" (no secret key) so the SDK is never imported in tests.
os.environ.pop("STRIPE_SECRET_KEY", None)
# Publishing stays "disabled" (no client id) so Google libs are never required
# for the contract tests that don't need a live upload.
os.environ.pop("YOUTUBE_OAUTH_CLIENT_ID", None)
os.environ.pop("YOUTUBE_OAUTH_CLIENT_SECRET", None)

import pytest  # noqa: E402

from saas.db import Base, engine  # noqa: E402
from saas import models  # noqa: E402,F401  (registers all tables on Base.metadata)


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
