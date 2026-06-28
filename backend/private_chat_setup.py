"""
Dashboard-native private-chat creation - Route 2, Phase 0.

See PRIVATE_CHAT_MIGRATION.md. Replaces the Monday-triggered "Private Chat …
when they join Circle" zaps (46/47/53/54). Phase 0 is MANUAL: a dry-run
`preview()` (no writes) and a per-student `create_for_student()` behind an
explicit admin click - nothing runs on a schedule yet.

Key win over the zaps: we match the student to their Circle identity on EITHER
email (or a strong name match), so students who joined Circle under a different
email than they signed up with on Kajabi no longer silently fall through.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from db import db
import settings_store
import circle_api
import student_lookup

logger = logging.getLogger(__name__)


def _eligible(row: dict) -> bool:
    """Same population the 'needs setup' flag cares about - current private
    tier / active B&G, not a Boss, not setup-dismissed. (Predicates live in
    routes.students_db; imported lazily to avoid an import cycle.)"""
    from routes.students_db import (
        _is_current_private_tier, _b_and_g_active, _is_boss,
    )
    if row.get("setup_not_needed") or _is_boss(row):
        return False
    return _is_current_private_tier(row.get("tier")) or _b_and_g_active(row.get("boost_and_go"))


async def _match_circle_member(row: dict, by_email: dict) -> tuple[Optional[dict], Optional[str]]:
    """Find the student's Circle member via email / circle_email / any "Other
    emails" address (exact) or a strong fuzzy name match. Returns (member,
    matched_via) or (None, None). Matching on Other emails mirrors the
    combined-identity model used for bonus/Calendly matching - a student who
    joined Circle under a different address than their main one still resolves."""
    import re as _re
    for key in ("email", "circle_email"):
        e = (row.get(key) or "").strip().lower()
        if e and e in by_email:
            return by_email[e], key
    for tok in _re.split(r"[,;\s]+", row.get("other_emails") or ""):
        e = tok.strip().lower()
        if e and "@" in e and e in by_email:
            return by_email[e], "other_emails"
    name = (row.get("name") or "").strip()
    if name:
        hits = await student_lookup.name_search(db, name, limit=1)
        top = hits[0] if hits else None
        if top and (top.get("match_score") or 0) >= 80 and (top.get("email") or "").strip():
            # name_search returns slim hits without id - re-resolve from the cache
            te = (top["email"] or "").strip().lower()
            if te in by_email:
                return by_email[te], "name"
    return None, None


async def _build_email_index() -> dict:
    members = await student_lookup._get_name_index(db)
    return {
        (m.get("email") or "").strip().lower(): m
        for m in members
        if (m.get("email") or "").strip()
    }


def _looks_like_dms_off(error_text: Optional[str], status) -> bool:
    """Did Circle reject the group-chat create specifically because the student
    has direct messages switched off? Only true for an explicit DMs/privacy
    message on a CLIENT-side rejection (4xx). A generic 500 "something went
    wrong" is NOT treated as DMs-off - that was a false positive (members with
    DMs on, e.g. Chenai/Emma, were wrongly flagged "Awaiting DMs"); those now
    surface as a real error so the true cause shows."""
    t = (error_text or "").lower()
    if not t:
        return False
    keywords = (
        "direct message", "messaging is", "messaging disabled", "disabled messaging",
        "not allow", "cannot be messaged", "can't be messaged", "does not allow",
        "messaging off", "privacy",
    )
    hit = any(k in t for k in keywords)
    # Only treat as DMs-off on a client-side rejection, not a 5xx/transient.
    return hit and status in (400, 403, 409, 422)


def _chat_name(row: dict) -> str:
    fn = (row.get("first_name") or (row.get("name") or "").split(" ")[0] or "").strip()
    return f"{fn} - Private Coaching".strip(" -") or "Private Coaching"


# Audience = which welcome template applies. Derived from tier / B&G level
# because the message's tier name, allowance and links differ.
_AUDIENCE_DISPLAY = {
    "private_plus": "Private Plus",
    "vip": "VIP",
    "boost_and_go": "Boost & Go",
    "boost_and_go_plus": "Boost & Go Plus",
}


def _audience(row: dict) -> Optional[str]:
    t = (row.get("tier") or "").strip().lower()
    if t in ("academy private plus", "upgrade private plus", "private plus"):
        return "private_plus"
    if t in ("vip", "upgrade vip"):
        return "vip"
    if t == "boost & go plus":
        return "boost_and_go_plus"
    if t == "boost & go":
        return "boost_and_go"
    b = (row.get("boost_and_go") or "").strip().lower()
    if "b&g" in b or b == "upgraded":
        return "boost_and_go_plus" if "plus" in b else "boost_and_go"
    return None


def _welcome_context(row: dict) -> dict:
    from routes.students_db import expected_video_allowance
    name = (row.get("name") or "").strip()
    fn = (row.get("first_name") or (name.split(" ")[0] if name else "")).strip()
    ln = (row.get("surname") or (" ".join(name.split(" ")[1:]) if name else "")).strip()
    aud = _audience(row)
    va = row.get("video_allowance")
    if va in (None, ""):
        va = expected_video_allowance(row.get("tier"), row.get("boost_and_go"))
    return {
        "first_name": fn or "there",
        "last_name": ln,
        "full_name": name,
        "email": (row.get("email") or "").strip().lower(),
        "tier": _AUDIENCE_DISPLAY.get(aud) or (row.get("tier") or ""),
        "video_allowance": str(va) if va not in (None, "") else "",
    }


def _render(template: str, ctx: dict) -> str:
    out = template
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", v)
    return out


async def preview(db_) -> dict:
    """Dry run - who WOULD get a chat, and whether we can resolve them on
    Circle. Writes nothing."""
    cfg = await settings_store.get_private_chat_config(db_)
    coaches_with_email = [c for c in cfg["coaches"] if c.get("email")]
    config_ready = bool(coaches_with_email) and bool(cfg.get("sender_email"))
    templates = cfg.get("welcome_templates") or {}

    by_email = await _build_email_index()
    ready, not_on_circle, awaiting_dms = [], [], []

    async for r in db_.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        if not _eligible(r):
            continue
        if (r.get("private_chat_url") or "").strip():
            continue  # already has a chat - never touch
        base = {
            "id": r["_id"],
            "name": r.get("name"),
            "tier": r.get("tier"),
            "boost_and_go": r.get("boost_and_go"),
            "kajabi_email": (r.get("email") or "").strip().lower() or None,
        }
        # A pending status (e.g. "Awaiting DMs") means a create was attempted and
        # the student needs to enable Circle DMs - surface separately, not as
        # "ready", so the team knows to chase rather than re-click.
        status = (r.get("private_chat_status") or "").strip()
        if status:
            awaiting_dms.append({**base, "status": status})
            continue
        member, via = await _match_circle_member(r, by_email)
        if member:
            aud = _audience(r)
            ready.append({
                **base,
                "matched_via": via,
                "circle_member_id": member.get("id"),
                "circle_email": (member.get("email") or "").strip().lower(),
                "chat_name": _chat_name(r),
                "audience": aud,
                "has_template": bool(aud and (templates.get(aud) or "").strip()),
            })
        else:
            not_on_circle.append(base)

    ready.sort(key=lambda x: x.get("name") or "")
    not_on_circle.sort(key=lambda x: x.get("name") or "")
    awaiting_dms.sort(key=lambda x: x.get("name") or "")
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "config_ready": config_ready,
        "coaches": cfg["coaches"],
        "sender_email": cfg.get("sender_email"),
        "counts": {"ready": len(ready), "not_on_circle": len(not_on_circle),
                   "awaiting_dms": len(awaiting_dms)},
        "ready": ready,
        "not_on_circle": not_on_circle,
        "awaiting_dms": awaiting_dms,
    }


def _norm_name(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", (s or "").lower())).strip()


_GATHER_CACHE_KEY = "private_chat_coach_chats"
_GATHER_TTL_SECONDS = 600  # 10 min - listing all coaches' chats is slow + rate-limited


async def _bust_gather_cache(db_) -> None:
    try:
        await db_.cache.delete_many({"_id": {"$regex": f"^{_GATHER_CACHE_KEY}"}})
    except Exception:
        pass


async def _gather_coach_chats(db_, coach_emails: list, use_cache: bool = True) -> tuple:
    """Union of every coach's Circle group chats →
    (member_ids set, names list, coaches_read list, chats list). Reading ALL
    coaches (not just the sender) is essential: historical chats were made by
    Oksana and the go-forward sender (Coralie) isn't in them, so this is how we
    detect an existing chat and never spawn a duplicate.

    CACHED for 10 min (Mongo) because listing 4 coaches' chats is the slow,
    rate-limited step that was timing out the create button. `chats` carries each
    room's {uuid, name, participant_ids} so a caller can record the URL of an
    existing chat onto the student's row."""
    key = f"{_GATHER_CACHE_KEY}:{','.join(sorted(coach_emails))}"
    if use_cache:
        doc = await db_.cache.find_one({"_id": key})
        ca = (doc or {}).get("cached_at")
        if ca:
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - ca).total_seconds() < _GATHER_TTL_SECONDS:
                p = doc.get("payload") or {}
                return (set(p.get("member_ids") or []), p.get("names") or [],
                        p.get("coaches_read") or [], p.get("chats") or [])

    member_ids: set = set()
    names: list = []
    coaches_read: list = []
    chats: list = []
    # Read each coach's chats CONCURRENTLY. Every coach authenticates with their
    # OWN Circle token, so this fans out across 4 separate auth contexts rather
    # than serialising them - ~4x faster wall time. Sequential reads were
    # blowing the caller's 75s budget (4 coaches × slow paged reads). Each
    # coach still paginates internally, so we never burst more than ~4 requests
    # at once. A coach that errors/empties is just skipped (partial coverage is
    # fine - every private chat includes the coaches, so the others cover it).
    results = await asyncio.gather(
        *[circle_api.list_group_chats(db_, ce) for ce in coach_emails],
        return_exceptions=True,
    )
    for ce, cc in zip(coach_emails, results):
        if isinstance(cc, BaseException) or not cc:
            continue
        coaches_read.append({"email": ce, "chats": len(cc)})
        for ch in cc:
            pids = ch.get("participant_ids") or []
            member_ids.update(pids)
            names.append(_norm_name(ch.get("name") or ""))
            chats.append({"uuid": ch.get("uuid"), "name": ch.get("name") or "", "participant_ids": pids})
    try:
        await db_.cache.update_one(
            {"_id": key},
            {"$set": {"cached_at": datetime.now(timezone.utc), "payload": {
                "member_ids": sorted(member_ids), "names": names,
                "coaches_read": coaches_read, "chats": chats,
            }}},
            upsert=True,
        )
    except Exception:
        pass
    return member_ids, names, coaches_read, chats


