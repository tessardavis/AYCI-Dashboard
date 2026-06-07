"""
CRUD over the Academy Members Mongo mirror — the data set that eventually
fully replaces the Monday Academy Members board.

Reads pull from db.academy_members (the 15-min mirror). Writes update the
same row AND mark the edited field in `dashboard_edited_fields` so the
next Monday sync doesn't clobber the change.

Routes:
  GET   /api/students-db                  list, with filters + search
  GET   /api/students-db/{monday_item_id} one row
  PATCH /api/students-db/{monday_item_id} update fields (protected from sync)
  POST  /api/students-db/update-by-email  Zapier-callable lookup+update
                                          (replaces Monday Get Items + Update Item)
  POST  /api/students-db/intake           Zapier-callable upsert for new
                                          signups (Kajabi/Tally/waitlist)
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from db import db
from deps import require_board, require_admin
import webhooks_outbound

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["students-db"])


# CURRENT private products that get set up (private chat + allowance). Used for
# the "needs setup" flag. Deliberately a positive allow-list so deprecated/old
# tiers (Platinum, Academy/Upgrade 1:1, Gold/Platinum Legacy Upgrade) are NOT
# flagged — confirmed with Tessa 2026-06-06.
_CURRENT_PRIVATE_TIERS = {
    "academy private plus", "upgrade private plus",
    "vip", "upgrade vip",
    "boost & go", "boost & go plus",
}


def _is_current_private_tier(tier: Optional[str]) -> bool:
    parts = [p.strip() for p in (tier or "").lower().split(",") if p.strip()]
    return any(p in _CURRENT_PRIVATE_TIERS for p in parts)


def _b_and_g_active(boost: Optional[str]) -> bool:
    """The 'Boost + Go' column carries customer states — B&G / B&G Plus /
    B&G - Presentation / B&G Plus - Presentation, plus 'Upgraded' (they did
    buy B&G; confirmed by Tessa) — and sales-pipeline states (Offer Due/Made/
    Declined) which are NOT paying customers."""
    b = (boost or "").strip().lower()
    return "b&g" in b or b == "upgraded"


# Expected private video allowance per tier / Boost & Go level (Tessa, 2026-06-06).
_VIDEO_ALLOWANCE_BY_TIER = {
    "academy private plus": 15, "upgrade private plus": 15,
    "vip": 30, "upgrade vip": 30,
    "boost & go": 5, "boost & go plus": 10,
}


def expected_video_allowance(tier: Optional[str], boost: Optional[str]) -> Optional[int]:
    """Expected private video allowance, or None if the tier/B&G doesn't have a
    defined allowance (e.g. base Academy, or 1:1/Platinum — not yet specified)."""
    t = (tier or "").strip().lower()
    if t in _VIDEO_ALLOWANCE_BY_TIER:
        return _VIDEO_ALLOWANCE_BY_TIER[t]
    b = (boost or "").strip().lower()
    if "b&g" in b or b == "upgraded":
        return 10 if "plus" in b else 5
    return None


def _is_boss(row: dict) -> bool:
    """Boss Badge = Yes → they've landed their job and are finished working with
    us, so they need no further setup (private chat / allowance)."""
    return (row.get("boss_badge") or "").strip().lower() in {"yes", "true", "1", "y"}


def _allowance_flag(row: dict) -> Optional[str]:
    """'missing' (expected but unset), 'mismatch' (set but ≠ expected),
    'ok', or None (no expected allowance defined, or student is a Boss)."""
    if _is_boss(row):
        return None
    exp = expected_video_allowance(row.get("tier"), row.get("boost_and_go"))
    if exp is None:
        return None
    cur = row.get("video_allowance")
    if cur in (None, ""):
        return "missing"
    try:
        return "ok" if int(cur) == exp else "mismatch"
    except (TypeError, ValueError):
        return "mismatch"


def _needs_private_chat_setup(row: dict) -> bool:
    """True for a private-tier / active Boost & Go student who still needs
    setting up — i.e. missing their private chat link OR missing their video
    allowance. (A wrong-but-present allowance is a 'mismatch', surfaced
    separately, not auto-changed.)"""
    if row.get("setup_not_needed"):
        return False  # manually dismissed — intentionally fine to leave empty
    if _is_boss(row):
        return False  # landed their job — finished with us, no setup needed
    if not (_is_current_private_tier(row.get("tier")) or _b_and_g_active(row.get("boost_and_go"))):
        return False
    no_chat = not (row.get("private_chat_url") or "").strip()
    return no_chat or _allowance_flag(row) == "missing"


def _slim_row_for_list(row: dict) -> dict:
    """Drop heavy fields (full column dicts) from list responses."""
    keep = (
        "_id", "name", "first_name", "surname", "email", "circle_email",
        "tier", "cohort_joined", "interview_date", "speciality", "hospital",
        "interview_type", "private_chat_url", "boost_and_go", "video_allowance",
        "setup_not_needed", "setup_not_needed_reason",
        "url", "synced_at", "dashboard_edited_fields",
    )
    out = {k: row.get(k) for k in keep if k in row}
    out["needs_setup"] = _needs_private_chat_setup(row)
    out["video_allowance_expected"] = expected_video_allowance(row.get("tier"), row.get("boost_and_go"))
    out["allowance_flag"] = _allowance_flag(row)
    return out


@router.get("/students-db")
async def list_students(
    q: Optional[str] = None,
    tier: Optional[str] = None,
    cohort: Optional[str] = None,
    has_interview: Optional[bool] = None,
    limit: int = 500,
    user: dict = Depends(require_board("students")),
):
    """Paginated list of Academy Members rows.

    Filters:
      q              substring match against name + email (case-insensitive)
      tier           exact tier text (e.g. "Platinum"). Mongo regex if you
                     need a prefix-style filter — coaches send full strings
                     today though.
      cohort         exact cohort text (e.g. "April 26")
      has_interview  true → only rows with a non-empty interview_date

    Sorted by interview_date asc (rows with no date last)."""
    query: dict = {}
    if tier:
        query["tier"] = tier
    if cohort:
        query["cohort_joined"] = cohort
    if has_interview is True:
        query["interview_date"] = {"$ne": None, "$exists": True}
    elif has_interview is False:
        query["$or"] = [{"interview_date": None}, {"interview_date": {"$exists": False}}]
    if q:
        rx = {"$regex": q, "$options": "i"}
        # Don't smash the broader query with $or — use $and to keep filters
        existing_or = query.pop("$or", None)
        text_or = [
            {"name": rx},
            {"email": rx},
            {"first_name": rx},
            {"surname": rx},
        ]
        if existing_or:
            query["$and"] = [{"$or": existing_or}, {"$or": text_or}]
        else:
            query["$or"] = text_or

    cursor = (
        db.academy_members
        .find(query, {"columns_by_id": 0, "columns": 0})  # heavy fields excluded
        .sort([("interview_date", 1), ("name", 1)])
        # Cap high enough to return the whole board in one page — the slim
        # projection keeps rows small. The old 2000 cap silently dropped
        # students past it (board is ~2.1k), so they couldn't be searched.
        .limit(min(limit, 10000))
    )
    # How many private videos each student has actually submitted (their
    # "used" count) — one aggregation over the submissions collection, keyed by
    # the (lowercased) email it was submitted under.
    used_counts: dict[str, int] = {}
    try:
        async for g in db.private_video_submissions.aggregate(
            [{"$group": {"_id": "$email", "n": {"$sum": 1}}}]
        ):
            em = (g.get("_id") or "")
            if em:
                used_counts[str(em).strip().lower()] = g.get("n", 0)
    except Exception as e:
        logger.info(f"[students-db] videos-used aggregate skipped: {e}")

    rows = []
    async for r in cursor:
        slim = _slim_row_for_list(r)
        em = (r.get("email") or "").strip().lower()
        ce = (r.get("circle_email") or "").strip().lower()
        slim["videos_used"] = used_counts.get(em) or used_counts.get(ce) or 0
        rows.append(slim)
    return {"items": rows, "count": len(rows)}


# Declared BEFORE /students-db/{monday_item_id} so the static paths aren't
# shadowed by the id route (Starlette matches in declaration order).
@router.get("/students-db/allowance-audit")
async def allowance_audit(user: dict = Depends(require_board("students"))):
    """Private/B&G students whose video allowance is MISSING or MISMATCHED vs
    the expected per-tier value (PP 15, VIP 30, B&G 5, B&G Plus 10)."""
    missing, mismatch = [], []
    async for r in db.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        flag = _allowance_flag(r)
        if flag not in ("missing", "mismatch"):
            continue
        entry = {
            "id": r["_id"], "name": r.get("name"), "email": r.get("email"),
            "tier": r.get("tier"), "boost_and_go": r.get("boost_and_go"),
            "current": r.get("video_allowance"),
            "expected": expected_video_allowance(r.get("tier"), r.get("boost_and_go")),
        }
        (missing if flag == "missing" else mismatch).append(entry)
    missing.sort(key=lambda x: (x.get("name") or ""))
    mismatch.sort(key=lambda x: (x.get("name") or ""))
    return {"missing": missing, "mismatch": mismatch,
            "counts": {"missing": len(missing), "mismatch": len(mismatch)}}


@router.post("/students-db/apply-expected-allowances")
async def apply_expected_allowances(user: dict = Depends(require_board("students"))):
    """Set video_allowance = expected for every student whose allowance is
    MISSING (only). Never overwrites a present value — mismatches are left for
    review. Pins video_allowance as dashboard-owned so the sync won't clobber."""
    now = datetime.now(timezone.utc)
    applied = []
    async for r in db.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        if _allowance_flag(r) != "missing":
            continue
        exp = expected_video_allowance(r.get("tier"), r.get("boost_and_go"))
        if exp is None:
            continue
        new_protected = sorted(set(r.get("dashboard_edited_fields") or []) | {"video_allowance"})
        await db.academy_members.update_one(
            {"_id": r["_id"]},
            {"$set": {
                "video_allowance": exp,
                "dashboard_edited_fields": new_protected,
                "dashboard_edited_at": now,
                "dashboard_edited_by": user.get("email") or "dashboard",
            }},
        )
        applied.append({"id": r["_id"], "name": r.get("name"), "set_to": exp})
    return {"ok": True, "set": len(applied), "applied": applied[:300]}


