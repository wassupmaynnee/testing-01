"""Symmetric encryption for OAuth tokens at rest.

The key is derived deterministically from APP_SECRET so no extra secret is
required, and the cryptography package is imported lazily — it is only needed on
the OAuth-publishing path, which is itself env-gated. The app boots and all
non-publishing paths work even if cryptography is not installed.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from .config import get_settings


@lru_cache
def _fernet():
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415 (lazy, optional dep)
    except ImportError as exc:  # pragma: no cover - only when publishing unconfigured
        raise RuntimeError(
            "cryptography is required for OAuth token storage; install requirements"
        ) from exc

    secret = get_settings().app_secret.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt a token string -> urlsafe token (str). Empty in, empty out."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a stored token -> plaintext (str). Empty in, empty out."""
    if not token:
        return ""
    return _fernet().decrypt(token.encode()).decode()
