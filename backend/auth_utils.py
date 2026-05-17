"""
Authentication helpers — password hashing + JWT token issuance/verification.

Pure functions; no DB dependency. The actual `get_current_user` dependency
that hits MongoDB lives in deps.py.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Response

JWT_ALGORITHM = "HS256"


def jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "type": "access",
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    # Pick cookie attributes based on environment:
    # - Local dev (PUBLIC_BASE_URL = http://localhost…): SameSite=lax + secure=False
    #   so cookies work over plain HTTP.
    # - Production (HTTPS frontend on a different domain from backend, e.g.
    #   Vercel + Render): SameSite=none + secure=True so the browser actually
    #   sends them on cross-site XHR/fetch requests.
    is_https = os.environ.get("PUBLIC_BASE_URL", "").startswith("https://")
    cookie_kwargs = dict(
        httponly=True,
        secure=is_https,
        samesite="none" if is_https else "lax",
        path="/",
    )
    response.set_cookie(
        "access_token", access, max_age=60 * 60 * 24, **cookie_kwargs,
    )
    response.set_cookie(
        "refresh_token", refresh, max_age=60 * 60 * 24 * 7, **cookie_kwargs,
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate an access token. Raises jwt exceptions on invalid."""
    payload = jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Invalid token type")
    return payload