async def no_chat_audit(db_) -> dict:
    """Reconciliation audit: current private-tier students who have NO coach
    group chat in Circle. More accurate than the `private_chat_url` field
    because it checks Circle directly - catches students with a *dead* URL too
    (e.g. a chat that "succeeded" in the zap but the student has DMs off).

    Lists a resident coach's group chats (every private chat includes the
    coaches), then flags eligible students not present in any of them. The
    cause isn't necessarily DMs-off (could be dual-email or never-created) -
    DMs-off is confirmed when chat creation is attempted and fails.

    Read-only. Best-effort matching: by Circle member id (authoritative) with a
    fall-back to chat-room name, since participant previews can be truncated.
    """
    cfg = await settings_store.get_private_chat_config(db_)
    coach_emails = [c["email"] for c in cfg["coaches"] if c.get("email")]
    if not coach_emails:
        return {"ok": False, "error": "Set at least one coach's Circle email in Private chat setup first."}

    # Union every coach's group chats (see _gather_coach_chats) - survives a
    # coach whose session can't be minted and covers historical Oksana chats.
    chat_member_ids, chat_names, coaches_read, _chats = await _gather_coach_chats(db_, coach_emails)
    if not coaches_read:
        return {"ok": False, "error": (
            "Couldn't read any coach's Circle group chats. The Circle parent "
            "token can only mint a session for coaches who are admins/moderators "
            "- check that at least one configured coach has those rights."
        )}

    by_email = await _build_email_index()
    no_chat, not_on_circle = [], []

    async for r in db_.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        if not _eligible(r):
            continue
        member, via = await _match_circle_member(r, by_email)
        base = {
            "id": r["_id"],
            "name": r.get("name"),
            "tier": r.get("tier"),
            "boost_and_go": r.get("boost_and_go"),
            "email": (r.get("email") or "").strip().lower() or None,
            "has_dead_url": bool((r.get("private_chat_url") or "").strip()),
            "private_chat_status": r.get("private_chat_status") or None,
        }
        if not member or not member.get("id"):
            not_on_circle.append(base)
            continue
        mid = int(member["id"])
        if mid in chat_member_ids:
            continue  # confirmed in a coach group chat
        # Fallback: a chat named after the student (preview may have truncated ids)
        nm = _norm_name(r.get("name") or "")
        if nm and any(nm and nm in cn for cn in chat_names):
            continue
        no_chat.append({**base, "circle_member_id": mid, "matched_via": via})

    no_chat.sort(key=lambda x: x.get("name") or "")
    not_on_circle.sort(key=lambda x: x.get("name") or "")
    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "coaches_checked": coaches_read,
        "group_chats_scanned": sum(c["chats"] for c in coaches_read),
        "counts": {"no_chat": len(no_chat), "not_on_circle": len(not_on_circle)},
        "no_chat": no_chat,
        "not_on_circle": not_on_circle,
    }


