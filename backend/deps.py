"""
FastAPI dependency providers + board-access helpers.

Anything route handlers need from `Depends(...)`:
  - get_current_user - pulls user from JWT cookie / bearer token
  - require_admin    - admin-only guard
  - require_board    - factory for per-board access guards

Also defines the canonical board list and `user_has_board()` helper.
"""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request

from auth_utils import decode_access_token
from db import db


# All boards exposed to non-admin users (admins always pass).
ALL_BOARDS = [
    "weekly_scorecard",
    "quarterly_rocks",
    "launches",
    "cohort",
    "interviews",
    "students",
    "at_risk",
    "coach_activity",
    "spotlight",
    "leaderboard",
    "tickets",
    "private_videos",
    "refunds",
    "bot",
]
ADMIN_ONLY_BOARDS = ["settings"]


def user_has_board(user: dict, board: str) -> bool:
    """Admins always pass. Members must have the board in their board_access."""
    if user.get("role") == "admin":
        return True
    if board in ADMIN_ONLY_BOARDS:
        return False
    return board in (user.get("board_access") or [])


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_access_token(token)
        user = await db.users.find_one(
            {"id": payload["sub"]}, {"_id": 0, "password_hash": 0}
        )
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user


def require_board(board: str):
    """Factory: dependency that ensures the current user can access `board`."""
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if not user_has_board(user, board):
            raise HTTPException(
                status_code=403,
                detail=f"Access to '{board}' board is not granted",
            )
        return user
    return _check
