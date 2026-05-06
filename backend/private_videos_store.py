"""
Private-Tier Video Submissions — DB-backed version (Phase 1 of Monday
retirement).

Schema of `private_video_submissions` collection:
    {
      "id": "uuid4",                  # our primary key
      "monday_item_id": "2892822381", # legacy — set for migrated rows, null for native
      "first_name": str,
      "last_name": str,
      "email": str,                   # lowercased, used as student matcher
      "submitted_at": iso datetime,
      "question": str,
      "tally_video_url": str | null,
      "total_allowance": int | null,
      "submission_number": int | null,
      "status": "new"|"working"|"done"|"update_name",
      "assignee_team_member_id": str | null,
      "replied_at": iso datetime | null,
      "reply_link": str | null,
      "private_chat_url": str | null,
      "interview_date": iso date | null,
      "created_at": iso datetime,
      "updated_at": iso datetime,
    }
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

STATUS_ORDER = {"new": 0, "working": 1, "done": 2, "update_name": 3}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_status(label: Optional[str]) -> str:
    if not label:
        return "new"
    t = label.lower().strip()
    if t == "new":
        return "new"
    if t in ("working on it", "working"):
        return "working"
    if t == "done":
        return "done"
    if t in ("update name", "update"):
        return "update_name"
    return "new"


def _status_label(key: str) -> str:
    return {
        "new": "New",
        "working": "Working on it",
        "done": "Done",
        "update_name": "Update name",
    }.get(key, "New")


def _to_int(v) -> Optional[int]:
    try:
        return int(str(v).strip()) if v not in (None, "") else None
    except Exception:
        return None


async def list_submissions(db) -> dict:
    """Return every submission, sorted by status (New → Working → Done) then
    submitted date desc."""
    rows = await db.private_video_submissions.find(
        {}, {"_id": 0}
    ).to_list(2000)
    rows.sort(key=lambda r: (
        STATUS_ORDER.get(r.get("status", "new"), 99),
        -(int(
            (r.get("submitted_at") or "1900-01-01")[:10].replace("-", "")
        ) if r.get("submitted_at") else 0),
    ))
    # Decorate with label for the UI (keeps the frontend identical to Monday)
    for r in rows:
        r["status_label"] = _status_label(r.get("status", "new"))
    return {"items": rows, "fetched_at": _now_iso()}


async def update_submission(db, submission_id: str, patch: dict) -> dict:
    allowed = {}
    if "status" in patch and patch["status"] is not None:
        allowed["status"] = _norm_status(patch["status"])
    if "assignee_team_member_id" in patch:
        allowed["assignee_team_member_id"] = patch["assignee_team_member_id"] or None
    if "replied_at" in patch:
        allowed["replied_at"] = patch["replied_at"] or None
    if "reply_link" in patch:
        allowed["reply_link"] = (patch["reply_link"] or "").strip() or None
    if "private_chat_url" in patch:
        allowed["private_chat_url"] = (patch["private_chat_url"] or "").strip() or None
    if "interview_date" in patch:
        allowed["interview_date"] = patch["interview_date"] or None

    if not allowed:
        return {"ok": False, "reason": "no editable fields supplied"}
    allowed["updated_at"] = _now_iso()
    res = await db.private_video_submissions.update_one(
        {"id": submission_id}, {"$set": allowed}
    )
    if res.matched_count == 0:
        return {"ok": False, "reason": "submission not found"}
    return {"ok": True, "id": submission_id}


async def create_submission(db, data: dict) -> dict:
    """Create a new submission — used by the Tally webhook."""
    now = _now_iso()
    email = (data.get("email") or "").strip().lower()
    row = {
        "id": str(uuid.uuid4()),
        "monday_item_id": None,
        "first_name": (data.get("first_name") or "").strip(),
        "last_name": (data.get("last_name") or "").strip(),
        "email": email,
        "submitted_at": data.get("submitted_at") or now,
        "question": (data.get("question") or "").strip(),
        "tally_video_url": (data.get("tally_video_url") or "").strip() or None,
        "total_allowance": _to_int(data.get("total_allowance")),
        "submission_number": _to_int(data.get("submission_number")),
        "status": _norm_status(data.get("status") or "new"),
        "assignee_team_member_id": data.get("assignee_team_member_id"),
        "replied_at": data.get("replied_at"),
        "reply_link": data.get("reply_link"),
        "private_chat_url": data.get("private_chat_url"),
        "interview_date": data.get("interview_date"),
        "created_at": now,
        "updated_at": now,
    }
    await db.private_video_submissions.insert_one(row)
    return row


# ---------------------------------------------------------------- Migration
async def migrate_from_monday(db) -> dict:
    """One-off: pull every row from Monday board 5083952249 and write into
    `private_video_submissions`. Idempotent: rows already migrated (matched
    on monday_item_id) are updated in place, not duplicated."""
    import private_videos as monday_pv
    monday_data = await monday_pv.list_submissions(db, force=True)
    created = 0
    updated = 0
    now = _now_iso()
    for it in monday_data.get("items") or []:
        monday_id = str(it.get("id"))
        row = {
            "first_name": (it.get("first_name") or "").strip(),
            "last_name": (it.get("last_name") or "").strip(),
            "email": ((it.get("email") or "").strip().lower()),
            "submitted_at": it.get("submitted") or it.get("created_at"),
            "question": (it.get("question") or "").strip(),
            "tally_video_url": ((it.get("tally_video") or {}).get("url")
                                 or (it.get("video") or {}).get("url")),
            "total_allowance": _to_int(it.get("total_allowance")),
            "submission_number": _to_int(it.get("submission_number")),
            "status": _norm_status(it.get("status")),
            "assignee_team_member_id": None,  # Monday user_id ≠ our team_member uuid; manual mapping later
            "replied_at": it.get("replied"),
            "reply_link": (it.get("reply_link") or {}).get("url"),
            "private_chat_url": it.get("private_chat"),
            "interview_date": it.get("interview_date"),
            "updated_at": now,
        }
        existing = await db.private_video_submissions.find_one(
            {"monday_item_id": monday_id}, {"_id": 0, "id": 1}
        )
        if existing:
            await db.private_video_submissions.update_one(
                {"monday_item_id": monday_id}, {"$set": row}
            )
            updated += 1
        else:
            row["id"] = str(uuid.uuid4())
            row["monday_item_id"] = monday_id
            row["created_at"] = now
            await db.private_video_submissions.insert_one(row)
            created += 1
    return {"ok": True, "created": created, "updated": updated,
            "total_in_monday": len(monday_data.get("items") or [])}
