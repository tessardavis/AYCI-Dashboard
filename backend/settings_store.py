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


# ---- Active quarter (for rock archiving) -------------------------------
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
