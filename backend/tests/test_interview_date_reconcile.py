"""
Unit tests for interview_date_reconcile._latest_tally_date — the rule that
decides which Tally submission's date becomes authoritative.

Critical: "most recent SUBMISSION wins" (by submitted_at), NOT "soonest/latest
date". A reschedule to an earlier-but-future date must still be adopted because
it was submitted last.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interview_date_reconcile import _latest_tally_date, _valid_date


def _sub(date, submitted_at):
    return {"date": date, "submitted_at": submitted_at}


def test_picks_most_recent_submission_even_if_earlier_date():
    # Older submission has a LATER date; newer submission has an earlier (still
    # future) date. The newer SUBMISSION must win.
    history = [
        _sub("2026-09-01", "2026-05-01T10:00:00Z"),  # submitted first, later date
        _sub("2026-07-09", "2026-06-08T10:00:00Z"),  # submitted last, earlier date
    ]
    assert _latest_tally_date(history) == "2026-07-09"


def test_order_in_list_does_not_matter():
    # Same data, reversed list order — still keyed off submitted_at.
    history = [
        _sub("2026-07-09", "2026-06-08T10:00:00Z"),
        _sub("2026-09-01", "2026-05-01T10:00:00Z"),
    ]
    assert _latest_tally_date(history) == "2026-07-09"


def test_skips_invalid_dates_falls_to_next_submission():
    history = [
        _sub("", "2026-06-10T10:00:00Z"),            # latest submission, no date
        _sub("not-a-date", "2026-06-09T10:00:00Z"),  # invalid
        _sub("2026-07-09", "2026-06-08T10:00:00Z"),  # newest valid
    ]
    assert _latest_tally_date(history) == "2026-07-09"


def test_no_history_is_none():
    assert _latest_tally_date([]) is None
    assert _latest_tally_date(None) is None


def test_past_date_latest_submission_is_still_adopted():
    # Reconcile reflects the true latest date even if past; downstream date
    # filters (night-before/upcoming) handle past dates themselves.
    history = [_sub("2026-01-05", "2026-01-02T10:00:00Z")]
    assert _latest_tally_date(history) == "2026-01-05"


def test_valid_date_truncates_and_parses():
    assert _valid_date("2026-07-09T00:00:00") == "2026-07-09"
    assert _valid_date("2026-07-09") == "2026-07-09"
    assert _valid_date("") is None
    assert _valid_date(None) is None
    assert _valid_date("nope") is None
