"""
Spotlight leaderboard scoring based on Circle "badges" (member_tags).

Definition (per Tessa):
    score = (count of member_tags) - (cohort tags) - (private-tier tags)

Only members carrying the active cohort tag (e.g. "Apr '26") have a score; the
rest are treated as not-on-leaderboard (None).

Cohort tags
-----------
Tags whose name looks like a cohort marker. Heuristics:
  - Matches /^[A-Za-z]+ '\d{2}$/   e.g. "Apr '26", "Feb '26", "April '25"
  - Starts with "AYGI"             e.g. "AYGI 25/26", "AYGI 25 VIP"
  - Starts with "RFI-"             e.g. "RFI-1" through "RFI-5"
  - Equals "Legacy Cohort"

Private-tier tags
-----------------
Hard-coded set: VIP, Private Tier, Private Plus, Platinum, Gold, 1:1, Boost & Go
"""
from __future__ import annotations

import re

PRIVATE_TIER_TAGS = {
    "vip",
    "private tier",
    "private plus",
    "platinum",
    "gold",
    "1:1",
    "boost & go",
}

_COHORT_DATE_RE = re.compile(r"^[A-Za-z]+\s*'\d{2}$")


def _is_cohort_tag(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    if _COHORT_DATE_RE.match(n):
        return True
    low = n.lower()
    if low.startswith("aygi"):
        return True
    if low.startswith("rfi-"):
        return True
    if low == "legacy cohort":
        return True
    return False


def _is_private_tier_tag(name: str) -> bool:
    return (name or "").strip().lower() in PRIVATE_TIER_TAGS


def _tag_name(t) -> str:
    """`member_tags` may be list[dict] (full Circle response) or list[str]
    (the slim cache in `circle_members_cache`). Normalise to a string."""
    if isinstance(t, dict):
        return (t.get("name") or "").strip()
    return str(t or "").strip()


def member_badge_score(member_tags: list) -> int:
    """Count badges = total tags - cohort tags - private-tier tags."""
    total = 0
    for t in member_tags or []:
        name = _tag_name(t)
        if not name:
            continue
        if _is_cohort_tag(name) or _is_private_tier_tag(name):
            continue
        total += 1
    return total


async def build_leaderboard_index(db, cohort_tag: str = "Apr '26") -> dict[str, int]:
    """Return `{name_key_lowercased: badge_score}` for every Circle member with
    the given cohort tag. Uses the existing `circle_members_cache` populated
    by `student_lookup._circle_get_cached_members` — note that cache stores
    `member_tags` as list[str] (just tag names), so we accept either shape.
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
        # Also index by first word so spotlight first-name-only fallback works
        first_word = flat_name.split(" ")[0] if flat_name else ""
        if first_word and first_word != flat_name:
            # Only set if we haven't seen this first-word yet (avoid clashes
            # silently — spotlight only consults this when interview index says
            # name was unambiguous on the interview form, which is enough)
            out.setdefault(first_word, score)
    return out


def member_badges(member_tags: list) -> list[str]:
    """Return the individual badge names — tags minus cohort tags minus private
    tier tags. Sorted alphabetically for consistent UI rendering."""
    out: list[str] = []
    for t in member_tags or []:
        name = _tag_name(t)
        if not name:
            continue
        if _is_cohort_tag(name) or _is_private_tier_tag(name):
            continue
        out.append(name)
    return sorted(set(out), key=lambda s: s.lower())


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
