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
