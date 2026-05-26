"""
Pre-computed Cohort Leaderboard response cache.

Why this exists: building the leaderboard response on-demand takes ~30s
(dominated by a single 1.7MB find_one on `circle_members_cache`).
Coaches open the leaderboard *before each live Curriculum / General
Coaching session*, so the cost of computing it lands on the user. We
pre-warm a ~20-min window ahead of every such session so opening the
page is a single sub-100ms Mongo read.

Storage: `db.leaderboard_response_cache`, one doc per cohort:
    { _id: "Apr '26", payload: {...full endpoint response...}, computed_at: <utc> }

Reader returns None when the cache is missing or older than `max_age_minutes`;
the route handler then falls through to the live (slow) compute path.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import leaderboard
import leaderboard_snapshots

logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")

# Cohorts we keep warm. Matches the frontend dropdown (CohortLeaderboard.jsx).
# Order matters for prewarm — active cohort first so it's hottest if budget is tight.
ACTIVE_COHORTS = ["Apr '26", "Feb '26", "April '25"]

# How long before a session we want the cache warm. The endpoint will accept
# a cache up to CACHE_MAX_AGE_MINUTES old; the warmer fires when a session
# is starting within PREWARM_WINDOW_MINUTES. The window is set wider than the
# spotlight Slack reminder (which fires ~30 min ahead) so the cache is already
# hot by the time the team clicks through from that ping. Max-age exceeds the
# window so a warm stays valid right through the session start.
PREWARM_WINDOW_MINUTES = 40
CACHE_MAX_AGE_MINUTES = 50


async def _compute_response(db, cohort: str, limit: int = 25) -> dict:
    """Reproduce the route handler's payload so the cache is a drop-in
    replacement. Kept here (not imported from the route) to avoid a
    circular import and so the warmer can be invoked from the scheduler
    without spinning up FastAPI."""
    full = await leaderboard.get_top_leaderboard(db, cohort_tag=cohort, limit=500)
    deltas = await leaderboard_snapshots.get_week_over_week(
        db, cohort, days=7, current_rows=full,
    )
    capped = max(1, min(int(limit), 100))
    rows = full[:capped]
    # Deep copy to avoid mutating the precomputed `full` list shared with climbers
    rows = [dict(r) for r in rows]
    for r in rows:
        d = deltas.get(r.get("email") or "")
        r["delta"] = d["delta"] if d else None
        r["new_badges"] = d["new_badges"] if d else []
        r["delta_snapshot_date"] = d.get("snapshot_date") if d else None
    climbers = await leaderboard_snapshots.get_biggest_climbers(
        db, cohort, days=7, limit=5, current_rows=full, deltas=deltas,
    )
    return {
        "cohort": cohort,
        "entries": rows,
        "total": len(rows),
        "biggest_climbers": climbers,
    }


async def prewarm(db, cohort: str, *, limit: int = 25) -> dict:
    """Compute the leaderboard response for `cohort` and write it to cache.
    Idempotent — re-runs just overwrite the doc. Returns a small status dict."""
    started = datetime.now(timezone.utc)
    payload = await _compute_response(db, cohort, limit=limit)
    await db.leaderboard_response_cache.update_one(
        {"_id": cohort},
        {"$set": {
            "_id": cohort,
            "payload": payload,
            "computed_at": started,
            "row_count": payload.get("total", 0),
        }},
        upsert=True,
    )
    duration = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        f"[leaderboard-cache] warmed {cohort}: {payload.get('total', 0)} entries in {duration:.1f}s"
    )
    return {"cohort": cohort, "rows": payload.get("total", 0), "duration_s": round(duration, 1)}


async def read_cached(db, cohort: str, *, max_age_minutes: int = CACHE_MAX_AGE_MINUTES) -> Optional[dict]:
    """Return the cached payload if it exists and is younger than
    `max_age_minutes`, else None."""
    doc = await db.leaderboard_response_cache.find_one(
        {"_id": cohort}, {"_id": 0},
    )
    if not doc:
        return None
    computed_at = doc.get("computed_at")
    if not isinstance(computed_at, datetime):
        return None
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    if computed_at < cutoff:
        return None
    payload = doc.get("payload")
    if not payload:
        return None
    # Surface the freshness so debug eyes can tell cached vs live.
    return {**payload, "_cache_computed_at": computed_at.isoformat()}


async def warm_for_upcoming_sessions(db) -> dict:
    """Called by the every-5-min spotlight reminders tick. If any Curriculum
    or General Coaching session is starting within PREWARM_WINDOW_MINUTES,
    re-warm the active cohorts so the page opens instantly when the team
    pulls it up just before the session.

    Why hook here vs. its own cron: the spotlight tick already fetches the
    upcoming-sessions list, so we piggyback. We don't fire when no session
    is imminent — saves ~30s of Mongo I/O on every 5-min idle tick.

    Returns `{checked: N, warmed: [...]}`. Never raises."""
    try:
        import spotlight
        payload = await spotlight.get_upcoming_spotlight_sessions(db, limit=6)
    except Exception as e:
        logger.warning(f"[leaderboard-cache] could not load upcoming sessions: {e}")
        return {"checked": 0, "warmed": [], "error": str(e)}

    sessions = payload.get("sessions") or []
    now = datetime.now(timezone.utc)
    window = now + timedelta(minutes=PREWARM_WINDOW_MINUTES)
    imminent = []
    for s in sessions:
        starts_at = s.get("starts_at") or ""
        if not starts_at:
            continue
        try:
            dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        # Session is in the prewarm window if it starts between now and
        # +PREWARM_WINDOW_MINUTES. We don't warm for sessions already in
        # progress (the team is already on the page).
        if now <= dt <= window:
            imminent.append(s)

    if not imminent:
        return {"checked": len(sessions), "warmed": []}

    warmed = []
    for cohort in ACTIVE_COHORTS:
        try:
            res = await prewarm(db, cohort)
            warmed.append(res)
        except Exception as e:
            logger.exception(f"[leaderboard-cache] prewarm failed for {cohort}")
            warmed.append({"cohort": cohort, "error": str(e)})
    return {
        "checked": len(sessions),
        "imminent_sessions": [s.get("name") for s in imminent],
        "warmed": warmed,
    }
