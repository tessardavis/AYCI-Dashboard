"""Helpers for Circle.so Admin/Headless API lookups used by the DM bot.

Auth model:
  • CIRCLE_API_TOKEN - Admin API v2 token, used for member lookups by ID.
  • CIRCLE_HEADLESS_TOKEN - Headless parent token. Exchanged for per-member
    access tokens via POST /api/v1/headless/auth_token (Bearer + email).
    Per-member access_tokens are short-lived; we cache them in MongoDB
    `app_settings.circle_headless_tokens` keyed by community_member_id and
    refresh proactively before expiry.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ADMIN_BASE = "https://app.circle.so/api/admin/v2"
ADMIN_V1_BASE = "https://app.circle.so/api/v1"
HEADLESS_BASE = "https://app.circle.so/api/headless/v1"
HEADLESS_AUTH = "https://app.circle.so/api/v1/headless/auth_token"

# Circle rate-limits aggressively (429), especially during the bulk coach-chat
# scan. Retry transient throttles with a short backoff so a scan rides through
# mild rate-limiting instead of returning empty.
_RETRY_STATUSES = {429, 503}
_MAX_RETRIES = 4


def _retry_after_seconds(r: httpx.Response) -> float:
    """Honour a Retry-After header (seconds) if Circle sends one, capped so a
    single 429 can't stall a request for minutes."""
    try:
        ra = (r.headers or {}).get("Retry-After")
        if ra:
            return min(float(ra), 20.0)
    except (TypeError, ValueError):
        pass
    return 0.0


async def _request_with_backoff(c: httpx.AsyncClient, method: str, url: str,
                                *, label: str = "", **kwargs) -> Optional[httpx.Response]:
    """Issue a request, retrying on 429/503 with Retry-After (else exponential
    1s/2s/4s) backoff. Returns the final Response (caller checks status), or
    None on a network-level error."""
    r: Optional[httpx.Response] = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = await c.request(method, url, **kwargs)
        except Exception as e:
            logger.warning(f"[circle-api] {label or url} errored: {e}")
            return None
        if r.status_code not in _RETRY_STATUSES or attempt == _MAX_RETRIES - 1:
            return r
        wait = _retry_after_seconds(r) or float(2 ** attempt)
        logger.info(f"[circle-api] {label or url} {r.status_code} - backoff {wait}s (attempt {attempt + 1})")
        await asyncio.sleep(wait)
    return r


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
        r = await _request_with_backoff(
            c, "POST", HEADLESS_AUTH,
            label=f"auth_token({admin_email})",
            headers={
                "Authorization": f"Bearer {_headless_parent_token()}",
                "Content-Type": "application/json",
            },
            json={"email": admin_email},
        )
        if r is None:
            return None
        if r.status_code != 200:
            logger.warning(f"[circle-api] headless auth_token({admin_email}) failed: {r.status_code} {r.text[:160]}")
            return None
        body = r.json()

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
    """Return basic member info + tags: {name, email, first_name, profile_url, tags}."""
    import circle_meter
    try:
        # Essential: reactive to inbound DMs / coach lookups, low volume (6h cached
        # by fetch_member_cached) - exempt from the breaker but still counted.
        r = await circle_meter.circle_admin_request(
            "GET", f"{ADMIN_BASE}/community_members/{member_id}",
            headers=_admin_headers(), timeout=15,
            endpoint="community_members", essential=True)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"[circle-api] fetch_member({member_id}) failed: {e}")
        return None
    d = r.json()
    name = (d.get("name")
            or " ".join(filter(None, [d.get("first_name"), d.get("last_name")])).strip()
            or d.get("public_uid"))
    tags = [t.get("name") for t in (d.get("member_tags") or []) if t.get("name")]
    return {
        "id": d.get("id"),
        "name": name,
        "first_name": d.get("first_name") or (name or "").split(" ")[0],
        "email": (d.get("email") or "").lower(),
        "profile_url": d.get("profile_url"),
        "tags": tags,
    }


