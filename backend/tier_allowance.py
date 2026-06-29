"""
Single source of truth for a student's private-video allowance by tier.

Used by both the Students DB (the allowance column + missing/mismatch flags)
and the Private-Tier Videos board (the "X / Y" counter). Kept in its own module
so neither imports the other.
"""
from __future__ import annotations

from typing import Optional

# Confirmed allowances (Tessa, 29 Jun 2026): VIP 30, Private Plus 15.
# B&G 5 / B&G Plus 10. Base Academy / Silver / Gold / Platinum / 1:1 have no
# defined private-video allowance (they're not on the board).
_VIDEO_ALLOWANCE_BY_TIER = {
    "academy private plus": 15, "upgrade private plus": 15, "private plus": 15,
    "vip": 30, "upgrade vip": 30,
    "boost & go": 5, "boost & go plus": 10,
}


def expected_video_allowance(tier: Optional[str], boost: Optional[str]) -> Optional[int]:
    """Expected private video allowance from tier, or None if the tier/B&G
    doesn't have a defined allowance (e.g. base Academy, or 1:1/Platinum)."""
    t = (tier or "").strip().lower()
    if t in _VIDEO_ALLOWANCE_BY_TIER:
        return _VIDEO_ALLOWANCE_BY_TIER[t]
    b = (boost or "").strip().lower()
    if "b&g" in b or b == "upgraded":
        return 10 if "plus" in b else 5
    return None


def effective_video_allowance(tier, boost, manual) -> Optional[int]:
    """The allowance to actually SHOW for a student.

    Rule (Tessa, 29 Jun 2026): the tier number is the default. A manually-set
    allowance only wins when it's a genuine top-up ABOVE the tier default
    (e.g. Richard, a VIP given 45). A stored value at-or-below the tier default
    is treated as stale/broken Monday data and replaced by the tier number
    (so e.g. a Private Plus showing 0 becomes 15). Computed live - no migration.
    """
    exp = expected_video_allowance(tier, boost)
    try:
        m = int(manual) if manual not in (None, "") else None
    except (TypeError, ValueError):
        m = None
    if exp is None:
        return m  # no tier default - honour any manual value
    if m is not None and m > exp:
        return m  # genuine top-up wins
    return exp