async def create_via_webhook(db_, student_id: str) -> dict:
    """Trigger chat creation via the dashboard's Zapier catch-hook (the reliable
    path - a Catch-Hook zap does Circle's "Start Group Chat" + posts the welcome
    + POSTs the URL back to /students-db/update-by-email). The dashboard owns the
    decision + the rendered per-tier welcome message; the zap just executes.
    Replaces the unreliable headless group-create and the Monday-triggered zaps."""
    cfg = await settings_store.get_private_chat_config(db_)
    url = (cfg.get("create_webhook_url") or "").strip()
    if not url:
        return {"ok": False, "error": "no create webhook configured (Settings > Private chat setup)"}
    row = await db_.academy_members.find_one({"_id": student_id})
    if not row:
        return {"ok": False, "error": "student not found"}
    if not _eligible(row):
        return {"ok": False, "error": "student is not an eligible private-tier row"}
    if (row.get("private_chat_url") or "").strip():
        return {"ok": False, "skipped": "already_has_chat", "private_chat_url": row["private_chat_url"]}
    audience = _audience(row)
    template = (cfg.get("welcome_templates") or {}).get(audience or "")
    if not (template or "").strip():
        return {"ok": False, "error": f"no welcome template configured for audience '{audience}'"}
    welcome = _render(template, _welcome_context(row))
    sender = (cfg.get("sender_email") or "").strip().lower()
    # Coaches to ADD to the chat, EXCLUDING the sender - the sender is the chat's
    # creator (the Zapier Circle connection) and Circle rejects adding the creator
    # to their own chat ("you can't direct message yourself"). The student email
    # is sent separately so the zap maps [coaches + email] into Member Emails.
    coach_emails = [
        e for e in ((c.get("email") or "").strip().lower() for c in cfg["coaches"])
        if e and e != sender
    ]
    payload = {
        "event": "private_chat_create",
        "student_id": row["_id"],
        "email": (row.get("email") or "").strip().lower(),
        "circle_email": (row.get("circle_email") or "").strip().lower(),
        "name": row.get("name"),
        "first_name": row.get("first_name"),
        "tier": row.get("tier"),
        "boost_and_go": row.get("boost_and_go"),
        "audience": audience,
        "welcome_message": welcome,
        "coaches": coach_emails,
        "sender_email": sender,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url, json=payload)
        ok = r.status_code in (200, 201, 202, 204)
        if not ok:
            await db_.academy_members.update_one({"_id": row["_id"]}, {"$set": {
                "private_chat_last_error": f"chat-create webhook returned {r.status_code}: {r.text[:160]}"[:300],
                "private_chat_last_error_at": datetime.now(timezone.utc)}})
            return {"ok": False, "error": f"chat-create webhook returned {r.status_code}"}
    except Exception as e:
        await db_.academy_members.update_one({"_id": row["_id"]}, {"$set": {
            "private_chat_last_error": f"chat-create webhook errored: {str(e)[:160]}"[:300],
            "private_chat_last_error_at": datetime.now(timezone.utc)}})
        return {"ok": False, "error": f"chat-create webhook errored: {str(e)[:160]}"}
    logger.info(f"[private-chat] create requested via webhook for {student_id} ({audience})")
    return {"ok": True, "id": student_id, "via": "webhook", "queued": True}


