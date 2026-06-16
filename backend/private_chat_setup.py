"""
Dashboard-native private-chat creation — Route 2, Phase 0.

See PRIVATE_CHAT_MIGRATION.md. Replaces the Monday-triggered "Private Chat …
when they join Circle" zaps (46/47/53/54). Phase 0 is MANUAL: a dry-run
`preview()` (no writes) and a per-student `create_for_student()` behind an
explicit admin click — nothing runs on a schedule yet.

Key win over the zaps: we match the student to their Circle identity on EITHER
email (or a strong name match), so students who joined Circle under a different
email than they signed up with on Kajabi no longer silently fall through.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from db import db
import settings_store
import circle_api
import student_lookup

logger = logging.getLogger(__name__)


def _eligible(row: dict) -> bool:
    """Same population the 'needs setup' flag cares about — current private
    tier / active B&G, not a Boss, not setup-dismissed. (Predicates live in
    routes.students_db; imported lazily to avoid an import cycle.)"""
    from routes.students_db import (
        _is_current_private_tier, _b_and_g_active, _is_boss,
    )
    if row.get("setup_not_needed") or _is_boss(row):
        return False
    return _is_current_private_tier(row.get("tier")) or _b_and_g_active(row.get("boost_and_go"))


async def _match_circle_member(row: dict, by_email: dict) -> tuple[Optional[dict], Optional[str]]:
    """Find the student's Circle member via email/circle_email (exact) or a
    strong fuzzy name match. Returns (member, matched_via) or (None, None)."""
    for key in ("email", "circle_email"):
        e = (row.get(key) or "").strip().lower()
        if e and e in by_email:
            return by_email[e], key
    name = (row.get("name") or "").strip()
    if name:
        hits = await student_lookup.name_search(db, name, limit=1)
        top = hits[0] if hits else None
        if top and (top.get("match_score") or 0) >= 80 and (top.get("email") or "").strip():
            # name_search returns slim hits without id — re-resolve from the cache
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
    """Dry run — who WOULD get a chat, and whether we can resolve them on
    Circle. Writes nothing."""
    cfg = await settings_store.get_private_chat_config(db_)
    coaches_with_email = [c for c in cfg["coaches"] if c.get("email")]
    config_ready = bool(coaches_with_email) and bool(cfg.get("sender_email"))
    templates = cfg.get("welcome_templates") or {}

    by_email = await _build_email_index()
    ready, not_on_circle = [], []

    async for r in db_.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        if not _eligible(r):
            continue
        if (r.get("private_chat_url") or "").strip():
            continue  # already has a chat — never touch
        member, via = await _match_circle_member(r, by_email)
        base = {
            "id": r["_id"],
            "name": r.get("name"),
            "tier": r.get("tier"),
            "boost_and_go": r.get("boost_and_go"),
            "kajabi_email": (r.get("email") or "").strip().lower() or None,
        }
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
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "config_ready": config_ready,
        "coaches": cfg["coaches"],
        "sender_email": cfg.get("sender_email"),
        "counts": {"ready": len(ready), "not_on_circle": len(not_on_circle)},
        "ready": ready,
        "not_on_circle": not_on_circle,
    }


def _norm_name(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", (s or "").lower())).strip()


async def _gather_coach_chats(db_, coach_emails: list) -> tuple:
    """Union of every coach's Circle group chats → (member_ids set, names list,
    coaches_read list). Reading ALL coaches (not just the sender) is essential:
    historical chats were created by Oksana and the go-forward sender (Coralie)
    isn't in them, but the other coaches (Becky/Tessa) are — so this is how we
    detect an existing chat and never spawn a duplicate."""
    member_ids: set = set()
    names: list = []
    coaches_read: list = []
    for ce in coach_emails:
        chats = await circle_api.list_group_chats(db_, ce)
        if not chats:
            continue
        coaches_read.append({"email": ce, "chats": len(chats)})
        for ch in chats:
            member_ids.update(ch.get("participant_ids") or [])
            names.append(_norm_name(ch.get("name") or ""))
    return member_ids, names, coaches_read


async def no_chat_audit(db_) -> dict:
    """Reconciliation audit: current private-tier students who have NO coach
    group chat in Circle. More accurate than the `private_chat_url` field
    because it checks Circle directly — catches students with a *dead* URL too
    (e.g. a chat that "succeeded" in the zap but the student has DMs off).

    Lists a resident coach's group chats (every private chat includes the
    coaches), then flags eligible students not present in any of them. The
    cause isn't necessarily DMs-off (could be dual-email or never-created) —
    DMs-off is confirmed when chat creation is attempted and fails.

    Read-only. Best-effort matching: by Circle member id (authoritative) with a
    fall-back to chat-room name, since participant previews can be truncated.
    """
    cfg = await settings_store.get_private_chat_config(db_)
    coach_emails = [c["email"] for c in cfg["coaches"] if c.get("email")]
    if not coach_emails:
        return {"ok": False, "error": "Set at least one coach's Circle email in Private chat setup first."}

    # Union every coach's group chats (see _gather_coach_chats) — survives a
    # coach whose session can't be minted and covers historical Oksana chats.
    chat_member_ids, chat_names, coaches_read = await _gather_coach_chats(db_, coach_emails)
    if not coaches_read:
        return {"ok": False, "error": (
            "Couldn't read any coach's Circle group chats. The Circle parent "
            "token can only mint a session for coaches who are admins/moderators "
            "— check that at least one configured coach has those rights."
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


async def create_for_student(db_, student_id: str) -> dict:
    """Create ONE student's coach group chat. Heavily guarded against
    duplicates (Circle can't mutate a room's roster, so a wrong call makes a
    confusing second chat). Returns a diagnostic dict — `raw` carries Circle's
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

    # Resolve the welcome template for this student's audience up-front — refuse
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
    # with this student? Critically checks all coaches, not just the sender —
    # historical chats were made by Oksana and Coralie (the sender) isn't in
    # them, so a sender-only check would miss them and spawn a duplicate chat
    # (→ a new thread, splitting the student's video replies). Matches by member
    # id, with a chat-name fallback for truncated participant previews.
    try:
        all_coach_emails = [c["email"] for c in cfg["coaches"] if c.get("email")]
        existing_ids, existing_names, _ = await _gather_coach_chats(db_, all_coach_emails)
        nm = _norm_name(row.get("name") or "")
        if student_mid in existing_ids or (nm and any(nm in cn for cn in existing_names)):
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
        return {"ok": False, "error": "circle group-chat create failed", "raw": (created or {}).get("raw")}

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

    # Welcome message — render the tier template (best-effort; a failed post
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
