# dashboard/auth.py
"""Shared-password HTTP Basic Auth for the private family dashboard.

If DASH_USER/DASH_PASSWORD are unset, auth is OPEN (local dev). On Railway they MUST be
set (the runbook enforces this). Comparison is constant-time.
"""
from __future__ import annotations
import os
import base64
import secrets

from fastapi import Request, HTTPException

_REALM = "liquidity-scanner"


def _expected() -> tuple[str | None, str | None]:
    return os.environ.get("DASH_USER"), os.environ.get("DASH_PASSWORD")


def auth_enabled() -> bool:
    user, pw = _expected()
    return bool(user and pw)


def check_basic(header: str | None) -> bool:
    """True if auth is disabled (creds unset) OR the Basic Authorization header matches."""
    user, pw = _expected()
    if not (user and pw):
        return True  # not configured -> open (local dev)
    if not header or not header[:6].lower() == "basic ":
        return False
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except Exception:
        return False
    got_user, sep, got_pw = decoded.partition(":")
    if not sep:
        return False
    # single constant-time compare of the combined credential — no and/short-circuit oracle
    return secrets.compare_digest(f"{got_user}:{got_pw}", f"{user}:{pw}")


async def require_auth(request: Request) -> None:
    """FastAPI dependency: 401 with a Basic challenge unless the request is authorized."""
    if not check_basic(request.headers.get("authorization")):
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'})
