"""
Daily leaderboard snapshot — so we can compute week-over-week deltas and
surface "biggest climbers" in each cohort.

Snapshots live in `leaderboard_snapshots`:
  {
    "cohort": "Apr '26",
    "email": "user@x.com",
    "name": "...",
    "score": 5,
    "badges": ["Verified!", "Daily Prep", ...],
    "snapshot_date": "2026-05-03",            # YYYY-MM-DD (UK)
    "recorded_at": ISODateTime
  }

Unique index: (cohort, email, snapshot_date). One row per person per day.
Daily cron at 02:15 UK (in server.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import leaderboard

logger = logging.getLogger(__name__)
UK_TZ = ZoneInfo("Europe/London")


def _today_uk_str() -> str:
    return datetime.now(UK_TZ).date().isoformat()


async def snapshot_cohort(db, cohort: str = "Apr '26") -> int:
    """Write today's snapshot rows for all members of `cohort`. Idempotent —
    re-running in the same day updates the existing rows rather than
    duplicating them. Returns number of rows written."""
    rows = await leaderboard.get_top_leaderboard(db, cohort_tag=cohort, limit=500)
    date = _today_uk_str()
    now = datetime.now(timezone.utc)
    count = 0
    for r in rows:
        if not r.get("email"):
            continue
        await db.leaderboard_snapshots.update_one(
            {"cohort": cohort, "email": r["email"], "snapshot_date": date},
            {"$set": {
                "cohort": cohort,
                "email": r["email"],
                "name": r.get("name"),
                "score": r["score"],
                "badges": r.get("badges") or [],
                "snapshot_date": date,
                "recorded_at": now,
            }},
            upsert=True,
        )
        count += 1
    logger.info(f"[leaderboard-snapshot] {cohort}: wrote {count} rows for {date}")
    return count


async def snapshot_all_active_cohorts(db) -> dict:
    """Snapshot every cohort currently visible on the Cohort Leaderboard page
    picker. Called by the daily cron."""
    results = {}
    for cohort in ("Apr '26", "Feb '26", "April '25"):
        try:
            results[cohort] = await snapshot_cohort(db, cohort)
        except Exception as e:
            logger.exception(f"[leaderboard-snapshot] {cohort} failed")
            results[cohort] = f"error: {e}"
    return results


async def get_week_over_week(
    db,
    cohort: str,
    days: int = 7,
    *,
    current_rows: Optional[list[dict]] = None,
) -> dict[str, dict]:
    """Return `{email: {prev_score, delta, new_badges}}` for a cohort.

    `prev_score` is the score from ~`days` ago (uses the newest snapshot
    strictly older than `today - days + 1`). If no prior snapshot exists, we
    return an empty dict for that member (delta unknown, not 0).

    Pass `current_rows` (output of `get_top_leaderboard`) to skip the extra
    fetch when the caller already has it — saves a ~1.7MB Mongo read."""
    today = datetime.now(UK_TZ).date()
    cutoff_date = (today - timedelta(days=days)).isoformat()
    rows = db.leaderboard_snapshots.find(
        {"cohort": cohort, "snapshot_date": {"$lte": cutoff_date}},
        {"_id": 0, "email": 1, "score": 1, "badges": 1, "snapshot_date": 1},
    ).sort("snapshot_date", -1)
    # Pick latest snapshot per email
    best: dict[str, dict] = {}
    async for r in rows:
        email = r.get("email")
        if email and email not in best:
            best[email] = r
    # Compute deltas against current state
    current = current_rows if current_rows is not None else await leaderboard.get_top_leaderboard(db, cohort_tag=cohort, limit=500)
    out: dict[str, dict] = {}
    for c in current:
        email = c.get("email")
        if not email:
            continue
        prior = best.get(email)
        if not prior:
            continue
        prev_score = prior.get("score", 0)
        prev_badges = set(prior.get("badges") or [])
        curr_badges = set(c.get("badges") or [])
        new_badges = sorted(curr_badges - prev_badges, key=lambda s: s.lower())
        out[email] = {
            "prev_score": prev_score,
            "delta": c["score"] - prev_score,
            "new_badges": new_badges,
            "snapshot_date": prior.get("snapshot_date"),
        }
    return out


async def get_biggest_climbers(
    db,
    cohort: str,
    days: int = 7,
    limit: int = 5,
    *,
    current_rows: Optional[list[dict]] = None,
    deltas: Optional[dict[str, dict]] = None,
) -> list[dict]:
    """Top-`limit` members by positive delta over `days`. Returns list of
    `{email, name, delta, current_score, prev_score, new_badges, avatar_url}`.

    Pass `current_rows` + `deltas` if the caller already has them to avoid
    re-fetching the 1.7MB Circle members cache and re-scanning snapshots."""
    current = current_rows if current_rows is not None else await leaderboard.get_top_leaderboard(db, cohort_tag=cohort, limit=500)
    deltas = deltas if deltas is not None else await get_week_over_week(db, cohort, days=days, current_rows=current)
    by_email = {c["email"]: c for c in current if c.get("email")}
    climbers = []
    for email, d in deltas.items():
        if d["delta"] <= 0:
            continue
        cur = by_email.get(email) or {}
        climbers.append({
            "email": email,
            "name": cur.get("name"),
            "avatar_url": cur.get("avatar_url"),
            "current_score": cur.get("score", 0),
            "prev_score": d["prev_score"],
            "delta": d["delta"],
            "new_badges": d["new_badges"],
            "snapshot_date": d.get("snapshot_date"),
        })
    climbers.sort(key=lambda c: (-c["delta"], -c["current_score"], (c.get("name") or "").lower()))
    return climbers[:limit]
