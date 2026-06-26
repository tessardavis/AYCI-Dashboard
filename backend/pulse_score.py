"""
Pulse Score: a single 0-100 health score for the team dashboard, amalgamating
four pillars (each scored 0-25):

  1. Scorecard goals - ratio of metrics on-track for the most recent week.
  2. Quarterly rocks - ratio of active-quarter rocks that are NOT off-track.
  3. SLA breaches    - number of Circle posts unanswered >48 h.
  4. Students at risk - number of high-spend students that are dormant.

Cheap to compute because every input is already cached upstream:
  - coach_activity / sla_notifications.count_unanswered → cached coach summary
  - at_risk.get_at_risk_cached → 24h cache
  - rocks + metrics + weekly_values → straight Mongo reads (small collections)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import at_risk
import settings_store
import sla_notifications


def _latest_completed_monday(today: Optional[datetime] = None) -> str:
    """ISO date of the most recently *completed* Monday (i.e. last week's
    Monday if today is mid-week). Mirrors the frontend scorecard logic."""
    now = (today or datetime.now(timezone.utc)).date()
    # Monday=0. The most recent completed week ends last Sunday, so its Monday
    # is `now - now.weekday() - 7`.
    this_monday = now - timedelta(days=now.weekday())
    last_monday = this_monday - timedelta(days=7)
    return last_monday.isoformat()


def _is_on_track(value: float, goal, direction: str) -> Optional[bool]:
    """Mirror of frontend `isOnTrack` (lib/format.js)."""
    if value is None or goal is None:
        return None
    try:
        v = float(value)
        g = float(goal)
    except (TypeError, ValueError):
        return None
    if direction == "below":
        return v <= g
    return v >= g


async def _score_scorecard(db, week_start: str) -> dict:
    """Pillar 1: missed scorecard goals.
    Score = 25 * (on_track / with_value). Metrics without a value or without a
    goal are excluded from the denominator."""
    metrics = await db.metrics.find(
        {"cohort_only": {"$ne": True}}, {"_id": 0}
    ).to_list(1000)
    if not metrics:
        return {"score": 25, "max": 25, "tracked": 0, "missed": 0,
                "label": "No metrics configured"}

    values = await db.weekly_values.find(
        {"week_start": week_start}, {"_id": 0}
    ).to_list(10000)
    by_metric = {v["metric_id"]: v["value"] for v in values}

    tracked = 0
    on_track = 0
    for m in metrics:
        val = by_metric.get(m["id"])
        verdict = _is_on_track(val, m.get("goal"), m.get("goal_direction") or "above")
        if verdict is None:
            continue
        tracked += 1
        if verdict:
            on_track += 1

    if tracked == 0:
        return {"score": 25, "max": 25, "tracked": 0, "missed": 0,
                "label": "No values entered yet"}

    missed = tracked - on_track
    pct = on_track / tracked
    score = round(25 * pct)
    return {"score": score, "max": 25, "tracked": tracked, "missed": missed,
            "on_track": on_track,
            "label": f"{missed} of {tracked} scorecard goal{'s' if tracked != 1 else ''} missed"}


async def _score_rocks(db) -> dict:
    """Pillar 2: off-track rocks in active quarter.
    Score = 25 * ((total - off_track) / total). 'done' rocks count as healthy."""
    active = await settings_store.get_active_quarter(db)
    if not active:
        return {"score": 25, "max": 25, "total": 0, "off_track": 0,
                "label": "No active quarter set"}

    rocks = await db.rocks.find({"quarter": active}, {"_id": 0}).to_list(1000)
    if not rocks:
        return {"score": 25, "max": 25, "total": 0, "off_track": 0,
                "quarter": active,
                "label": f"No rocks set for {active}"}

    off_track = sum(1 for r in rocks if r.get("status") == "off_track")
    total = len(rocks)
    healthy = total - off_track
    score = round(25 * (healthy / total))
    return {"score": score, "max": 25, "total": total, "off_track": off_track,
            "quarter": active,
            "label": f"{off_track} of {total} rock{'s' if total != 1 else ''} off-track"}


async def _score_sla(db) -> dict:
    """Pillar 3: SLA breaches. 0 = full marks; each breach docks 3 points,
    floor at 0. (8 breaches = 1 point left, 9+ = 0.)"""
    try:
        unanswered = await sla_notifications.count_unanswered(db)
    except Exception:
        unanswered = 0
    score = max(0, 25 - 3 * unanswered)
    return {"score": score, "max": 25, "unanswered": unanswered,
            "label": (
                "All Circle posts answered in <48 h" if unanswered == 0
                else f"{unanswered} post{'s' if unanswered != 1 else ''} unanswered >48 h"
            )}


async def _score_students(db) -> dict:
    """Pillar 4: at-risk students. 0 = full marks; each at-risk student docks
    1 point, floor at 0. (25 at-risk students = 0 points.)"""
    try:
        payload = await at_risk.get_at_risk_cached(db, force=False)
    except Exception:
        payload = {"total_at_risk": 0, "computing": True}
    if payload.get("computing") and payload.get("total_at_risk", 0) == 0:
        return {"score": 25, "max": 25, "at_risk": 0, "computing": True,
                "label": "First-time at-risk scan in progress"}
    n = int(payload.get("total_at_risk", 0))
    score = max(0, 25 - n)
    return {"score": score, "max": 25, "at_risk": n,
            "label": (
                "No high-spend students dormant" if n == 0
                else f"{n} high-spend student{'s' if n != 1 else ''} dormant on Circle"
            )}


def _label_for_score(score: int) -> str:
    if score >= 80:
        return "Healthy"
    if score >= 60:
        return "Watch"
    return "At risk"


async def compute_pulse_score(db, week_start: Optional[str] = None) -> dict:
    """Compute the four pillar scores and the overall 0-100 Pulse Score."""
    ws = week_start or _latest_completed_monday()
    sc, rk, sla, st = (
        await _score_scorecard(db, ws),
        await _score_rocks(db),
        await _score_sla(db),
        await _score_students(db),
    )
    total = sc["score"] + rk["score"] + sla["score"] + st["score"]
    return {
        "score": total,
        "label": _label_for_score(total),
        "week_start": ws,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "pillars": {
            "scorecard": sc,
            "rocks": rk,
            "sla": sla,
            "students": st,
        },
    }
