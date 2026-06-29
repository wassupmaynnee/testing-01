"""Auth primitives: PBKDF2 password hashing + signed HttpOnly mf_session token."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from .config import get_settings

SESSION_COOKIE = "mf_session"
_PBKDF2_ROUNDS = 240_000
_SESSION_TTL = 60 * 60 * 24 * 7  # 7 days


# ----------------------------- password hashing -----------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt_hex, hash_hex = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# --------------------------- signed session tokens --------------------------
def _b64(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_session(user_id: str) -> str:
    """user_id.expiry.hmac — stateless, signed with APP_SECRET."""
    secret = get_settings().app_secret.encode()
    expiry = str(int(time.time()) + _SESSION_TTL)
    payload = f"{user_id}.{expiry}"
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64(sig)}"


def read_session(token: str | None) -> str | None:
    if not token:
        return None
    try:
        user_id, expiry, sig_b64 = token.split(".")
    except ValueError:
        return None
    secret = get_settings().app_secret.encode()
    expected = hmac.new(secret, f"{user_id}.{expiry}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_unb64(sig_b64), expected):
        return None
    if int(expiry) < int(time.time()):
        return None
    return user_id