async def create_for_student(db_, student_id: str) -> dict:
    """Create ONE student's coach group chat. Heavily guarded against
    duplicates (Circle can't mutate a room's roster, so a wrong call makes a
    confusing second chat). Returns a diagnostic dict - `raw` carries Circle's
    response so we can confirm the contract on the first live run.

    Phase 0 scope: match → no-dup guards → create group chat → write back →
    post welcome. TODO before Phase 1: apply the onboarding Circle tag and the
    Slack alert the zaps do (tag name + channel still to confirm), and verify
    the private_chat_url format against an existing row.
    """
    cfg = await settings_store.get_private_chat_config(db_)
    sender_email = (cfg.get("sender_email") or "").strip().lower()
    coach_emails = [c["email"] for c in cfg["coaches"] if c.get("email")]
    if not sender_email or not coach_emails:
        return {"ok": False, "error": "coach config incomplete (need coach emails + a sender)"}

    row = await db_.academy_members.find_one({"_id": student_id})
    if not row:
        return {"ok": False, "error": "student not found"}
    if not _eligible(row):
        return {"ok": False, "error": "student is not an eligible private-tier row"}
    if (row.get("private_chat_url") or "").strip():
        return {"ok": False, "skipped": "already_has_chat", "private_chat_url": row["private_chat_url"]}

    # Resolve the welcome template for this student's audience up-front - refuse
    # to create a chat we can't open with the right (tier-specific) message.
    audience = _audience(row)
    template = (cfg.get("welcome_templates") or {}).get(audience or "")
    if not (template or "").strip():
        return {"ok": False, "error": f"no welcome template configured for audience '{audience}'"}

    by_email = await _build_email_index()
    member, via = await _match_circle_member(row, by_email)
    if not member or not member.get("id"):
        return {"ok": False, "skipped": "not_on_circle"}
    student_mid = int(member["id"])
    student_circle_email = (member.get("email") or "").strip().lower()

    # Circle-side duplicate guard: does ANY coach already share a group chat
    # with this student? Critically checks all coaches, not just the sender -
    # historical chats were made by Oksana and Coralie (the sender) isn't in
    # them, so a sender-only check would miss them and spawn a duplicate chat
    # (→ a new thread, splitting the student's video replies). Matches by member
    # id, with a chat-name fallback for truncated participant previews.
    try:
        all_coach_emails = [c["email"] for c in cfg["coaches"] if c.get("email")]
        existing_ids, existing_names, _, existing_chats = await _gather_coach_chats(db_, all_coach_emails)
        nm = _norm_name(row.get("name") or "")
        # Find the actual existing room (by member id, then name) so we can
        # record its URL - not just refuse. (Fixes "set up but no link on the
        # dashboard": e.g. Cate Luce already had a chat, we skipped without
        # recording it, so she kept showing as missing.)
        match_uuid = None
        for ch in existing_chats:
            if student_mid in (ch.get("participant_ids") or []):
                match_uuid = ch.get("uuid"); break
        if not match_uuid and nm:
            for ch in existing_chats:
                if nm and nm in _norm_name(ch.get("name") or ""):
                    match_uuid = ch.get("uuid"); break
        if student_mid in existing_ids or (nm and any(nm in cn for cn in existing_names)) or match_uuid:
            if match_uuid:
                chat_url = f"https://app.circle.so/c/messages/{match_uuid}"
                now = datetime.now(timezone.utc)
                pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"private_chat_url"})
                await db_.academy_members.update_one({"_id": student_id}, {"$set": {
                    "private_chat_url": chat_url,
                    "private_chat_circle_uuid": match_uuid,
                    "private_chat_status": "",
                    "dashboard_edited_fields": pinned,
                    "dashboard_edited_at": now,
                    "dashboard_edited_by": "private-chat-setup",
                }})
                logger.info(f"[private-chat] linked existing chat {match_uuid} for {student_id}")
                return {"ok": True, "id": student_id, "recorded_existing": True, "private_chat_url": chat_url}
            return {"ok": False, "skipped": "existing_circle_chat_found"}
    except Exception as e:
        logger.info(f"[private-chat] existence check skipped: {e}")

    # Resolve coach member ids (the sender is implicit from their token).
    coach_ids: list[int] = []
    for ce in coach_emails:
        if ce == sender_email:
            continue
        m = by_email.get(ce)
        if m and m.get("id"):
            coach_ids.append(int(m["id"]))
        else:
            logger.warning(f"[private-chat] coach {ce} not found in Circle member cache")
    member_ids = coach_ids + [student_mid]

    chat_name = _chat_name(row)
    created = await circle_api.create_group_chat(db_, sender_email, member_ids, chat_name)
    if not created or not created.get("chat_room_uuid"):
        err = (created or {}).get("error") or ""
        status = (created or {}).get("status")
        logger.warning(f"[private-chat] create failed for {student_id} status={status} err={err[:200]}")
        if _looks_like_dms_off(err, status):
            # The student has Circle DMs off - record it so the team chases them
            # (replaces the signal the old Zapier zap used to set). Pinned so the
            # Monday sync won't wipe it.
            now = datetime.now(timezone.utc)
            pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"private_chat_status"})
            await db_.academy_members.update_one({"_id": student_id}, {"$set": {
                "private_chat_status": "Awaiting DMs",
                "dashboard_edited_fields": pinned,
                "dashboard_edited_at": now,
                "dashboard_edited_by": "private-chat-setup",
            }})
            return {"ok": False, "skipped": "awaiting_dms", "detail": err[:200]}
        # Persist the raw failure on the row so it's visible in the dashboard
        # (students-db lookup) instead of buried in Render logs - lets us see
        # Circle's exact rejection and tighten DMs-off detection.
        try:
            await db_.academy_members.update_one({"_id": student_id}, {"$set": {
                "private_chat_last_error": f"{status}: {err}"[:300],
                "private_chat_last_error_at": datetime.now(timezone.utc),
            }})
        except Exception:
            pass
        return {"ok": False,
                "error": f"circle create failed [{status}]: {(err or '(no body)')[:220]}",
                "status": status, "raw": err}

    uuid = created["chat_room_uuid"]
    # TODO verify this URL format against an existing private_chat_url.
    chat_url = f"https://app.circle.so/c/messages/{uuid}"

    now = datetime.now(timezone.utc)
    set_fields: dict = {
        "private_chat_url": chat_url,
        "private_chat_circle_uuid": uuid,
        "private_chat_created_at": now,
        "private_chat_coaches": coach_emails,
        "private_chat_status": "",  # clear any pending note (e.g. "Awaiting DMs")
        "private_chat_last_error": "",  # clear any prior failure note
        "dashboard_edited_at": now,
        "dashboard_edited_by": "private-chat-setup",
    }
    if student_circle_email and not (row.get("circle_email") or "").strip():
        set_fields["circle_email"] = student_circle_email  # the dual-email fix
    pinned = set(row.get("dashboard_edited_fields") or [])
    pinned.update({"private_chat_url"})
    if "circle_email" in set_fields:
        pinned.add("circle_email")
    set_fields["dashboard_edited_fields"] = sorted(pinned)
    await db_.academy_members.update_one({"_id": student_id}, {"$set": set_fields})
    await _bust_gather_cache(db_)  # new chat → invalidate the dedup cache

    # Welcome message - render the tier template (best-effort; a failed post
    # doesn't undo the chat).
    welcome = _render(template, _welcome_context(row))
    posted = await circle_api.post_dm_message(db_, sender_email, uuid, welcome)

    logger.info(f"[private-chat] created chat for {student_id} uuid={uuid} matched_via={via}")
    return {
        "ok": True,
        "id": student_id,
        "chat_room_uuid": uuid,
        "private_chat_url": chat_url,
        "matched_via": via,
        "circle_email_linked": set_fields.get("circle_email"),
        "coaches_added": coach_ids,
        "welcome_posted": bool(posted),
        "raw": created.get("raw"),
    }


