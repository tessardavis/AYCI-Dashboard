"""
Reconcile each student's dashboard interview_date from their most-recent Tally
submission. See ~/.claude/plans/fluffy-discovering-cake.md (Part 1).

When a student reschedules they submit a fresh "AYCI - Interview Date Form"
(Tally nGyGj2). Nothing carried that new date into the mirror's
`interview_date`, so the dashboard, Upcoming Interviews and the night-before DM
all kept using the stale Monday value. This sets `interview_date` from the
MOST-RECENTLY-SUBMITTED Tally entry and pins it in `dashboard_edited_fields`
(already in academy_members_mirror.PROTECTED_FIELDS), so the 15-min Monday sync
can't clobber it.

Per Tessa: Tally is the single source of truth for date changes — no manual
dashboard editing; off-form reschedules are out of scope.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db import db
import tally_lookup

logger = logging.getLogger(__name__)


def _valid_date(d) -> str | None:
    """Return YYYY-MM-DD if `d` is a parseable ISO date, else None."""
    d = (str(d or ""))[:10]
    if not d:
        return None
    try:
        datetime.fromisoformat(d)
        return d
    except ValueError:
        return None


def _latest_tally_date(history: list) -> str | None:
    """Interview date from the most-recently-SUBMITTED entry that has a valid
    date.

    NB: `tally_lookup` sorts history by DATE, but Tessa's rule is "most recent
    *submission* wins" — so we sort by `submitted_at` here, not by date. This is
    what makes a re-submission with an earlier-but-future date still win.
    """
    rows = sorted((history or []), key=lambda r: (r.get("submitted_at") or ""), reverse=True)
    for r in rows:
        d = _valid_date(r.get("date"))
        if d:
            return d
    return None


async def reconcile_interview_dates(db_=db) -> dict:
    """Set interview_date from the latest Tally submission for every mirror row
    with an email. Idempotent (no-op when already equal). Returns a summary with
    a `changed` list of {email, name, old, new, monday_id} for observability and
    the calendar step.
    """
    rows = []
    async for r in db_.academy_members.find(
        {"$or": [{"email": {"$nin": [None, ""]}}, {"circle_email": {"$nin": [None, ""]}}]},
        {"columns": 0, "columns_by_id": 0},
    ):
        rows.append(r)

    # Look up Tally history for both the signup and Circle emails (covers the
    # dual-email case), in one bulk fetch.
    emails: set = set()
    for r in rows:
        for k in ("email", "circle_email"):
            v = (r.get(k) or "").strip().lower()
            if v:
                emails.add(v)
    if not emails:
        return {"scanned": 0, "changed_count": 0, "changed": [], "calendar_synced": 0}

    history_by_email = await tally_lookup.lookup_emails_bulk(db_, sorted(emails))

    now = datetime.now(timezone.utc)
    changed = []
    for r in rows:
        merged: list = []
        for k in ("email", "circle_email"):
            v = (r.get(k) or "").strip().lower()
            if v and v in history_by_email:
                merged += history_by_email[v].get("history") or []
        new_date = _latest_tally_date(merged)
        if not new_date:
            continue  # no Tally submission with a valid date → leave the Monday value
        old_date = (r.get("interview_date") or "") or None
        if new_date == old_date:
            continue  # idempotent no-op
        pinned = sorted(set(r.get("dashboard_edited_fields") or []) | {"interview_date"})
        await db_.academy_members.update_one(
            {"_id": r["_id"]},
            {"$set": {
                "interview_date": new_date,
                "interview_date_source": "tally",
                "interview_date_prev": old_date,
                "interview_date_reconciled_at": now,
                "dashboard_edited_fields": pinned,
                "dashboard_edited_at": now,
                "dashboard_edited_by": "interview-date-reconcile",
            }},
        )
        changed.append({
            "email": (r.get("email") or r.get("circle_email") or "").strip().lower(),
            "name": r.get("name"),
            "old": old_date,
            "new": new_date,
            "monday_id": r["_id"],
        })

    # Part 2: self-heal the "AYCI Interviews" calendar for changed students.
    # Best-effort and inert until GOOGLE_INTERVIEWS_CALENDAR_ID is set + the
    # calendar is shared with the dashboard service account.
    calendar_synced = 0
    try:
        import google_calendar
        if google_calendar.is_configured() and changed:
            by_id = {r["_id"]: r for r in rows}
            for c in changed:
                row = by_id.get(c["monday_id"])
                if not row:
                    continue
                try:
                    if await google_calendar.ensure_interview_event(db_, {**row, "interview_date": c["new"]}):
                        calendar_synced += 1
                except Exception as e:
                    logger.warning(f"[interview-date-reconcile] calendar sync failed for {c['email']}: {e}")
    except Exception as e:
        logger.info(f"[interview-date-reconcile] calendar step skipped: {e}")

    summary = {
        "scanned": len(rows),
        "changed_count": len(changed),
        "changed": changed,
        "calendar_synced": calendar_synced,
    }
    logger.info(f"[interview-date-reconcile] {summary['changed_count']} updated of {summary['scanned']}")
    return summary