@router.post("/students-db/revert-applied-allowances")
async def revert_applied_allowances(user: dict = Depends(require_board("students"))):
    """Undo a recent apply-expected-allowances: for rows this user set in the
    last 6h where video_allowance still equals the expected value, clear it
    back to empty and un-pin it (so it shows as 'missing' again, exactly as
    before). Only touches the auto-applied ones — never manual edits to other
    values."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    actor = user.get("email") or user.get("id")
    now = datetime.now(timezone.utc)
    reverted = []
    async for r in db.academy_members.find(
        {"dashboard_edited_fields": "video_allowance"},
        {"columns": 0, "columns_by_id": 0},
    ):
        ea = r.get("dashboard_edited_at")
        if not isinstance(ea, datetime):
            continue
        if ea.tzinfo is None:
            ea = ea.replace(tzinfo=timezone.utc)
        if ea < cutoff or (r.get("dashboard_edited_by") != actor):
            continue
        exp = expected_video_allowance(r.get("tier"), r.get("boost_and_go"))
        if exp is None or r.get("video_allowance") != exp:
            continue  # not an untouched auto-applied value — leave it
        new_protected = sorted(set(r.get("dashboard_edited_fields") or []) - {"video_allowance"})
        await db.academy_members.update_one(
            {"_id": r["_id"]},
            {"$set": {
                "video_allowance": None,
                "dashboard_edited_fields": new_protected,
                "dashboard_edited_at": now,
                "dashboard_edited_by": actor,
            }},
        )
        reverted.append({"id": r["_id"], "name": r.get("name"), "was": exp})
    return {"ok": True, "reverted": len(reverted), "items": reverted[:300]}


@router.get("/students-db/{monday_item_id}")
async def get_student(
    monday_item_id: str,
    user: dict = Depends(require_board("students")),
):
    """Full row including the columns dict (used by Student Lookup-style
    full-detail views)."""
    row = await db.academy_members.find_one({"_id": monday_item_id})
    if not row:
        raise HTTPException(404, "Student not found in academy_members mirror")
    return row


# Editable fields from the dashboard. Anything outside this list returns
# a 400 — explicit allowlist prevents accidental edits to fields that
# upstream automations control (e.g. someone PATCHing video_allowance
# when Stripe is supposed to own that).
EDITABLE_FIELDS = {
    "name", "first_name", "surname", "email", "circle_email",
    "tier", "cohort_joined", "interview_date", "speciality", "hospital",
    "interview_type", "private_chat_url", "video_allowance",
    "setup_not_needed", "setup_not_needed_reason",
}


class StudentPatch(BaseModel):
    """Each call PATCHes a small subset of fields. Any field present is
    treated as an edit — set explicitly to `null` to clear it."""
    name: Optional[str] = None
    first_name: Optional[str] = None
    surname: Optional[str] = None
    email: Optional[str] = None
    circle_email: Optional[str] = None
    tier: Optional[str] = None
    cohort_joined: Optional[str] = None
    interview_date: Optional[str] = None  # ISO yyyy-mm-dd
    speciality: Optional[str] = None
    hospital: Optional[str] = None
    interview_type: Optional[str] = None
    private_chat_url: Optional[str] = None
    video_allowance: Optional[int] = None
    setup_not_needed: Optional[bool] = None
    setup_not_needed_reason: Optional[str] = None

    class Config:
        extra = "forbid"  # reject unknown keys outright


@router.patch("/students-db/{monday_item_id}")
async def update_student(
    monday_item_id: str,
    patch: StudentPatch,
    user: dict = Depends(require_board("students")),
):
    """Update one or more fields on a student row. Edited fields get
    added to `dashboard_edited_fields` so the next 15-min Monday sync
    doesn't overwrite the change."""
    # Only consider fields the caller explicitly set (not Pydantic defaults)
    set_fields = patch.dict(exclude_unset=True)
    if not set_fields:
        raise HTTPException(400, "No fields to update")

    # Allowlist guard (also covered by Pydantic extra=forbid, but defensive)
    bad = set(set_fields.keys()) - EDITABLE_FIELDS
    if bad:
        raise HTTPException(400, f"Fields not editable here: {sorted(bad)}")

    existing = await db.academy_members.find_one({"_id": monday_item_id})
    if not existing:
        raise HTTPException(404, "Student not found in academy_members mirror")

    # Normalise email-ish fields to lowercase (matches the sync logic)
    for k in ("email", "circle_email"):
        if k in set_fields and set_fields[k] is not None:
            set_fields[k] = set_fields[k].strip().lower() or None

    now = datetime.now(timezone.utc)
    update_set: dict[str, Any] = dict(set_fields)
    update_set["dashboard_edited_at"] = now
    update_set["dashboard_edited_by"] = user.get("email") or user.get("id")

    # Union the existing protected-fields list with the newly edited ones.
    new_protected = set(existing.get("dashboard_edited_fields") or [])
    new_protected.update(set_fields.keys())
    update_set["dashboard_edited_fields"] = sorted(new_protected)

    await db.academy_members.update_one(
        {"_id": monday_item_id}, {"$set": update_set}
    )

    fresh = await db.academy_members.find_one({"_id": monday_item_id})

    # Outbound webhook fan-out — fire only for columns whose value actually
    # changed (skip no-op writes). Fire-and-forget so the response isn't
    # blocked on downstream zaps.
    diff = webhooks_outbound.changed_fields_diff(existing, set_fields)
    if diff:
        asyncio.create_task(
            webhooks_outbound.notify_column_changes(
                db, item_id=monday_item_id, fields_changed=diff, student=fresh,
            )
        )

    return fresh


