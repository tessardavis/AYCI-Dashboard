"""Unit tests for leaderboard.member_badge_score (no DB needed).

The scoring rule is: score = count of member_tags NOT in the explicit
EXCLUDED_TAGS set (cohort + tier + specialty + ops tags)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from leaderboard import (
    member_badge_score,
    member_badges,
    _is_excluded,
    EXCLUDED_TAGS,
)


def test_exclusion_coverage():
    # Spot-check every category is in the set
    for t in (
        "Apr '26", "Feb '26", "Sep '25", "April '25", "Legacy Cohort",
        "VIP", "Private Tier", "Private Plus", "Platinum", "Gold", "1:1", "Boost & Go",
        "Surgery", "Radiology", "Paeds", "ED", "Breast surgery", "Anaesthetics",
        "Coach", "Circle Member", "Academy Member", "Autoreply hold", "Interview week",
        "Deep Dive 5", "Boss", "Fast Track", "Sep-25 early",
    ):
        assert _is_excluded(t), f"{t!r} should be excluded"


def test_non_excluded_tags_count():
    # Tags NOT in the list → counted as badges
    for t in ("Verified!", "Daily Prep", "Video Course Legend", "Baseline TMAY",
              "USP Guru", "Verified Community Member"):
        assert not _is_excluded(t), f"{t!r} should NOT be excluded"


def test_score_ignores_excluded():
    tags = [
        {"name": "Apr '26"}, {"name": "VIP"}, {"name": "Paeds"}, {"name": "Boss"},
        {"name": "Verified!"}, {"name": "Daily Prep"}, {"name": "Baseline TMAY"},
    ]
    # 3 real badges (Verified!, Daily Prep, Baseline TMAY), rest all excluded
    assert member_badge_score(tags) == 3
    assert member_badges(tags) == ["Baseline TMAY", "Daily Prep", "Verified!"]


def test_score_zero_for_excluded_only():
    tags = [{"name": "Apr '26"}, {"name": "VIP"}, {"name": "Paeds"}, {"name": "Coach"}]
    assert member_badge_score(tags) == 0
    assert member_badges(tags) == []


def test_case_insensitive_exclusion():
    tags = ["apr '26", "VIP", "paeds"]
    assert member_badge_score(tags) == 0


def test_handles_empty_and_none():
    assert member_badge_score([]) == 0
    assert member_badge_score(None) == 0
    assert member_badge_score([{"name": ""}, {"name": None}]) == 0


def test_accepts_str_list_shape():
    """circle_members_cache stores tags as list[str], not list[dict]."""
    tags = ["Apr '26", "Verified!", "Daily Prep"]
    assert member_badge_score(tags) == 2
    assert member_badges(tags) == ["Daily Prep", "Verified!"]


def test_exclusion_set_size_matches_raw_list():
    """Guard against typos shrinking the exclusion set."""
    assert len(EXCLUDED_TAGS) == 44


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