async def list_member_emails_by_tag(tag_id: int, tag_name: str = "", max_pages: int = 40) -> list[str]:
    """List emails of community members carrying a given member tag, via the Admin
    API. Paginated + page-capped, routed through circle_meter (non-essential, so
    the breaker caps runaway cost). Belt-and-braces: keep only members whose
    member_tags actually include `tag_name` (in case the API tag filter is ignored,
    so we never mis-tag a non-Boss). One-off use (e.g. the Boss-badge backfill)."""
    import circle_meter
    emails: list[str] = []
    page = 1
    while page <= max_pages:
        try:
            # Tag-scoped endpoint: returns ONLY this tag's members (so ~5 pages
            # for the Boss tag, not the whole 15k tag-assignment list).
            r = await circle_meter.circle_admin_request(
                "GET", f"{ADMIN_BASE}/member_tags/{tag_id}/tagged_members",
                headers=_admin_headers(), timeout=30,
                params={"per_page": 100, "page": page},
                endpoint="tagged_members", essential=False)
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"[circle-api] list_member_emails_by_tag page {page} failed: {e}")
            break
        body = r.json()
        records = body.get("records") or []
        if not records:
            break
        for d in records:
            em = (d.get("user_email") or d.get("email") or "").strip().lower()
            if em:
                emails.append(em)
        has_next = bool(body.get("has_next_page")) or ((body.get("page_count") or 0) > page)
        if not has_next:
            break
        page += 1
    logger.info(f"[circle-api] list_member_emails_by_tag({tag_name or tag_id}): {len(set(emails))} emails over {page} page(s)")
    return sorted(set(emails))