_link_scan_started_at = None  # datetime while a scan is in flight, else None


def link_scan_running() -> bool:
    # Time-bounded so a crash/restart mid-scan can't leave it "running" forever.
    if _link_scan_started_at is None:
        return False
    return (datetime.now(timezone.utc) - _link_scan_started_at).total_seconds() < 180


async def link_existing_chats(db_, apply: bool = False) -> dict:
    """Single-flight guard: run at most ONE scan at a time so repeated triggers
    can't pile up and rate-limit Circle. Auto-clears after 180s if something
    leaves the flag set."""
    global _link_scan_started_at
    if link_scan_running():
        return {"ok": False, "error": "a scan is already running - wait ~2 min"}
    _link_scan_started_at = datetime.now(timezone.utc)
    try:
        return await _link_existing_impl(db_, apply=apply)
    finally:
        _link_scan_started_at = None


async def _link_existing_impl(db_, apply: bool = False) -> dict:
    """Find every eligible student who ALREADY has a coach group chat in Circle
    but whose dashboard row has no private_chat_url, and (apply=True) record that
    chat's URL on their row.

    Fixes the backlog of zap-created chats that were never written back to the
    dashboard (the zaps make the Circle chat but don't update the row). Reports
    who got linked and who couldn't be matched, so the residual is the genuine
    'needs a fresh chat / not on Circle' set - not a mystery.
    """
    async def _cache(res: dict) -> dict:
        try:
            await db_.cache.update_one(
                {"_id": "private_chat_link_existing"},
                {"$set": {"cached_at": datetime.now(timezone.utc), "result": res}},
                upsert=True,
            )
        except Exception:
            pass
        return res

    cfg = await settings_store.get_private_chat_config(db_)
    coach_emails = [c["email"] for c in cfg["coaches"] if c.get("email")]
    if not coach_emails:
        return await _cache({"ok": False, "error": "no coach emails configured"})
    # use_cache=True: reuse the recent coach-chats scan instead of hammering
    # Circle on every run (which was getting rate-limited → empty → loop).
    try:
        _ids, _names, coaches_read, chats = await asyncio.wait_for(
            _gather_coach_chats(db_, coach_emails, use_cache=True), timeout=180)
    except asyncio.TimeoutError:
        return await _cache({"ok": False, "error": "Circle read timed out - likely rate-limited; the scheduled run will retry shortly"})
    if not coaches_read:
        return await _cache({"ok": False, "error": "couldn't read any coach group chats (Circle session/rate-limit) - try again in a few minutes"})

    by_email = await _build_email_index()
    linked, not_found = [], []
    already = 0
    now = datetime.now(timezone.utc)

    async for r in db_.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        if not _eligible(r):
            continue
        if (r.get("private_chat_url") or "").strip():
            already += 1
            continue
        # Email-only match (in-memory, fast) - no per-student Circle name_search,
        # which would make this scan time out at the proxy.
        em = (r.get("email") or "").strip().lower()
        cem = (r.get("circle_email") or "").strip().lower()
        member = by_email.get(em) or by_email.get(cem)
        if not member or not member.get("id"):
            not_found.append({"id": r["_id"], "name": r.get("name"), "reason": "not_on_circle"})
            continue
        mid = int(member["id"])
        nm = _norm_name(r.get("name") or "")
        fn = _norm_name(r.get("first_name") or "")
        sn = _norm_name(r.get("surname") or "")
        match = None
        for ch in chats:  # primary: their member id is in the room
            if mid in (ch.get("participant_ids") or []):
                match = ch
                break
        if not match and nm:  # fallback: their name is in the room name
            for ch in chats:
                cn = _norm_name(ch.get("name") or "")
                if (nm and nm in cn) or (fn and sn and fn in cn and sn in cn):
                    match = ch
                    break
        if not match:
            not_found.append({"id": r["_id"], "name": r.get("name"), "reason": "no_matching_chat"})
            continue
        url = f"https://app.circle.so/c/messages/{match.get('uuid')}"
        linked.append({"id": r["_id"], "name": r.get("name"), "url": url, "chat_name": match.get("name")})
        if apply:
            pinned = sorted(set(r.get("dashboard_edited_fields") or []) | {"private_chat_url"})
            await db_.academy_members.update_one({"_id": r["_id"]}, {"$set": {
                "private_chat_url": url,
                "private_chat_circle_uuid": match.get("uuid"),
                "private_chat_status": "",
                "private_chat_last_error": "",
                "dashboard_edited_fields": pinned,
                "dashboard_edited_at": now,
                "dashboard_edited_by": "link-existing-chats",
            }})

    logger.info(f"[private-chat] link-existing: linked={len(linked)} not_found={len(not_found)} apply={apply}")
    return await _cache({
        "ok": True, "applied": apply,
        "coaches_read": coaches_read,
        "counts": {"linked": len(linked), "not_found": len(not_found), "already_had_url": already},
        "linked": linked,
        "not_found": not_found,
    })


