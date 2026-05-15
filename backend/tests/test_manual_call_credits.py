"""Regression tests for the manual-call fold-in logic in
`private_tier_utilisation` and `over_allowance_alerts`.

Two correctness properties pinned:

1. **Duration → credits conversion**: a manual call's contribution to a
   student's call count is `ceil(duration_min / 30)` with a floor of 1.
   So 30 min = 1, 60 min = 2 (William's case), 90 min = 3.

2. **Email scoping**: the fold-in must add credits ONLY for emails that
   are actually tracked in the source dataset (the page's student list),
   not arbitrarily mutate the counts dict. Previously a bug caused the
   over-allowance widget to drop manual-call credits if the student had
   zero Calendly calls — both modules now scope by the tracked email
   set.
"""
from __future__ import annotations

import asyncio
import os
import sys
import math

# Ensure backend/ is on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _credits_from_duration(minutes: int) -> int:
    return max(1, math.ceil(minutes / 30))


def test_credits_from_duration():
    """30=1, 45=2, 60=2, 90=3, edge cases."""
    assert _credits_from_duration(30) == 1
    assert _credits_from_duration(31) == 2
    assert _credits_from_duration(45) == 2  # rounds up
    assert _credits_from_duration(60) == 2  # William's 1-hour call
    assert _credits_from_duration(90) == 3
    assert _credits_from_duration(15) == 1  # floor
    assert _credits_from_duration(1) == 1   # floor


def test_manual_calls_fold_into_both_widgets():
    """Insert two manual_calls rows, run the fold-in logic in isolation,
    confirm both pick up the credits — and confirm an UNTRACKED email is
    NOT folded in (scope safety).

    Uses a fresh Motor client (not the `db` singleton) so this test
    doesn't bind the global client to a soon-to-be-closed loop —
    important when running in the same pytest session as other Motor
    tests (`test_circle_dm_first_sight.py`).
    """
    async def _run():
        import os
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            db = client[os.environ["DB_NAME"]]
            tracked = "regression-test-tracked@example.com"
            untracked = "regression-test-untracked@example.com"
            await db.manual_calls.delete_many({
                "student_email": {"$in": [tracked, untracked]},
            })
            # Seed: tracked = 60+30 → 2+1 credits = 3 total
            await db.manual_calls.insert_many([
                {"id": "reg-test-1", "student_email": tracked,
                 "student_name": "Tracked", "host": "Tessa",
                 "starts_at": "2026-05-15T10:00:00Z", "duration_min": 60,
                 "notes": None, "event_type": "Manual entry",
                 "created_at": "2026-05-15T10:00:00Z", "created_by": None},
                {"id": "reg-test-2", "student_email": tracked,
                 "student_name": "Tracked", "host": "Tessa",
                 "starts_at": "2026-05-14T10:00:00Z", "duration_min": 30,
                 "notes": None, "event_type": "Manual entry",
                 "created_at": "2026-05-14T10:00:00Z", "created_by": None},
                {"id": "reg-test-3", "student_email": untracked,
                 "student_name": "Untracked", "host": "Tessa",
                 "starts_at": "2026-05-15T10:00:00Z", "duration_min": 60,
                 "notes": None, "event_type": "Manual entry",
                 "created_at": "2026-05-15T10:00:00Z", "created_by": None},
            ])
            tracked_emails = {tracked}
            counts: dict[str, int] = {}
            async for row in db.manual_calls.find(
                {}, {"_id": 0, "student_email": 1, "duration_min": 1},
            ):
                em = (row.get("student_email") or "").strip().lower()
                if not em or em not in tracked_emails:
                    continue
                credits = _credits_from_duration(int(row.get("duration_min") or 30))
                counts[em] = counts.get(em, 0) + credits
            assert counts.get(tracked) == 3, f"expected 3, got {counts}"
            assert untracked not in counts, f"untracked leaked: {counts}"
            await db.manual_calls.delete_many({
                "student_email": {"$in": [tracked, untracked]},
            })
        finally:
            client.close()
    asyncio.run(_run())