# ----------------------------------------------------- Zapier-callable update
# Replaces the Monday "Get Items by Column Value + Update Item" pair used by
# ~40 zaps. Zap re-point: swap both Monday steps for one Webhooks-by-Zapier
# POST to this endpoint with the email + fields to change.
#
# Auth: shared secret in `X-Webhook-Secret`. Set ZAPIER_WEBHOOK_SECRET on
# Render and paste the same string into each zap's Webhooks step header.

def _check_webhook_secret(x_webhook_secret: Optional[str]) -> None:
    expected = (os.environ.get("ZAPIER_WEBHOOK_SECRET") or "").strip()
    if not expected:
        raise HTTPException(503, "Webhook auth not configured")
    if (x_webhook_secret or "").strip() != expected:
        raise HTTPException(401, "Invalid webhook secret")


def _parse_email_and_fields(body: dict) -> tuple[str, dict]:
    """Accept both nested and flat payload shapes so the Zapier Webhooks
    step is easy to configure:

      Nested (what Postman / a hand-written client sends):
        {"email": "x@y.z", "fields": {"milestone_1": "Yes"}}

      Flat (what's natural in Zapier's key/value UI):
        {"email": "x@y.z", "milestone_1": "Yes"}

    Returns (email, fields_dict)."""
    if not isinstance(body, dict):
        raise HTTPException(400, "payload must be an object")
    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(400, "email is required")
    nested = body.get("fields")
    if isinstance(nested, dict) and nested:
        return email, nested
    # Flat mode: everything except `email` and a small set of reserved
    # top-level keys is treated as a field to set.
    reserved = {"email", "source"}
    flat = {k: v for k, v in body.items() if k not in reserved}
    if not flat:
        raise HTTPException(400, "fields must be non-empty")
    return email, flat


