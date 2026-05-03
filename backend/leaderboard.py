"""
Spotlight leaderboard scoring based on Circle "badges" (member_tags).

Definition (per Tessa 03-May):
    score = count of member_tags that are NOT in the exclusion set below.

The exclusion set covers cohort markers, private tiers, specialty tags, and
operational/status tags. Anything else counts as a badge.
"""
from __future__ import annotations

import re


# Explicit exclusion list from Tessa (case-insensitive match). Keep whitespace
# stripped; we compare lower() to lower().
EXCLUDED_TAGS_RAW = [
    "Private Tier",
    "VIP",
    "Sep '25",
    "July '25",
    "Surgery",
    "Radiology",
    "Paeds",
    "Ortho",
    "Ophthalmology",
    "Obs & Gynae",
    "ED",
    "Breast surgery",
    "Anaesthetics",
    "Deep Dive 5",
    "Gold",
    "Platinum",
    "1:1",
    "Private Plus",
    "Coach",
    "Circle Member",
    "April '25",
    "Feb '25",
    "Nov '24",
    "Sep '24",
    "July '24",
    "Nov '25",
    "Fast Track",
    "May '24",
    "Jan '24",
    "March '24",
    "Legacy Cohort",
    "Boss",
    "Feb '26",
    "Autoreply hold",
    "Interview week",
    "Boost & Go",
    "Academy Member",
    "Sep-25 early",
    "Apr '26",
]
EXCLUDED_TAGS = {t.strip().lower() for t in EXCLUDED_TAGS_RAW}


def _is_excluded(name: str) -> bool:
    return (name or "").strip().lower() in EXCLUDED_TAGS


def _tag_name(t) -> str:
    """`member_tags` may be list[dict] (full Circle response) or list[str]
    (the slim cache in `circle_members_cache`). Normalise to a string."""
    if isinstance(t, dict):
        return (t.get("name") or "").strip()
    return str(t or "").strip()


def member_badge_score(member_tags: list) -> int:
    """Count badges = total tags - excluded tags."""
    return len(member_badges(member_tags))


def member_badges(member_tags: list) -> list[str]:
    """Return the individual badge names — tags minus the excluded set.
    Sorted alphabetically for consistent UI rendering."""
    out: list[str] = []
    for t in member_tags or []:
        name = _tag_name(t)
        if not name or _is_excluded(name):
            continue
        out.append(name)
    return sorted(set(out), key=lambda s: s.lower())


async def build_leaderboard_index(db, cohort_tag: str = "Apr '26") -> dict[str, int]:
    """Return `{name_key_lowercased: badge_score}` for every Circle member with
    the given cohort tag. Used by the Spotlight board's "× badges" chip.
    """
    doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
    if not doc:
        return {}
    target = cohort_tag.strip().lower()
    out: dict[str, int] = {}
    for m in doc.get("members") or []:
        tags = m.get("member_tags") or []
        names = {_tag_name(t).lower() for t in tags}
        if target not in names:
            continue
        score = member_badge_score(tags)
        flat_name = re.sub(r"\s+", " ", (m.get("name") or "").strip().lower())
        if flat_name:
            out[flat_name] = max(out.get(flat_name, 0), score)
        first_word = flat_name.split(" ")[0] if flat_name else ""
        if first_word and first_word != flat_name:
            out.setdefault(first_word, score)
    return out


async def get_top_leaderboard(db, cohort_tag: str = "Apr '26", limit: int = 25) -> list[dict]:
    """Top-`limit` members on the cohort leaderboard."""
    doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
    if not doc:
        return []
    target = cohort_tag.strip().lower()
    rows: list[dict] = []
    for m in doc.get("members") or []:
        tags = m.get("member_tags") or []
        names = {_tag_name(t).lower() for t in tags}
        if target not in names:
            continue
        badges = member_badges(tags)
        rows.append({
            "name": m.get("name"),
            "email": (m.get("email") or "").lower(),
            "avatar_url": m.get("avatar_url"),
            "score": len(badges),
            "badges": badges,
        })
    rows.sort(key=lambda r: (-r["score"], (r.get("name") or "").lower()))
    return rows[:limit]