async def fetch_member_cached(db, member_id: int | str, max_age_hours: int = 6) -> dict | None:
    """`fetch_member` with a MongoDB cache so we don't re-call Circle Admin
    API for every poll cycle. Cache key: `circle_members_cache.{member_id}`."""
    try:
        mid_int = int(member_id)
    except (TypeError, ValueError):
        return None
    doc = await db.circle_members_cache.find_one(
        {"id": f"member:{mid_int}"}, {"_id": 0, "data": 1, "cached_at": 1},
    )
    if doc and doc.get("data") and doc.get("cached_at"):
        try:
            cached_at = datetime.fromisoformat(doc["cached_at"])
            if (datetime.now(timezone.utc) - cached_at).total_seconds() < max_age_hours * 3600:
                return doc["data"]
        except Exception:
            pass
    data = await fetch_member(mid_int)
    if data:
        await db.circle_members_cache.update_one(
            {"id": f"member:{mid_int}"},
            {"$set": {
                "id": f"member:{mid_int}",
                "member_id": mid_int,
                "data": data,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
    return data


async def fetch_latest_dm_message(db, admin_email: str, sender_id: int) -> Optional[str]:
    """Fetch the most recent DM message body from `sender_id` to the admin
    identified by `admin_email`. Returns None if Headless API is
    unconfigured, the access-token exchange failed, or no matching thread
    was found - caller falls back to a "passed to team" holding reply.
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
    """All chat rooms visible to `admin_email`, sorted newest-first by
    `last_message.created_at`. Each row contains chat_room_kind, the other
    participant (for DMs), and the last_message inline. Pages through results.

    NOTE: this uses Circle's `/messages` endpoint (the "chat rooms list",
    despite the misleading name). The earlier `/chat_threads` endpoint
    silently omits fresh DMs that haven't yet had a reply thread, so we
    switched. Records are normalised to a small shape the rest of the bot
    expects: `{chat_room_uuid, chat_room: {kind, name}, last_message,
                  other_participants: [...] }`.
    """
    access_token = await _get_access_token(db, admin_email)
    if not access_token:
        return []
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as c:
        # 2 pages × 100 = 200 most-recently-active chat rooms per coach.
        # That's plenty - beyond ~200 they're all stale and rarely get a
        # new student message. Keeps poll cycles under ~30s for 5 coaches.
        for page in range(1, 3):
            try:
                r = await c.get(
                    f"{HEADLESS_BASE}/messages",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"per_page": min(per_page, 100), "page": page},
                )
                if r.status_code != 200:
                    logger.warning(f"[circle-api] list_dm_threads p{page} failed: {r.status_code} {r.text[:120]}")
                    break
                body = r.json()
                for rec in body.get("records") or []:
                    out.append({
                        "chat_room_uuid": rec.get("uuid"),
                        "chat_room": {
                            "kind": rec.get("chat_room_kind"),
                            "name": rec.get("chat_room_name"),
                        },
                        "last_message": rec.get("last_message") or {},
                        "other_participants_preview": rec.get("other_participants_preview") or [],
                        "unread_messages_count": rec.get("unread_messages_count") or 0,
                    })
                if not body.get("has_next_page"):
                    break
            except Exception as e:
                logger.warning(f"[circle-api] list_dm_threads errored: {e}")
                break
    return out


async def list_group_chats(db, admin_email: str, max_pages: int = 30) -> list[dict]:
    """All GROUP chat rooms `admin_email` is in, paged fully (up to max_pages ×
    100). Returns `[{uuid, name, participant_ids: [int]}]`. Used by the
    "no group chat" audit to find which private-tier students already have a
    coach chat - since every private chat includes the coaches, one coach's
    group-chat list covers them all.

    NB: `other_participants_preview` may be truncated for large rooms, so the
    audit also falls back to matching by chat-room name. Participant ids that
    do appear are authoritative.
    """
    access_token = await _get_access_token(db, admin_email)
    if not access_token:
        return []
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=25) as c:
        for page in range(1, max_pages + 1):
            r = await _request_with_backoff(
                c, "GET", f"{HEADLESS_BASE}/messages",
                label=f"list_group_chats({admin_email}) p{page}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"per_page": 100, "page": page},
            )
            if r is None:
                break
            if r.status_code != 200:
                logger.warning(f"[circle-api] list_group_chats p{page} failed: {r.status_code} {r.text[:120]}")
                break
            body = r.json()
            for rec in body.get("records") or []:
                # Circle's headless /messages reports group rooms as
                # chat_room_kind == "group_chat" (NOT "group" - that value
                # never appears, which silently returned 0 group chats and
                # made the link-existing scan look rate-limited).
                if rec.get("chat_room_kind") != "group_chat":
                    continue
                pids = []
                for p in rec.get("other_participants_preview") or []:
                    if isinstance(p, dict):
                        pid = p.get("id") or p.get("community_member_id")
                        if pid:
                            try:
                                pids.append(int(pid))
                            except (TypeError, ValueError):
                                pass
                out.append({
                    "uuid": rec.get("uuid"),
                    "name": rec.get("chat_room_name") or "",
                    "participant_ids": pids,
                })
            if not body.get("has_next_page"):
                break
    return out


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
    the created message dict (with `id`) or None on failure.

    Circle's Headless chat API requires the body in their tiptap-rich-text
    shape (`rich_text_body`); a plain `body` string is rejected with
    `Missing parameter: rich_text_body`. We build the minimal tiptap doc
    that covers our use case - single paragraph, plain text, line breaks as
    `hardBreak` nodes.
    """
    access_token = await _get_access_token(db, admin_email)
    if not access_token:
        return None
    rich = _build_tiptap_body(body)
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.post(
                f"{HEADLESS_BASE}/messages/{chat_room_uuid}/chat_room_messages",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"body": body, "rich_text_body": rich},
            )
            if r.status_code in (200, 201, 202):
                return r.json()
            logger.warning(f"[circle-api] post_dm_message failed: {r.status_code} {r.text[:240]}")
        except Exception as e:
            logger.warning(f"[circle-api] post_dm_message errored: {e}")
        return None


async def add_member_to_space(db, space_id: int, email: str) -> dict:
    """Add a community member (by EMAIL) to a SINGLE Circle space.

    Uses the **Admin v1** API (`POST /api/v1/space_members {space_id, email}`)
    with `CIRCLE_ADMIN_V1_TOKEN`. The Admin v2 `space_members` endpoint we tried
    first only ever 422'd ("User not added to space") - on v2 the only thing
    that works is `space_group_members`, which adds to the whole GROUP (an
    over-grant). v1 does a true single-space add (confirmed 2026-06-19). This is
    the same path the Zapier "Add Member to Space" step uses for the
    early-interview course-catch-up grant.

    Returns {ok, status, error}. Idempotent: v1 returns 200 with
    `{"success": false, "message": "User already added to space."}` for an
    existing member - treated as success."""
    email = (email or "").strip().lower()
    if not space_id or not email:
        return {"ok": False, "error": "missing space_id or email"}
    token = (os.environ.get("CIRCLE_ADMIN_V1_TOKEN") or "").strip()
    if not token:
        return {"ok": False, "error": "CIRCLE_ADMIN_V1_TOKEN not configured "
                "(need an Admin v1 token for single-space adds)"}
    import circle_meter
    if True:
        try:
            # Essential: a coach manually granting space access (user-facing,
            # rare) - exempt from the breaker but counted.
            r = await circle_meter.circle_admin_request(
                "POST", f"{ADMIN_V1_BASE}/space_members",
                headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
                json={"space_id": int(space_id), "email": email}, timeout=20,
                endpoint="space_members", essential=True,
            )
            txt = (r.text or "")[:300]
            try:
                data = r.json()
            except Exception:
                data = {}
            msg = str(data.get("message") or "").lower()
            already = "already added" in msg or "already a member" in msg
            if r.status_code in (200, 201) and (data.get("success") is True or already):
                return {"ok": True, "status": r.status_code, "already_member": already}
            logger.warning(f"[circle-api] add_member_to_space v1({space_id},{email}) failed {r.status_code} {txt}")
            return {"ok": False, "status": r.status_code, "error": txt}
        except Exception as e:
            logger.warning(f"[circle-api] add_member_to_space errored: {e}")
            return {"ok": False, "status": None, "error": str(e)[:300]}


async def send_direct_message(db, sender_email: str, member_id: int, body: str) -> bool:
    """Send a 1:1 Circle DM from `sender_email` to `member_id`. Find-or-creates
    the direct chat room (sender implicit from their token), then posts the
    message. Returns True on success."""
    if not member_id or not body:
        return False
    access_token = await _get_access_token(db, sender_email)
    if not access_token:
        logger.warning(f"[circle-api] send_direct_message: no token for {sender_email}")
        return False
    room_uuid = None
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.post(
                f"{HEADLESS_BASE}/messages",
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json={"chat_room": {"kind": "direct", "community_member_ids": [int(member_id)]}},
            )
            if r.status_code in (200, 201):
                b = r.json()
                room_uuid = (
                    b.get("chat_room_uuid") or (b.get("chat_room") or {}).get("uuid") or b.get("uuid")
                )
            else:
                logger.warning(f"[circle-api] send_direct_message room create failed {r.status_code} {r.text[:200]}")
        except Exception as e:
            logger.warning(f"[circle-api] send_direct_message room errored: {e}")
    if not room_uuid:
        return False
    posted = await post_dm_message(db, sender_email, room_uuid, body)
    return bool(posted)


async def create_group_chat(
    db, sender_email: str, member_ids: list[int], name: Optional[str] = None,
) -> Optional[dict]:
    """Find-or-create a GROUP chat room owned by `sender_email` that contains
    `member_ids` (the sender is implicit from their token). Returns
    {chat_room_uuid, name, raw} or None.

    Same Headless `POST /messages` find-or-create endpoint as the 1:1 helper in
    interview_eve_dm, with kind="group" + a name + multiple member ids.

    NB: Circle keys a group room on its exact member set - calling this with a
    different roster makes a NEW room, it does NOT mutate an existing one. The
    caller MUST guard against duplicates (we only ever call this for a student
    with no recorded private_chat_url and no existing coach chat). The exact
    `kind` token + group-create permission is the one contract detail to verify
    on the first live run."""
    ids = sorted({int(m) for m in member_ids if m})
    if not ids:
        return None
    access_token = await _get_access_token(db, sender_email)
    if not access_token:
        logger.warning(f"[circle-api] create_group_chat: no token for {sender_email}")
        return None
    chat_room: dict = {"kind": "group", "community_member_ids": ids}
    if name:
        chat_room["name"] = name
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.post(
                f"{HEADLESS_BASE}/messages",
                headers={"Authorization": f"Bearer {access_token}",
                         "Content-Type": "application/json"},
                json={"chat_room": chat_room},
            )
            if r.status_code in (200, 201):
                body = r.json()
                uuid = (
                    body.get("chat_room_uuid")
                    or (body.get("chat_room") or {}).get("uuid")
                    or body.get("uuid")
                )
                return {"chat_room_uuid": uuid, "name": name, "raw": body}
            logger.warning(f"[circle-api] create_group_chat failed {r.status_code} {r.text[:240]}")
            # Surface the failure detail so the caller can distinguish a DMs-off
            # rejection (→ flag "Awaiting DMs") from a generic error.
            return {"chat_room_uuid": None, "status": r.status_code, "error": (r.text or "")[:300]}
        except Exception as e:
            logger.warning(f"[circle-api] create_group_chat errored: {e}")
            return {"chat_room_uuid": None, "status": None, "error": str(e)[:300]}


def _build_tiptap_body(text: str) -> dict:
    """Build Circle's tiptap rich_text_body shape from plain text. Splits on
    newlines so multi-line replies render with proper line breaks."""
    text = text or ""
    lines = text.split("\n")
    content = []
    for i, line in enumerate(lines):
        if i > 0:
            content.append({"type": "hardBreak", "circle_ios_fallback_text": "\n"})
        if line:
            content.append({
                "type": "text",
                "text": line,
                "circle_ios_fallback_text": line,
            })
    return {
        "body": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": content}] if content else [{"type": "paragraph"}],
        },
        "circle_ios_fallback_text": text,
        "attachments": [],
        "inline_attachments": [],
        "sgids_to_object_map": {},
        "format": "chat",
        "community_members": [],
        "entities": [],
        "group_mentions": [],
        "polls": [],
    }