@router.post("/students-db/update-by-email")
async def update_student_by_email(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Find a student by email (or circle_email) and update fields.

    Returns 404 if no match — zaps' existing Slack-alert fallback paths
    can branch on that response. Returns 400 if any field is not in the
    automation allowlist."""
    _check_webhook_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    email, fields = _parse_email_and_fields(body)
    email_l = email.strip().lower()

    bad = set(fields.keys()) - PROTECTED_FIELDS
    if bad:
        raise HTTPException(
            400, f"Fields not writable by automation: {sorted(bad)}"
        )

    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
    )
    if not row:
        # Surface as 404 so the zap's existing not-found branch fires.
        raise HTTPException(404, f"No student found for email={email_l}")

    set_fields: dict[str, Any] = dict(fields)
    # Normalise email-ish fields (matches PATCH + mirror behaviour)
    for k in ("email", "circle_email"):
        if k in set_fields and set_fields[k] is not None:
            set_fields[k] = str(set_fields[k]).strip().lower() or None

    # Capture the pre-write values for read-modify-write callers (Zapier
    # filter steps that need the prior value). Empty string for fields not
    # previously set, since Zapier filters treat null awkwardly.
    previous_values = {k: (row.get(k) if row.get(k) is not None else "") for k in set_fields.keys()}

    now = datetime.now(timezone.utc)
    update_set: dict[str, Any] = dict(set_fields)
    update_set["dashboard_edited_at"] = now
    update_set["dashboard_edited_by"] = "zapier"

    new_protected = set(row.get("dashboard_edited_fields") or [])
    new_protected.update(set_fields.keys())
    update_set["dashboard_edited_fields"] = sorted(new_protected)

    await db.academy_members.update_one(
        {"_id": row["_id"]}, {"$set": update_set}
    )
    logger.info(
        f"[students-db] zapier update email={email_l} "
        f"id={row['_id']} fields={list(set_fields.keys())}"
    )

    # Outbound webhook fan-out — diff vs the pre-write row.
    diff = webhooks_outbound.changed_fields_diff(row, set_fields)
    if diff:
        fresh = await db.academy_members.find_one({"_id": row["_id"]})
        asyncio.create_task(
            webhooks_outbound.notify_column_changes(
                db, item_id=row["_id"], fields_changed=diff, student=fresh or row,
            )
        )

    return {
        "ok": True,
        "id": row["_id"],
        "matched_on": "email" if row.get("email") == email_l else "circle_email",
        "updated_fields": sorted(set_fields.keys()),
        "previous_values": previous_values,
    }


# --------------------------------------------- Zapier-callable 1:1 call booking
# Replaces the "1:1 Round Robin" zaps' AI-by-Zapier step that worked out which
# Call slot (1-4) a new booking should fill. The four Call columns on Monday
# are status columns sharing the label set:
#   Eligible | Booked | Booked - Becky | Booked - Tessa
#   Booked - Anoop | Booked - Charlotte
# Rule (confirmed 2026-06-04): fill the lowest-numbered slot whose current
# value is NOT already "Booked..." (i.e. Eligible or blank), with
# "Booked - <Coach>". If all four are booked, write nothing and return
# slot=null so the zap's existing Fallback (Slack alert) path can fire.

# Coaches with a dedicated "Booked - X" status label. Lowercased key → label.
_CALL_COACHES = {
    "becky": "Becky",
    "tessa": "Tessa",
    "anoop": "Anoop",
    "charlotte": "Charlotte",
}


def _current_call_slot(row: dict, n: int) -> str:
    """Current value of Call slot n for this row.

    Prefers the dashboard-owned scalar `call_n`; falls back to the Monday
    column dump (`columns["Call n"].text`) so the rule works during the
    safety-net week before the dashboard owns the field. "" if unset."""
    scalar = row.get(f"call_{n}")
    if scalar is not None:
        return str(scalar)
    entry = (row.get("columns") or {}).get(f"Call {n}")
    if isinstance(entry, dict):
        return entry.get("text") or ""
    return ""


@router.post("/students-db/book-call")
async def book_call(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Mark a student's next available 1:1 call slot as booked with a coach.

    Body: {"email": "x@y.z", "coach": "Anoop"}

    Returns the slot filled (1-4) and the value written, or slot=null with
    reason="all_slots_booked" when every slot is already taken. 404 if no
    student matches the email."""
    _check_webhook_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    if not isinstance(body, dict):
        raise HTTPException(400, "payload must be an object")
    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(400, "email is required")
    coach_raw = body.get("coach")
    if not isinstance(coach_raw, str) or not coach_raw.strip():
        raise HTTPException(400, "coach is required")
    coach = _CALL_COACHES.get(coach_raw.strip().lower())
    if not coach:
        raise HTTPException(
            400, f"coach must be one of: {sorted(_CALL_COACHES.values())}"
        )
    email_l = email.strip().lower()

    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
    )
    if not row:
        raise HTTPException(404, f"No student found for email={email_l}")

    matched_on = "email" if row.get("email") == email_l else "circle_email"

    # Lowest-numbered slot not already "Booked..." (Eligible or blank).
    slot = None
    for n in (1, 2, 3, 4):
        if not _current_call_slot(row, n).strip().startswith("Booked"):
            slot = n
            break

    if slot is None:
        logger.info(
            f"[students-db] book-call all slots full email={email_l} id={row['_id']}"
        )
        return {
            "ok": True,
            "id": row["_id"],
            "matched_on": matched_on,
            "slot": None,
            "reason": "all_slots_booked",
        }

    field = f"call_{slot}"
    value = f"Booked - {coach}"
    previous_value = _current_call_slot(row, slot)

    now = datetime.now(timezone.utc)
    new_protected = set(row.get("dashboard_edited_fields") or [])
    new_protected.add(field)
    await db.academy_members.update_one(
        {"_id": row["_id"]},
        {"$set": {
            field: value,
            "dashboard_edited_at": now,
            "dashboard_edited_by": "zapier",
            "dashboard_edited_fields": sorted(new_protected),
        }},
    )
    logger.info(
        f"[students-db] book-call email={email_l} id={row['_id']} "
        f"{field}={value!r} (was {previous_value!r})"
    )

    # Outbound webhook fan-out if the slot value actually changed.
    diff = webhooks_outbound.changed_fields_diff(row, {field: value})
    if diff:
        fresh = await db.academy_members.find_one({"_id": row["_id"]})
        asyncio.create_task(
            webhooks_outbound.notify_column_changes(
                db, item_id=row["_id"], fields_changed=diff, student=fresh or row,
            )
        )

    return {
        "ok": True,
        "id": row["_id"],
        "matched_on": matched_on,
        "slot": slot,
        "field": field,
        "value": value,
        "previous_value": previous_value if previous_value else "",
    }


