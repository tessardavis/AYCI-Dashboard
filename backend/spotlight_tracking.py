"""
Spotlight tracking: record who was actually spotlighted in each session.

Statuses (per Tessa 03-May):
  - spotlighted            — did a full spotlight coaching on them
  - didnt_attend           — signed up but was a no-show
  - skipped                — explicitly passed over (ran out of time)
  - not_submitted_correctly — their tally form had issues (wrong cycle, duplicate, etc.)

Data model (`spotlight_records` collection, no `_id` in responses):
{
  "id": "<uuid>",
  "session_id": 12345,                   # Circle event id
  "session_name": "Bonus General Coaching",
  "session_starts_at": "2026-05-03T09:00:00Z",
  "session_type": "group_coaching" | "curriculum",
  "student_name": "Tammy Tran",
  "student_email": "tammy@...",          # optional, only when from Tally
  "status": "spotlighted" | "didnt_attend" | "skipped" | "not_submitted_correctly",
  "notes": "",                           # optional free-text
  "source": "tally" | "manual",
  "recorded_by": "<user-id>",
  "recorded_by_name": "Tessa Davis",
  "recorded_at": "2026-05-03T10:45:00Z",
  "updated_at": "…",
}

Uniqueness: one record per (session_id, student_name_key). Re-posting the same
pair upserts the status + notes.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import spotlight

VALID_STATUSES = {
    "spotlighted",
    "didnt_attend",
    "skipped",
    "not_submitted_correctly",
}

STATUS_LABELS = {
    "spotlighted": "Spotlighted",
    "didnt_attend": "Didn't attend",
    "skipped": "Skipped",
    "not_submitted_correctly": "Not submitted correctly",
}


def _name_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


async def _enrich_session_meta(db, session_id: int) -> dict:
    """Look up a session's metadata (name, starts_at, type) from the currently-
    cached spotlight payload. If not found (session has ended long enough to
    drop off), fall back to any existing record for that session_id, and
    finally to `{"session_id": …}` only."""
    try:
        payload = await spotlight.get_upcoming_spotlight_sessions(db, limit=6)
        for s in payload.get("sessions") or []:
            if s.get("id") == session_id:
                return {
                    "session_name": s.get("name"),
                    "session_starts_at": s.get("starts_at"),
                    "session_type": s.get("session_type"),
                }
    except Exception:
        pass
    # Fallback to previously-stored record
    prior = await db.spotlight_records.find_one(
        {"session_id": session_id}, {"_id": 0}
    )
    if prior:
        return {
            "session_name": prior.get("session_name"),
            "session_starts_at": prior.get("session_starts_at"),
            "session_type": prior.get("session_type"),
        }
    return {"session_name": None, "session_starts_at": None, "session_type": None}


async def upsert_record(
    db,
    *,
    session_id: int,
    student_name: str,
    status: str,
    notes: str = "",
    source: str = "tally",
    student_email: Optional[str] = None,
    recorded_by: str,
    recorded_by_name: str,
) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status '{status}'")
    nk = _name_key(student_name)
    if not nk:
        raise ValueError("student_name required")
    meta = await _enrich_session_meta(db, session_id)
    now = datetime.now(timezone.utc)
    existing = await db.spotlight_records.find_one(
        {"session_id": session_id, "name_key": nk},
        {"_id": 0},
    )
    if existing:
        patch = {
            "status": status,
            "notes": notes or "",
            "source": source,
            "student_email": (student_email or existing.get("student_email") or "").lower() or None,
            "student_name": student_name.strip() or existing.get("student_name"),
            "recorded_by": recorded_by,
            "recorded_by_name": recorded_by_name,
            "updated_at": now,
            **meta,
        }
        await db.spotlight_records.update_one(
            {"id": existing["id"]}, {"$set": patch}
        )
        merged = {**existing, **patch}
        return _serialise(merged)
    record = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "student_name": student_name.strip(),
        "name_key": nk,
        "student_email": (student_email or "").lower() or None,
        "status": status,
        "notes": notes or "",
        "source": source,
        "recorded_by": recorded_by,
        "recorded_by_name": recorded_by_name,
        "recorded_at": now,
        "updated_at": now,
        **meta,
    }
    await db.spotlight_records.insert_one(dict(record))
    return _serialise(record)


async def delete_record(db, record_id: str) -> bool:
    result = await db.spotlight_records.delete_one({"id": record_id})
    return result.deleted_count > 0


async def list_for_session(db, session_id: int) -> list[dict]:
    rows = await db.spotlight_records.find(
        {"session_id": session_id}, {"_id": 0}
    ).to_list(500)
    return [_serialise(r) for r in rows]


async def list_history(db, limit: int = 40) -> list[dict]:
    """Return past sessions grouped, newest first. Each group contains the
    session meta + all records."""
    # Distinct session_ids ordered by session_starts_at desc
    pipeline = [
        {"$sort": {"session_starts_at": -1, "recorded_at": -1}},
        {"$group": {
            "_id": "$session_id",
            "session_name": {"$first": "$session_name"},
            "session_starts_at": {"$first": "$session_starts_at"},
            "session_type": {"$first": "$session_type"},
            "records": {"$push": "$$ROOT"},
        }},
        {"$sort": {"session_starts_at": -1}},
        {"$limit": limit},
    ]
    groups = []
    async for g in db.spotlight_records.aggregate(pipeline):
        records = [_serialise(r) for r in g.get("records") or []]
        # Within a group, put spotlighted first, then others
        records.sort(key=lambda r: (
            0 if r["status"] == "spotlighted" else 1,
            r.get("student_name", "").lower(),
        ))
        groups.append({
            "session_id": g["_id"],
            "session_name": g.get("session_name"),
            "session_starts_at": g.get("session_starts_at"),
            "session_type": g.get("session_type"),
            "records": records,
            "counts": _count_statuses(records),
        })
    return groups


def _count_statuses(records: list[dict]) -> dict[str, int]:
    out = {s: 0 for s in VALID_STATUSES}
    for r in records:
        s = r.get("status")
        if s in out:
            out[s] += 1
    return out


async def student_spotlight_counts(db) -> dict[str, int]:
    """Return `{name_key: spotlighted_count}` so the prep board can badge
    frequent flyers."""
    out: dict[str, int] = {}
    async for r in db.spotlight_records.find(
        {"status": "spotlighted"}, {"_id": 0, "name_key": 1}
    ):
        nk = r.get("name_key")
        if nk:
            out[nk] = out.get(nk, 0) + 1
    return out


def _serialise(r: dict[str, Any]) -> dict[str, Any]:
    """Make Mongo dates JSON-safe + drop `_id`/`name_key` from the wire format."""
    out = {k: v for k, v in r.items() if k not in {"_id", "name_key"}}
    for k in ("recorded_at", "updated_at"):
        v = out.get(k)
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            out[k] = v.isoformat()
    return out
