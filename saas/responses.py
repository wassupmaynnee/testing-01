"""The frozen {ok, data | error} JSON envelope used across every router."""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data}, status_code=status_code)


def err(code: str, message: str, status_code: int = 400, **extra: Any) -> JSONResponse:
    body = {"ok": False, "error": {"code": code, "message": message, **extra}}
    return JSONResponse(body, status_code=status_code)


def deferred(feature: str, plugs_in: str) -> JSONResponse:
    """Clean 'deferred' signal at a seam — not a stub, not an error in the live path."""
    return err(
        "deferred",
        f"{feature} is deferred in the walking-skeleton pass.",
        status_code=501,
        feature=feature,
        implement_at=plugs_in,
    )
