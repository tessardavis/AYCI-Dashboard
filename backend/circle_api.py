"""Helpers for Circle.so Admin/Headless API lookups used by the DM bot."""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ADMIN_BASE = "https://app.circle.so/api/admin/v2"
HEADLESS_BASE = "https://app.circle.so/api/headless/v1"


def _admin_headers() -> dict:
    return {"Authorization": f"Token {os.environ.get('CIRCLE_API_TOKEN', '')}"}


def _headless_headers() -> Optional[dict]:
    tok = (os.environ.get("CIRCLE_HEADLESS_TOKEN") or "").strip()
    if not tok:
        return None
    return {"Authorization": f"Bearer {tok}"}


async def fetch_member(member_id: int | str) -> dict | None:
    """Return basic member info: {name, email, first_name, profile_url}."""
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.get(f"{ADMIN_BASE}/community_members/{member_id}", headers=_admin_headers())
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"[circle-api] fetch_member({member_id}) failed: {e}")
            return None
        d = r.json()
        name = (d.get("name")
                or " ".join(filter(None, [d.get("first_name"), d.get("last_name")])).strip()
                or d.get("public_uid"))
        return {
            "id": d.get("id"),
            "name": name,
            "first_name": d.get("first_name") or (name or "").split(" ")[0],
            "email": (d.get("email") or "").lower(),
            "profile_url": d.get("profile_url"),
        }


async def fetch_latest_dm_message(admin_id: int, sender_id: int) -> Optional[str]:
    """Fetch the most recent DM message body from `sender_id` to `admin_id`.

    Returns None if Headless API is unconfigured or the message isn't
    available — the caller is expected to fall back to a "passed to team"
    holding reply when this happens.

    Requires `CIRCLE_HEADLESS_TOKEN` env var (Headless Member Token from
    Circle Settings → Developers, typically Plus-tier or above).
    """
    headers = _headless_headers()
    if not headers:
        return None

    async with httpx.AsyncClient(timeout=15) as c:
        try:
            # 1. List the admin's chat threads, looking for the one with this
            # sender as participant. Circle returns `records` sorted newest-first.
            r = await c.get(
                f"{HEADLESS_BASE}/chat_threads",
                headers=headers,
                params={"per_page": 30},
            )
            if r.status_code != 200:
                logger.warning(f"[circle-api] /chat_threads failed: {r.status_code} {r.text[:120]}")
                return None
            threads = r.json().get("records") or []
        except Exception as e:
            logger.warning(f"[circle-api] /chat_threads errored: {e}")
            return None

        # Find the DM thread (1:1) with our sender. Circle marks DMs with
        # `chat_type == "direct"` and `chat_thread_members` lists everyone.
        target = None
        for t in threads:
            if (t.get("chat_type") or "").lower() != "direct":
                continue
            members = t.get("chat_thread_members") or t.get("members") or []
            ids = {m.get("community_member_id") or m.get("id") for m in members if isinstance(m, dict)}
            if int(sender_id) in {int(x) for x in ids if x is not None}:
                target = t
                break
        if not target:
            logger.info(f"[circle-api] no direct thread found for sender={sender_id}")
            return None

        thread_id = target.get("id") or target.get("uuid")
        try:
            r2 = await c.get(
                f"{HEADLESS_BASE}/chat_threads/{thread_id}/messages",
                headers=headers,
                params={"per_page": 5, "sort": "-created_at"},
            )
            if r2.status_code != 200:
                logger.warning(f"[circle-api] thread messages failed: {r2.status_code} {r2.text[:120]}")
                return None
            msgs = r2.json().get("records") or []
        except Exception as e:
            logger.warning(f"[circle-api] thread messages errored: {e}")
            return None

        # Newest message FROM the sender (not echoed admin replies)
        for m in msgs:
            author_id = m.get("community_member_id") or (m.get("sender") or {}).get("id")
            if author_id and int(author_id) == int(sender_id):
                body = m.get("body") or m.get("plain_text") or m.get("text")
                if body:
                    return str(body).strip()
        return None
