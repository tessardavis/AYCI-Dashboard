"""
App-wide editable settings stored in MongoDB `app_settings` collection.
Keyed by `_id` (string). Currently used for cohort milestones.
"""
from __future__ import annotations

DEFAULT_COHORT_MILESTONES = [
    "USP Guru",
    "Verified Examples Badge",
    "Senior-Level Thinker",
    "Job Mastermind",
    "Authentic Self",
]


async def get_cohort_milestones(db) -> list[str]:
    doc = await db.app_settings.find_one({"_id": "cohort_milestones"}, {"_id": 0})
    if not doc or not doc.get("milestones"):
        return list(DEFAULT_COHORT_MILESTONES)
    ms = doc["milestones"]
    if not isinstance(ms, list) or len(ms) != 5:
        return list(DEFAULT_COHORT_MILESTONES)
    return [str(m).strip() for m in ms]


async def set_cohort_milestones(db, milestones: list[str]) -> list[str]:
    if not isinstance(milestones, list) or len(milestones) != 5:
        raise ValueError("Exactly 5 milestone names are required")
    cleaned = [str(m).strip() for m in milestones]
    if any(not m for m in cleaned):
        raise ValueError("Milestone names cannot be empty")
    await db.app_settings.update_one(
        {"_id": "cohort_milestones"},
        {"$set": {"milestones": cleaned}},
        upsert=True,
    )
    return cleaned


# ---- Coach Activity Circle space IDs (per cohort, admin-editable) -------
DEFAULT_COACH_SPACES = {
    "recorded_answer_space_id": 2529508,    # /c/recorded-answer-review-apr-26/
    "interview_support_space_id": 2529509,  # /c/specific-interview-support-apr-26/
    "recorded_answer_start": "2026-04-04",
    "interview_support_start": "2026-04-23",
}


async def get_coach_spaces(db) -> dict:
    """Return current Coach Activity space IDs + start dates. Falls back to
    sensible defaults if the setting hasn't been configured yet."""
    doc = await db.app_settings.find_one({"_id": "coach_spaces"}, {"_id": 0})
    merged = dict(DEFAULT_COACH_SPACES)
    if doc:
        merged.update({k: v for k, v in doc.items() if v is not None})
    try:
        merged["recorded_answer_space_id"] = int(merged["recorded_answer_space_id"])
        merged["interview_support_space_id"] = int(merged["interview_support_space_id"])
    except (TypeError, ValueError):
        merged["recorded_answer_space_id"] = DEFAULT_COACH_SPACES["recorded_answer_space_id"]
        merged["interview_support_space_id"] = DEFAULT_COACH_SPACES["interview_support_space_id"]
    return merged


async def set_coach_spaces(db, payload: dict) -> dict:
    allowed = set(DEFAULT_COACH_SPACES.keys())
    update = {k: v for k, v in payload.items() if k in allowed and v is not None}
    if not update:
        raise ValueError("No valid fields supplied")
    for k in ("recorded_answer_space_id", "interview_support_space_id"):
        if k in update:
            try:
                update[k] = int(update[k])
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be an integer")
    await db.app_settings.update_one(
        {"_id": "coach_spaces"},
        {"$set": update},
        upsert=True,
    )
    return await get_coach_spaces(db)


async def get_active_quarter(db, fallback_quarters: list[str] | None = None) -> str | None:
    """Returns the current active quarter ID (e.g. 'Q2 2026'), or the most
    recent quarter from `fallback_quarters` if no setting exists yet."""
    doc = await db.app_settings.find_one({"_id": "active_quarter"}, {"_id": 0})
    if doc and doc.get("quarter"):
        return doc["quarter"]
    if fallback_quarters:
        return fallback_quarters[0]  # caller passes already-sorted-desc list
    quarters = await db.rocks.distinct("quarter")
    if quarters:
        return sorted(quarters, reverse=True)[0]
    return None


async def set_active_quarter(db, quarter: str) -> str:
    quarter = quarter.strip()
    await db.app_settings.update_one(
        {"_id": "active_quarter"},
        {"$set": {"quarter": quarter}},
        upsert=True,
    )
    return quarter
