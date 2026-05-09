"""Coach-Activity alert dismissal store.

When the team has reviewed an "Awaiting coach reply" or "Posting > 3/week"
flag and confirmed it's not actually actionable (test post, student didn't
upload, etc.), they can dismiss it. Dismissals are SHARED across the team
and persist forever.

Dismissal model: a single document per (alert_type, dedup_key). Storing the
SAME dedup keys we use for Slack idempotency so a user-driven dismissal
also stops Slack pings for that (student, week).

Dedup keys (lowercased, single-spaced):
  unanswered:    "<post_id>"                       (one Circle post)
  rate_limited:  "<student_name>::<YYYY-MM-DD>"    (one student × week)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone


def _norm_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def rate_limit_key(name: str | None, week_start: str | None) -> str:
    return f"{_norm_name(name)}::{(week_start or '').strip()}"


def unanswered_key(post_id) -> str:
    return f"{post_id}"


async def list_dismissed_keys(db, alert_type: str) -> set[str]:
    """Return the set of dismissed keys for a given alert type."""
    cursor = db.coach_activity_dismissed.find(
        {"alert_type": alert_type}, {"_id": 0, "key": 1},
    )
    out: set[str] = set()
    async for d in cursor:
        k = d.get("key")
        if k:
            out.add(k)
    return out


async def dismiss(
    db, *, alert_type: str, key: str, by_user_id: str | None, by_name: str | None,
) -> dict:
    """Idempotently mark an alert as dismissed."""
    now = datetime.now(timezone.utc).isoformat()
    await db.coach_activity_dismissed.update_one(
        {"alert_type": alert_type, "key": key},
        {"$set": {
            "alert_type": alert_type,
            "key": key,
            "dismissed_at": now,
            "dismissed_by_user_id": by_user_id,
            "dismissed_by_name": by_name,
        }},
        upsert=True,
    )
    return {"ok": True, "alert_type": alert_type, "key": key}


async def undismiss(db, *, alert_type: str, key: str) -> dict:
    res = await db.coach_activity_dismissed.delete_one(
        {"alert_type": alert_type, "key": key}
    )
    return {"ok": True, "removed": res.deleted_count}