def autocreate_enabled() -> bool:
    """The hybrid auto-create job only runs when explicitly enabled - so we can
    cut over deliberately (enable this + turn the Zapier zaps 46/47/53 OFF the
    same day; running both would double-create)."""
    import os
    return os.environ.get("PRIVATE_CHAT_AUTOCREATE_ENABLED", "").strip().lower() == "true"


async def auto_create_ready_chats(db_, limit: int = 25) -> dict:
    """HYBRID auto-create. Creates chats for the clear-cut cases and leaves the
    judgement cases for the team:

      - eligible + on Circle + template set + no existing chat  → CREATE
      - DMs off (create rejected)                               → flag "Awaiting DMs"
      - on Circle but no welcome template for their tier        → report (no create)
      - not matched on Circle (likely dual-email / not joined)  → report (no create)

    Idempotent and guarded - create_for_student re-checks eligibility, existing
    chats across ALL coaches, and dups before creating. `limit` caps creates per
    run so a backlog doesn't fire a huge burst / hit Circle rate limits.
    """
    pv = await preview(db_)
    out = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "config_ready": pv.get("config_ready"),
        "created": [], "awaiting_dms": [], "no_template": [],
        "skipped": [], "errors": [],
        "not_on_circle_count": (pv.get("counts") or {}).get("not_on_circle", 0),
    }
    if not pv.get("config_ready"):
        out["error"] = "coach config incomplete (need coach emails + a sender)"
        return out

    created_n = 0
    for cand in pv.get("ready") or []:
        if not cand.get("has_template"):
            out["no_template"].append({"id": cand["id"], "name": cand.get("name"), "audience": cand.get("audience")})
            continue
        if created_n >= limit:
            out["skipped"].append({"id": cand["id"], "name": cand.get("name"), "reason": "limit_reached"})
            continue
        created_n += 1
        try:
            r = await create_for_student(db_, cand["id"])
            if r.get("ok"):
                out["created"].append({"id": cand["id"], "name": cand.get("name"), "url": r.get("private_chat_url")})
            elif r.get("skipped") == "awaiting_dms":
                out["awaiting_dms"].append({"id": cand["id"], "name": cand.get("name")})
            elif r.get("skipped"):
                out["skipped"].append({"id": cand["id"], "name": cand.get("name"), "reason": r.get("skipped")})
            else:
                out["errors"].append({"id": cand["id"], "name": cand.get("name"), "error": r.get("error")})
        except Exception as e:
            out["errors"].append({"id": cand["id"], "name": cand.get("name"), "error": str(e)[:200]})

    out["summary"] = {
        "created": len(out["created"]),
        "awaiting_dms": len(out["awaiting_dms"]),
        "no_template": len(out["no_template"]),
        "not_on_circle": out["not_on_circle_count"],
        "errors": len(out["errors"]),
    }
    logger.info(f"[private-chat] auto-create: {out['summary']}")
    return out
