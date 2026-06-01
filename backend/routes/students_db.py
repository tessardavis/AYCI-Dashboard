"""
CRUD over the Academy Members Mongo mirror — the data set that eventually
fully replaces the Monday Academy Members board.

Reads pull from db.academy_members (the 15-min mirror). Writes update the
same row AND mark the edited field in `dashboard_edited_fields` so the
next Monday sync doesn't clobber the change.

Routes:
  GET  /api/students-db                  list, with filters + search
  GET  /api/students-db/{monday_item_id} one row
  PATCH /api/students-db/{monday_item_id} update fields (protected from sync)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import db
from deps import require_board

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
