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

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from db import db
from deps import require_board

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["students-db"])


def _slim_row_for_list(row: dict) -> dict:
    """Drop heavy fields (full column dicts) from list responses."""
    keep = (
        "_id", "name", "first_name", "surname", "email", "circle_email",
        "tier", "cohort_joined", "interview_date", "speciality", "hospital",
        "interview_type", "url", "synced_at", "dashboard_edited_fields",
    )
    return {k: row.get(k) for k in keep if k in row}


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
        .limit(min(limit, 2000))
    )
    rows = [_slim_row_for_list(r) async for r in cursor]
    return {"items": rows, "count": len(rows)}


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
    "interview_type", "private_chat_url",
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

    existing = await db.academy_members.find_one(
        {"_id": monday_item_id}, {"_id": 1, "dashboard_edited_fields": 1},
    )
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
    return fresh


# ----------------------------------------------------- Zapier-callable update
# Replaces the Monday "Get Items by Column Value + Update Item" pair used by
# ~40 zaps. Zap re-point: swap both Monday steps for one Webhooks-by-Zapier
# POST to this endpoint with the email + fields to change.
#
# Auth: shared secret in `X-Webhook-Secret`. Set ZAPIER_WEBHOOK_SECRET on
# Render and paste the same string into each zap's Webhooks step header.

class StudentUpdateByEmail(BaseModel):
    """Lookup key is `email` — matches against `email` OR `circle_email` on
    academy_members (zaps sometimes have one, sometimes the other).
    Anything in `fields` is applied. Allowlisted to PROTECTED_FIELDS so the
    automation can't accidentally write `_id` or `columns_by_id`."""
    email: str
    fields: dict[str, Any]

    class Config:
        extra = "forbid"


def _check_webhook_secret(x_webhook_secret: Optional[str]) -> None:
    expected = (os.environ.get("ZAPIER_WEBHOOK_SECRET") or "").strip()
    if not expected:
        raise HTTPException(503, "Webhook auth not configured")
    if (x_webhook_secret or "").strip() != expected:
        raise HTTPException(401, "Invalid webhook secret")


@router.post("/students-db/update-by-email")
async def update_student_by_email(
    payload: StudentUpdateByEmail,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Find a student by email (or circle_email) and update fields.

    Returns 404 if no match — zaps' existing Slack-alert fallback paths
    can branch on that response. Returns 400 if any field is not in the
    automation allowlist."""
    _check_webhook_secret(x_webhook_secret)

    email_l = (payload.email or "").strip().lower()
    if not email_l:
        raise HTTPException(400, "email is required")
    if not payload.fields:
        raise HTTPException(400, "fields must be non-empty")

    bad = set(payload.fields.keys()) - PROTECTED_FIELDS
    if bad:
        raise HTTPException(
            400, f"Fields not writable by automation: {sorted(bad)}"
        )

    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
        {"_id": 1, "dashboard_edited_fields": 1, "email": 1, "circle_email": 1},
    )
    if not row:
        # Surface as 404 so the zap's existing not-found branch fires.
        raise HTTPException(404, f"No student found for email={email_l}")

    set_fields: dict[str, Any] = dict(payload.fields)
    # Normalise email-ish fields (matches PATCH + mirror behaviour)
    for k in ("email", "circle_email"):
        if k in set_fields and set_fields[k] is not None:
            set_fields[k] = str(set_fields[k]).strip().lower() or None

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

    return {
        "ok": True,
        "id": row["_id"],
        "matched_on": "email" if row.get("email") == email_l else "circle_email",
        "updated_fields": sorted(set_fields.keys()),
    }


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

class StudentIntake(BaseModel):
    """A signup event from upstream (Kajabi, Tally, waitlist).

    `email` is the dedup key — case-insensitive match against existing
    academy_members rows. `fields` is everything else to set (tier, cohort,
    name, dates, etc.); allowlisted to PROTECTED_FIELDS plus a few intake-
    only fields (stage, source) tracked on the row for audit.
    """
    email: str
    fields: dict[str, Any]
    source: Optional[str] = None  # e.g. "kajabi", "tally-onboarding", "waitlist"

    class Config:
        extra = "forbid"


# Extra fields the intake endpoint can set on a row in addition to the
# normal scalar columns. Tracked so we know who/what created the row.
INTAKE_ONLY_FIELDS = {"stage", "source", "intake_payload_meta"}


@router.post("/students-db/intake")
async def intake_student(
    payload: StudentIntake,
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
    `fields.tier` directly. Keeps this endpoint a thin primitive."""
    _check_webhook_secret(x_webhook_secret)

    email_l = (payload.email or "").strip().lower()
    if not email_l:
        raise HTTPException(400, "email is required")
    if not payload.fields:
        raise HTTPException(400, "fields must be non-empty")

    allowed = PROTECTED_FIELDS | INTAKE_ONLY_FIELDS
    bad = set(payload.fields.keys()) - allowed
    if bad:
        raise HTTPException(
            400, f"Fields not writable by intake: {sorted(bad)}"
        )

    set_fields: dict[str, Any] = dict(payload.fields)
    # Normalise email-ish fields (matches PATCH + mirror behaviour)
    for k in ("email", "circle_email"):
        if k in set_fields and set_fields[k] is not None:
            set_fields[k] = str(set_fields[k]).strip().lower() or None

    # Always carry the lookup email and source through to the row
    set_fields.setdefault("email", email_l)
    if payload.source:
        set_fields["source"] = payload.source

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
    return {
        "ok": True,
        "id": new_id,
        "action": "created",
        "fields": sorted(set_fields.keys()),
    }
