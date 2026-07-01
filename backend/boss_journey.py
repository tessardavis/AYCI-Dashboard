"""Boss Badge -> testimonial journey tracking. See PROCESSES.md #5.

Journey per Boss: tagged -> win shared -> testimonial booked -> recorded.
  - tagged: boss_badge=Yes (set by Coralie's "Mark as Boss" button / the form).
  - win shared: auto-detected from a post in the Share Your Wins Circle space.
  - testimonial booked/recorded: set by the Calendly webhook (calendly_webhook).

This module owns the win-shared detection + the "recorded" sweep + the per-Boss
status used by the "Bosses to chase" view. Circle reads route through circle_meter.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

WINS_SPACE_ID = 996901  # "Share Your Wins" (same id used by the scorecard posts connector)

_BOSS_YES = {"yes", "true", "1", "y"}
_BOOKED_STATES = {"booked", "rescheduled", "recorded", "attended", "done"}
_RECORDED_STATES = {"recorded", "attended", "done"}


def is_boss(row: dict) -> bool:
    return (row.get("boss_badge") or "").strip().lower() in _BOSS_YES


def journey_status(row: dict) -> dict:
    """Per-Boss status. The baseline is EVERY Boss-tagged member; we'd like each to
    do two INDEPENDENT things - share a win AND record a testimonial. They are not a
    funnel: someone can record a testimonial without ever posting a win, or vice
    versa. `complete` = did both. `needs_win` / `needs_testimonial` flag each gap
    independently. (`stuck` is kept only for legacy sort ordering.)"""
    win = bool(row.get("win_shared_at"))
    tstatus = (row.get("testimonial_status") or "").strip().lower()
    cancelled = tstatus in ("cancelled", "no-show")
    booked = tstatus in _BOOKED_STATES
    recorded = tstatus in _RECORDED_STATES or bool(row.get("testimonial_recorded_at"))
    needs_win = not win
    needs_testimonial = not recorded
    complete = win and recorded
    # Legacy single-axis label (win first) - only used to order the list nicely.
    if not win:
        stuck = "win"
    elif not booked or cancelled:
        stuck = "booking"
    elif not recorded:
        stuck = "recording"
    else:
        stuck = None
    return {
        "tagged": True,
        "tagged_at": row.get("boss_tagged_at"),
        "win_shared": win,
        "win_shared_at": row.get("win_shared_at"),
        "testimonial_status": row.get("testimonial_status"),
        "testimonial_booked": booked and not cancelled,
        "testimonial_booked_date": row.get("testimonial_booked_date"),
        "testimonial_recorded": recorded,
        "testimonial_coach": row.get("testimonial_coach"),
        "needs_win": needs_win,
        "needs_testimonial": needs_testimonial,
        "stuck": stuck,
        "complete": complete,
    }


def _post_author_ids_emails(posts: list) -> tuple[set, set]:
    """Defensively pull author member-ids + emails out of Circle post records
    (the exact field name varies, so check several)."""
    ids: set = set()
    emails: set = set()
    for p in posts:
        for k in ("user_id", "community_member_id", "author_id"):
            v = p.get(k)
            try:
                if v:
                    ids.add(int(v))
            except (TypeError, ValueError):
                pass
        for nest in ("user", "community_member", "author"):
            u = p.get(nest)
            if isinstance(u, dict):
                try:
                    if u.get("id"):
                        ids.add(int(u["id"]))
                except (TypeError, ValueError):
                    pass
                e = (u.get("email") or "").strip().lower()
                if e:
                    emails.add(e)
        e = (p.get("user_email") or "").strip().lower()
        if e:
            emails.add(e)
    return ids, emails


def _row_emails(row: dict) -> list:
    import re
    out = []
    for k in ("email", "circle_email"):
        e = (row.get(k) or "").strip().lower()
        if e:
            out.append(e)
    for tok in re.split(r"[,;\s]+", row.get("other_emails") or ""):
        e = tok.strip().lower()
        if e and "@" in e:
            out.append(e)
    return out


async def scan_wins_shared(db) -> dict:
    """Scan the Share Your Wins space and tick win_shared_at for any Boss who has
    posted there. One scan covers everyone. Read-only on Circle (metered)."""
    import coach_activity
    import private_chat_setup
    summary = {"posts": 0, "newly_marked": 0, "errors": 0}
    try:
        posts = await coach_activity._circle_list_posts_in_space(None, WINS_SPACE_ID)
    except Exception as e:
        logger.warning(f"[boss-journey] wins post scan failed: {e}")
        return {**summary, "error": str(e)[:200]}
    summary["posts"] = len(posts)
    author_ids, author_emails = _post_author_ids_emails(posts)

    # Record channel-wide totals (all sharers, Boss or not) so the Bosses widget
    # can show "total wins shared overall" without re-reading Circle each load.
    try:
        await db.fn_cache.update_one(
            {"_id": "wins_share_summary"},
            {"$set": {"_id": "wins_share_summary",
                      "total_posts": len(posts),
                      "unique_sharers": len(author_ids | author_emails),
                      "scanned_at": datetime.now(timezone.utc)}},
            upsert=True)
    except Exception as e:
        logger.warning(f"[boss-journey] wins summary store failed: {e}")

    try:
        by_email = await private_chat_setup._build_email_index()
    except Exception:
        by_email = {}

    now = datetime.now(timezone.utc)
    cursor = db.academy_members.find(
        {"boss_badge": {"$exists": True}, "win_shared_at": {"$in": [None, ""]}},
        {"name": 1, "boss_badge": 1, "email": 1, "circle_email": 1, "other_emails": 1})
    async for row in cursor:
        if not is_boss(row):
            continue
        emails = _row_emails(row)
        mid = None
        for e in emails:
            m = by_email.get(e)
            if m and m.get("id"):
                mid = int(m["id"])
                break
        shared = (mid is not None and mid in author_ids) or any(e in author_emails for e in emails)
        if shared:
            try:
                pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"win_shared_at"})
                await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
                    "win_shared_at": now, "dashboard_edited_fields": pinned,
                    "dashboard_edited_at": now, "dashboard_edited_by": "boss-journey-winscan"}})
                summary["newly_marked"] += 1
            except Exception as e:
                summary["errors"] += 1
                logger.warning(f"[boss-journey] win mark failed {row['_id']}: {e}")
    logger.info(f"[boss-journey] wins scan: {summary}")
    return summary


async def mark_recorded(db) -> dict:
    """Flip a booked testimonial to Recorded once its date has passed (the call
    happened). Pure Mongo - no Circle/Calendly calls."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)
    marked = 0
    cursor = db.academy_members.find(
        {"testimonial_status": {"$in": ["Booked", "Rescheduled"]},
         "testimonial_booked_date": {"$lt": today, "$nin": [None, ""]}},
        {"testimonial_booked_date": 1, "dashboard_edited_fields": 1})
    async for row in cursor:
        pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"testimonial_status", "testimonial_recorded_at"})
        await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
            "testimonial_status": "Recorded", "testimonial_recorded_at": now,
            "dashboard_edited_fields": pinned, "dashboard_edited_at": now,
            "dashboard_edited_by": "boss-journey-recorded"}})
        marked += 1
    logger.info(f"[boss-journey] marked recorded: {marked}")
    return {"recorded": marked}


async def sweep(db) -> dict:
    """Scheduled: detect newly-shared wins + flip past-date bookings to Recorded."""
    wins = await scan_wins_shared(db)
    rec = await mark_recorded(db)
    return {"wins": wins, "recorded": rec}