# ------------------------------------------------- Zapier-callable read/lookup
# The read counterpart to update-by-email. Replaces a Monday "Get Items by
# Column Value + Get Column Values" pair when a zap needs to READ current
# state before deciding what to write (e.g. the 1:1 Round Robin AI step that
# picks which call slot to fill). Writes nothing.

# Heavy fields never returned to a webhook caller — the full Monday column
# dumps are large and not useful to a zap.
_HEAVY_FIELDS = {"columns", "columns_by_id"}


@router.post("/students-db/lookup-by-email")
async def lookup_student_by_email(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Find a student by email (or circle_email) and return their fields.

    Body:
      {"email": "x@y.z"}                              scalar fields only
      {"email": "x@y.z", "columns": ["1:1 Call 1"]}   also pull these Monday
                                                       column titles by text

    Returns the row's scalar fields (heavy Monday column dumps excluded).
    For each title in `columns`, the current Monday text value is returned
    under `columns[title]` — lets a zap read a column the mirror doesn't
    promote to a scalar yet (e.g. call slots) during the safety-net week.

    404 on no match, mirroring update-by-email so a zap's existing
    not-found branch fires the same way."""
    _check_webhook_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    if not isinstance(body, dict):
        raise HTTPException(400, "payload must be an object")
    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(400, "email is required")
    email_l = email.strip().lower()

    requested_cols = body.get("columns") or []
    if not isinstance(requested_cols, list):
        raise HTTPException(400, "columns must be a list of Monday column titles")

    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
    )
    if not row:
        raise HTTPException(404, f"No student found for email={email_l}")

    fields = {
        k: v for k, v in row.items()
        if k not in _HEAVY_FIELDS and not isinstance(v, datetime)
    }

    # Pull requested Monday columns by title from the stored dump. Each entry
    # is {"text":..., "type":...}; return the text. "" for a missing title or
    # empty value so a zap filter sees an empty string, not null.
    col_titles = row.get("columns") or {}

    def _col_text(title: str) -> str:
        entry = col_titles.get(title)
        if not isinstance(entry, dict):
            return ""
        return entry.get("text") or ""

    columns_out = {str(title): _col_text(title) for title in requested_cols}

    return {
        "ok": True,
        "id": row["_id"],
        "matched_on": "email" if row.get("email") == email_l else "circle_email",
        "fields": fields,
        "columns": columns_out,
    }


# --------------------------------------------------- Toolkit access check
# Read endpoint for the toolkit site (tools.medicalinterviewprep.com et al.)
# to gate material access by Kajabi add-on purchase. The dashboard is the
# source of truth: the Kajabi purchase-capture zap sets the addon_* fields
# "Yes" via update-by-email; this endpoint reads them back by email.
#
# Maps each access key (what the toolkit site asks about) to the dashboard
# field. Add new add-ons here + in PROTECTED_FIELDS.
TOOLKIT_ADDONS = {
    "curveball_questions": "addon_curveball_questions",      # £47 order bump (Kajabi 2151209227, Circle delivery)
    "question_sets": "addon_question_sets",                  # 30 Recent Question Sets upsell (Kajabi 2151209222)
    "pre_interview_toolkit": "addon_pre_interview_toolkit",  # £97 upsell (Kajabi 2151209231, tools.medicalinterviewprep.com)
}


def _addon_on(value: Any) -> bool:
    """An add-on flag counts as purchased when set to an affirmative value."""
    return str(value or "").strip().lower() in {"yes", "true", "1", "y"}


@router.post("/toolkit/access")
async def toolkit_access(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Return which add-ons a student has purchased, by email.

    Body: {"email": "x@y.z"}
    Auth: X-Webhook-Secret (set TOOLKIT_ACCESS_SECRET on Render to use a
    dedicated secret; otherwise falls back to ZAPIER_WEBHOOK_SECRET).

    Always 200 (never 404) so the toolkit site gets a clean allow/deny:
      { "found": true/false,
        "access": { "curveball_questions": bool, "question_sets": bool,
                    "pre_interview_toolkit": bool } }
    A non-existent student returns found=false with all access false."""
    _check_toolkit_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    if not isinstance(body, dict):
        raise HTTPException(400, "payload must be an object")
    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(400, "email is required")
    email_l = email.strip().lower()

    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
        {"_id": 1, **{f: 1 for f in TOOLKIT_ADDONS.values()}},
    )
    if not row:
        return {
            "email": email_l,
            "found": False,
            "access": {k: False for k in TOOLKIT_ADDONS},
        }
    return {
        "email": email_l,
        "found": True,
        "id": row["_id"],
        "access": {k: _addon_on(row.get(field)) for k, field in TOOLKIT_ADDONS.items()},
    }


