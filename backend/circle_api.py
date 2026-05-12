"""Helpers for Circle.so Admin/Headless API lookups used by the DM bot.

Auth model:
  • CIRCLE_API_TOKEN — Admin API v2 token, used for member lookups by ID.
  • CIRCLE_HEADLESS_TOKEN — Headless parent token. Exchanged for per-member
    access tokens via POST /api/v1/headless/auth_token (Bearer + email).
    Per-member access_tokens are short-lived; we cache them in MongoDB
    `app_settings.circle_headless_tokens` keyed by community_member_id and
    refresh proactively before expiry.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ADMIN_BASE = "https://app.circle.so/api/admin/v2"
HEADLESS_BASE = "https://app.circle.so/api/headless/v1"
HEADLESS_AUTH = "https://app.circle.so/api/v1/headless/auth_token"


def _admin_headers() -> dict:
    return {"Authorization": f"Token {os.environ.get('CIRCLE_API_TOKEN', '')}"}


def _headless_parent_token() -> Optional[str]:
    return (os.environ.get("CIRCLE_HEADLESS_TOKEN") or "").strip() or None


async def _get_access_token(db, admin_email: str) -> Optional[str]:
    """Return a Bearer access_token for the given admin's Headless session.

    Caches in MongoDB and refreshes when within 60s of expiry. Returns None
    if no parent token is configured or the auth call failed.
    """
    if not _headless_parent_token():
        return None
    now = datetime.now(timezone.utc)
    cache_id = f"circle_headless_token:{admin_email.lower()}"
    cached = await db.app_settings.find_one({"id": cache_id}, {"_id": 0})
    if cached:
        expires_at = cached.get("expires_at")
        try:
            if expires_at and datetime.fromisoformat(expires_at.replace("Z", "+00:00")) - now > timedelta(seconds=60):
                return cached.get("access_token")
        except Exception:
            pass

    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.post(
                HEADLESS_AUTH,
                headers={
                    "Authorization": f"Bearer {_headless_parent_token()}",
                    "Content-Type": "application/json",
                },
                json={"email": admin_email},
            )
            if r.status_code != 200:
                logger.warning(f"[circle-api] headless auth_token({admin_email}) failed: {r.status_code} {r.text[:160]}")
                return None
            body = r.json()
        except Exception as e:
            logger.warning(f"[circle-api] headless auth_token errored: {e}")
            return None

    await db.app_settings.update_one(
        {"id": cache_id},
        {"$set": {
            "id": cache_id,
            "access_token": body.get("access_token"),
            "expires_at": body.get("access_token_expires_at"),
            "community_member_id": body.get("community_member_id"),
            "cached_at": now.isoformat(),
        }},
        upsert=True,
    )
    return body.get("access_token")


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


async def fetch_latest_dm_message(db, admin_email: str, sender_id: int) -> Optional[str]:
    """Fetch the most recent DM message body from `sender_id` to the admin
    identified by `admin_email`. Returns None if Headless API is
    unconfigured, the access-token exchange failed, or no matching thread
    was found — caller falls back to a "passed to team" holding reply.
    """
    access_token = await _get_access_token(db, admin_email)
    if not access_token:
        return None
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=15) as c:
        try:
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

        target_uuid = None
        target_pm_body = None  # short-circuit if the parent_message is the one we want
        for t in threads:
            pm = t.get("parent_message") or {}
            sender = pm.get("sender") or {}
            pm_sender_id = sender.get("community_member_id") or sender.get("id")
            if pm_sender_id and int(pm_sender_id) == int(sender_id):
                target_uuid = pm.get("chat_room_uuid") or t.get("chat_room_uuid")
                target_pm_body = (
                    pm.get("body")
                    or (pm.get("rich_text_body") or {}).get("circle_ios_fallback_text")
                )
                break
            # Also check via participants list in case the parent_message
            # was authored by the admin (i.e. admin DM'd the student first).
            participants = t.get("chat_room_participants") or t.get("participants") or []
            for p in participants:
                pid = p.get("community_member_id") or (p.get("community_member") or {}).get("id")
                if pid and int(pid) == int(sender_id):
                    target_uuid = pm.get("chat_room_uuid") or t.get("chat_room_uuid") or t.get("uuid")
                    break
            if target_uuid:
                break

        if not target_uuid:
            logger.info(f"[circle-api] no direct chat room found for sender={sender_id}")
            return None

        # If we already grabbed the body from parent_message and the latest
        # message in the thread is from the sender (replies_count is 0 or
        # last_reply timestamp matches the parent), return it. Otherwise we
        # need to pull /messages to find their newest reply.
        try:
            r2 = await c.get(
                f"{HEADLESS_BASE}/chat_rooms/{target_uuid}/messages",
                headers=headers,
                params={"per_page": 10},
            )
            if r2.status_code != 200:
                # Fallback to parent_message body if available
                return target_pm_body
            msgs = r2.json().get("records") or []
        except Exception as e:
            logger.warning(f"[circle-api] chat_room messages errored: {e}")
            return target_pm_body

        # Newest-first: find first message FROM the sender
        for m in sorted(msgs, key=lambda x: x.get("created_at") or "", reverse=True):
            sender_obj = m.get("sender") or {}
            author_id = (
                sender_obj.get("community_member_id")
                or sender_obj.get("id")
                or m.get("community_member_id")
            )
            if author_id and int(author_id) == int(sender_id):
                body = (
                    m.get("body")
                    or m.get("plain_text")
                    or (m.get("rich_text_body") or {}).get("circle_ios_fallback_text")
                    or m.get("text")
                )
                if body:
                    return str(body).strip()
        return None


# ----------------------------------------------- Polling helpers (DM bot v2)
async def get_cached_admin_member_id(db, admin_email: str) -> Optional[int]:
    """Read the admin's community_member_id from the Headless auth cache
    (populated by `_get_access_token`). Used by the polling bot to tell its
    own (= the admin's) messages apart from the student's."""
    doc = await db.app_settings.find_one(
        {"id": f"circle_headless_token:{admin_email.lower()}"},
        {"_id": 0, "community_member_id": 1},
    )
    cid = (doc or {}).get("community_member_id")
    try:
        return int(cid) if cid else None
    except Exception:
        return None


async def list_dm_threads(db, admin_email: str, per_page: int = 30) -> list[dict]:
    """All Direct-Message chat threads visible to `admin_email`.

    Pages through Circle's results so we don't miss threads. Circle defaults
    to ~30 per page but the user typically has 50-100+ direct threads.
    """
    access_token = await _get_access_token(db, admin_email)
    if not access_token:
        return []
    all_records: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as c:
        for page in range(1, 6):  # safety cap at 5 pages = 500 threads
            try:
                r = await c.get(
                    f"{HEADLESS_BASE}/chat_threads",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"per_page": min(per_page, 100), "page": page},
                )
                if r.status_code != 200:
                    logger.warning(f"[circle-api] list_dm_threads p{page} failed: {r.status_code} {r.text[:120]}")
                    break
                body = r.json()
                recs = body.get("records") or []
                all_records.extend(recs)
                if not body.get("has_next_page"):
                    break
            except Exception as e:
                logger.warning(f"[circle-api] list_dm_threads errored: {e}")
                break
    return all_records


async def list_thread_messages_for_admin(
    db, admin_email: str, chat_room_uuid: str, per_page: int = 20,
) -> list[dict]:
    """Latest N messages in a chat room. Circle returns them newest-first."""
    access_token = await _get_access_token(db, admin_email)
    if not access_token:
        return []
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.get(
                f"{HEADLESS_BASE}/messages/{chat_room_uuid}/chat_room_messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"per_page": per_page},
            )
            if r.status_code != 200:
                logger.warning(f"[circle-api] list_thread_messages failed: {r.status_code} {r.text[:160]}")
                return []
            return r.json().get("records") or []
        except Exception as e:
            logger.warning(f"[circle-api] list_thread_messages errored: {e}")
            return []


async def post_dm_message(
    db, admin_email: str, chat_room_uuid: str, body: str,
) -> Optional[dict]:
    """Post a chat message as `admin_email` into the given chat room. Returns
    the created message dict (with `id`) or None on failure."""
    access_token = await _get_access_token(db, admin_email)
    if not access_token:
        return None
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.post(
                f"{HEADLESS_BASE}/messages/{chat_room_uuid}/chat_room_messages",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"body": body},
            )
            if r.status_code in (200, 201):
                return r.json()
            logger.warning(f"[circle-api] post_dm_message failed: {r.status_code} {r.text[:200]}")
        except Exception as e:
            logger.warning(f"[circle-api] post_dm_message errored: {e}")
        return None
