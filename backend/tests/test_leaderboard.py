"""Unit tests for leaderboard.member_badge_score (no DB needed)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from leaderboard import (
    member_badge_score,
    _is_cohort_tag,
    _is_private_tier_tag,
)


def test_cohort_tag_detection():
    assert _is_cohort_tag("Apr '26")
    assert _is_cohort_tag("Feb '26")
    assert _is_cohort_tag("April '25")
    assert _is_cohort_tag("Sep '24")
    assert _is_cohort_tag("AYGI 25/26")
    assert _is_cohort_tag("AYGI 25 VIP")
    assert _is_cohort_tag("RFI-1")
    assert _is_cohort_tag("RFI-5")
    assert _is_cohort_tag("Legacy Cohort")
    # not cohort
    assert not _is_cohort_tag("Verified!")
    assert not _is_cohort_tag("Boss")
    assert not _is_cohort_tag("Daily Prep")


def test_private_tier_detection():
    for t in ("VIP", "vip", "Private Tier", "Private Plus", "Platinum",
              "Gold", "1:1", "Boost & Go"):
        assert _is_private_tier_tag(t), f"{t} should be private tier"
    assert not _is_private_tier_tag("Academy Member")
    assert not _is_private_tier_tag("Circle Member")


def test_score_basic():
    # Mix of all categories — only "Verified!" + "Daily Prep" + "Boss" count
    tags_dict = [
        {"name": "Apr '26"},        # cohort -> excluded
        {"name": "VIP"},             # private tier -> excluded
        {"name": "Verified!"},       # badge
        {"name": "Daily Prep"},      # badge
        {"name": "Boss"},            # badge
    ]
    assert member_badge_score(tags_dict) == 3

    # Same data, but as list[str] (slim cache shape)
    tags_str = ["Apr '26", "VIP", "Verified!", "Daily Prep", "Boss"]
    assert member_badge_score(tags_str) == 3


def test_score_no_badges_only_cohort_and_tier():
    tags = [{"name": "Apr '26"}, {"name": "Private Tier"}, {"name": "Platinum"}]
    assert member_badge_score(tags) == 0


def test_score_handles_empty_and_blank():
    assert member_badge_score([]) == 0
    assert member_badge_score(None) == 0
    assert member_badge_score([{"name": ""}, {"name": None}]) == 0


def test_specialty_tags_count_as_badges():
    """Tessa explicitly named only cohort + private-tier as exclusions, so
    speciality / 'Verified!' / engagement tags all count as badges."""
    tags = ["Paeds", "Anaesthetics ", "Verified!", "Apr '26"]
    assert member_badge_score(tags) == 3


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