def _check_toolkit_secret(x_webhook_secret: Optional[str]) -> None:
    """Accept a dedicated TOOLKIT_ACCESS_SECRET if configured, else fall back
    to the shared ZAPIER_WEBHOOK_SECRET."""
    toolkit = (os.environ.get("TOOLKIT_ACCESS_SECRET") or "").strip()
    if toolkit:
        if (x_webhook_secret or "").strip() == toolkit:
            return
        raise HTTPException(401, "Invalid toolkit secret")
    _check_webhook_secret(x_webhook_secret)


# Re-export so the webhook endpoint can use the same allowlist as the sync.
# Imported lazily to avoid a module-load cycle.
def _protected_fields_set() -> set[str]:
    try:
        from academy_members_mirror import PROTECTED_FIELDS as _PF
        return set(_PF)
    except Exception:
        return EDITABLE_FIELDS

PROTECTED_FIELDS = _protected_fields_set()


# --------------------------------------------------- Zapier-callable intake
# Replaces Monday "Create Item" for new student signups (Kajabi purchases,
# Tally onboarding, waitlist registrations). Upserts on email: existing
# academy_members row → update tier + provided fields; otherwise insert
# a new row with _id="auto:<uuid>".

# Extra fields the intake endpoint can set on a row in addition to the
# normal scalar columns. Tracked so we know who/what created the row.
INTAKE_ONLY_FIELDS = {"stage", "source", "intake_payload_meta"}


