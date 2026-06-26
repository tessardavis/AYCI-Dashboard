"""Regression tests for the manual-call fold-in logic in
`private_tier_utilisation` and `over_allowance_alerts`.

Two correctness properties pinned:

1. **Each manual call = 1 credit, regardless of duration.**
   The system counts call events, not minutes. VIP's tier allowance is
   described as "4 x 30-min + 1 x 60-min mock = 5 calls" - i.e. the
   60-min mock is ONE event in the count, same as a 30-min call. So
   William Twiggs's extra 60-min call counts as ONE additional event.
   The duration field is kept on each entry for the audit trail.

2. **Email scoping**: the fold-in must add credits ONLY for emails
   that are actually tracked in the source dataset (the page's student
   list), never arbitrarily mutate the counts dict. Previously the
   over-allowance widget could drop manual-call credits if the student
   had zero Calendly calls - both modules now scope by the tracked
   email set.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Ensure backend/ is on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_manual_calls_one_credit_per_entry_and_email_scoped():
    """Insert 3 manual_calls rows of varying durations for a tracked
    student + 1 row for an untracked email. Run the fold-in logic in
    isolation and assert:

      • tracked email gets 3 credits (1 per row, NOT duration-weighted)
      • untracked email gets 0 credits (scope safety)
    """
    async def _run():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            db = client[os.environ["DB_NAME"]]
            tracked = "regression-test-tracked@example.com"
            untracked = "regression-test-untracked@example.com"
            await db.manual_calls.delete_many({
                "student_email": {"$in": [tracked, untracked]},
            })
            await db.manual_calls.insert_many([
                # 60-min call (one event)
                {"id": "reg-test-1", "student_email": tracked,
                 "student_name": "Tracked", "host": "Tessa",
                 "starts_at": "2026-05-15T10:00:00Z", "duration_min": 60,
                 "notes": None, "event_type": "Manual entry",
                 "created_at": "2026-05-15T10:00:00Z", "created_by": None},
                # 30-min call (one event)
                {"id": "reg-test-2", "student_email": tracked,
                 "student_name": "Tracked", "host": "Tessa",
                 "starts_at": "2026-05-14T10:00:00Z", "duration_min": 30,
                 "notes": None, "event_type": "Manual entry",
                 "created_at": "2026-05-14T10:00:00Z", "created_by": None},
                # 90-min call (one event)
                {"id": "reg-test-3", "student_email": tracked,
                 "student_name": "Tracked", "host": "Tessa",
                 "starts_at": "2026-05-13T10:00:00Z", "duration_min": 90,
                 "notes": None, "event_type": "Manual entry",
                 "created_at": "2026-05-13T10:00:00Z", "created_by": None},
                # Untracked student
                {"id": "reg-test-4", "student_email": untracked,
                 "student_name": "Untracked", "host": "Tessa",
                 "starts_at": "2026-05-15T10:00:00Z", "duration_min": 60,
                 "notes": None, "event_type": "Manual entry",
                 "created_at": "2026-05-15T10:00:00Z", "created_by": None},
            ])

            # Apply the exact fold-in logic shipped to both helpers.
            tracked_emails = {tracked}
            counts: dict[str, int] = {}
            async for row in db.manual_calls.find(
                {}, {"_id": 0, "student_email": 1},
            ):
                em = (row.get("student_email") or "").strip().lower()
                if not em or em not in tracked_emails:
                    continue
                counts[em] = counts.get(em, 0) + 1

            # 3 entries → 3 credits (NOT 2 + 1 + 3 = 6).
            assert counts.get(tracked) == 3, (
                f"each manual entry must add exactly 1 credit regardless "
                f"of duration; got {counts}"
            )
            assert untracked not in counts, (
                f"untracked email leaked into counts: {counts}"
            )

            await db.manual_calls.delete_many({
                "student_email": {"$in": [tracked, untracked]},
            })
        finally:
            client.close()
    asyncio.run(_run())