@router.post("/students-db/intake")
async def intake_student(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Upsert a student row by email.

    Behaviour:
      - email matches an existing row (by email OR circle_email): update
        the allowlisted fields, preserve dashboard_edited_fields audit
        trail, return action="updated".
      - no match: insert a new row with _id="auto:<uuid>", marked
        synced_from_monday=False so the 15-min Monday sync leaves it alone.
        Return action="created".

    The endpoint deliberately does NOT branch on offer name or do tier
    lookups itself — the zap (or future intake-routing logic) supplies
    `fields.tier` directly. Keeps this endpoint a thin primitive.

    Accepts both nested (`{email, fields:{...}, source}`) and flat
    (`{email, tier, cohort_joined, ..., source}`) payload shapes."""
    _check_webhook_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    email, fields = _parse_email_and_fields(body)
    email_l = email.strip().lower()
    source = body.get("source")

    allowed = PROTECTED_FIELDS | INTAKE_ONLY_FIELDS
    bad = set(fields.keys()) - allowed
    if bad:
        raise HTTPException(
            400, f"Fields not writable by intake: {sorted(bad)}"
        )

    set_fields: dict[str, Any] = dict(fields)
    # Normalise email-ish fields (matches PATCH + mirror behaviour)
    for k in ("email", "circle_email"):
        if k in set_fields and set_fields[k] is not None:
            set_fields[k] = str(set_fields[k]).strip().lower() or None

    # Always carry the lookup email and source through to the row
    set_fields.setdefault("email", email_l)
    if source:
        set_fields["source"] = source

    existing = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
        {"_id": 1, "dashboard_edited_fields": 1},
    )

    now = datetime.now(timezone.utc)
    update_set: dict[str, Any] = dict(set_fields)
    update_set["dashboard_edited_at"] = now
    update_set["dashboard_edited_by"] = "zapier-intake"

    if existing:
        # Update — preserve dashboard_edited_fields audit
        new_protected = set(existing.get("dashboard_edited_fields") or [])
        # Only the scalar columns go in the protected set, not the
        # intake-only metadata fields.
        new_protected.update(set(set_fields.keys()) & PROTECTED_FIELDS)
        update_set["dashboard_edited_fields"] = sorted(new_protected)
        await db.academy_members.update_one(
            {"_id": existing["_id"]}, {"$set": update_set}
        )
        logger.info(
            f"[students-db] zapier intake updated email={email_l} "
            f"id={existing['_id']} fields={list(set_fields.keys())}"
        )
        return {
            "ok": True,
            "id": existing["_id"],
            "action": "updated",
            "fields": sorted(set_fields.keys()),
        }

    # Insert — new row with dashboard-generated id
    new_id = f"auto:{uuid.uuid4()}"
    insert_doc: dict[str, Any] = dict(set_fields)
    insert_doc["_id"] = new_id
    insert_doc["synced_from_monday"] = False
    insert_doc["created_at"] = now
    insert_doc["dashboard_edited_at"] = now
    insert_doc["dashboard_edited_by"] = "zapier-intake"
    insert_doc["dashboard_edited_fields"] = sorted(
        set(set_fields.keys()) & PROTECTED_FIELDS
    )
    await db.academy_members.insert_one(insert_doc)
    logger.info(
        f"[students-db] zapier intake created email={email_l} "
        f"id={new_id} fields={list(set_fields.keys())}"
    )

    # Outbound webhook fan-out for the new row's initial columns (treats
    # the insert as a transition from "didn't exist" to "exists with these
    # values", so subscribed downstream zaps fire on cohort assignment etc).
    diff = {k: v for k, v in set_fields.items() if k in PROTECTED_FIELDS}
    if diff:
        asyncio.create_task(
            webhooks_outbound.notify_column_changes(
                db, item_id=new_id, fields_changed=diff, student=insert_doc,
            )
        )

    return {
        "ok": True,
        "id": new_id,
        "action": "created",
        "fields": sorted(set_fields.keys()),
    }


# ----------------------------------------------- Webhook subscription admin
# Manage the subscribers that listen for column-change events. Authenticated
# (dashboard user only) — these are equivalent to changing a Monday zap
# trigger.
#
# NOTE: these live under /api/webhook-subscriptions, NOT /api/students-db/...,
# deliberately. A single-segment path like /students-db/webhook-subscriptions
# is shadowed by the GET /students-db/{monday_item_id} route declared above
# (Starlette matches in declaration order), so it would 404 as "student not
# found". A separate prefix sidesteps that.

class WebhookSubscriptionCreate(BaseModel):
    name: str
    column: str
    url: str
    active: bool = True

    class Config:
        extra = "forbid"


def _serialise_subscription(doc: dict) -> dict:
    """Drop Mongo's _id and render datetimes as ISO strings for the UI."""
    out = {k: v for k, v in doc.items() if k != "_id"}
    ca = out.get("created_at")
    if isinstance(ca, datetime):
        out["created_at"] = ca.isoformat()
    return out


@router.get("/webhook-subscriptions/columns")
async def list_webhook_columns(
    user: dict = Depends(require_admin),
):
    """The columns a subscription may listen on — the automation-writable
    field allowlist (PROTECTED_FIELDS). Populates the create-form dropdown."""
    return {"columns": sorted(PROTECTED_FIELDS)}


@router.get("/webhook-subscriptions")
async def list_webhook_subscriptions(
    user: dict = Depends(require_admin),
):
    cursor = db.dashboard_webhook_subscriptions.find({})
    items = [_serialise_subscription(s) async for s in cursor]
    items.sort(key=lambda s: (s.get("column", ""), s.get("name", "")))
    return {"items": items, "count": len(items)}


@router.post("/webhook-subscriptions")
async def create_webhook_subscription(
    payload: WebhookSubscriptionCreate,
    user: dict = Depends(require_admin),
):
    if payload.column not in PROTECTED_FIELDS:
        raise HTTPException(
            400,
            f"column must be one of: {sorted(PROTECTED_FIELDS)}",
        )
    if not payload.url.startswith("https://"):
        raise HTTPException(400, "url must be https://")
    doc = {
        "id": str(uuid.uuid4()),
        "name": payload.name.strip(),
        "column": payload.column,
        "url": payload.url.strip(),
        "active": payload.active,
        "created_at": datetime.now(timezone.utc),
        "created_by": user.get("email") or user.get("id"),
    }
    await db.dashboard_webhook_subscriptions.insert_one(doc)
    return _serialise_subscription(doc)


@router.delete("/webhook-subscriptions/{sub_id}")
async def delete_webhook_subscription(
    sub_id: str,
    user: dict = Depends(require_admin),
):
    res = await db.dashboard_webhook_subscriptions.delete_one({"id": sub_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Subscription not found")
    return {"ok": True}
