"""Regression tests for `circle_dm_poll._process_thread()` first-sight logic.

Two correctness requirements pinned forever:

1. **Backlog protection**: when a thread is first observed AND the inline
   last_message is anything older than 10 minutes OR sent by the admin
   (i.e. the coach's own reply), the bot must NOT reply on this poll. It
   should seed `last_seen_message_id` and return `{seeded: <uuid>}`.

2. **Fresh-student bypass**: when a thread is first observed AND the
   inline last_message is a *student* message younger than 10 minutes,
   the bot must NOT swallow it — it should minimally-seed state and fall
   through to the normal reply path. This fixes the "I sent a test DM
   and got nothing" UX.

These tests run against the live MongoDB the backend uses, with Circle
and Claude calls mocked, so no external traffic is generated. Uses plain
`asyncio.run()` instead of pytest-asyncio (not installed) so it runs in
the existing pytest environment unchanged.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

# Ensure backend/ is on the path before importing the module under test.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import circle_dm_poll  # noqa: E402
from db import db  # noqa: E402


ADMIN_ID = 999_111
STUDENT_ID = 999_222
COACH_EMAIL = "first-sight-test@example.com"
COACH_NAME = "Test Coach"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _thread(uuid: str, last_message: dict) -> dict:
    return {
        "chat_room_uuid": uuid,
        "chat_room": {"kind": "direct"},
        "other_participants_preview": [{
            "community_member_id": STUDENT_ID,
            "name": "Test Student",
        }],
        "last_message": last_message,
    }


def _msg(*, mid: int, sender_id: int, body: str, created_at: datetime) -> dict:
    return {
        "id": mid,
        "sender": {"community_member_id": sender_id, "name": "S"},
        "body": body,
        "created_at": _iso(created_at),
    }


async def _cleanup():
    await db.circle_dm_threads.delete_many({
        "id": {"$regex": "^thread:first-sight-test-"},
    })
    await db.tickets.delete_one({"id": "tkt-first-sight-test"})


async def _scenario_admin_message():
    """Inline last_message from the admin → bot must seed and NOT reply."""
    uuid = "first-sight-test-admin"
    now = datetime.now(timezone.utc)
    thread = _thread(uuid, _msg(
        mid=1001, sender_id=ADMIN_ID, body="hello there",
        created_at=now - timedelta(minutes=1),  # fresh, but admin
    ))
    res = await circle_dm_poll._process_thread(
        db, admin_email=COACH_EMAIL, admin_member_id=ADMIN_ID,
        coach_name=COACH_NAME, thread=thread, excluded_tags_lower=set(),
    )
    assert res == {"seeded": uuid}, f"admin: expected seeded, got {res}"
    state = await db.circle_dm_threads.find_one({"id": f"thread:{uuid}"}, {"_id": 0})
    assert state is not None
    assert state["state"] == "active"
    assert state["last_seen_message_id"] == 1001
    assert state.get("first_sight_replied") is not True


async def _scenario_old_student_message():
    """Inline last_message is a student message but >10 min old → seed only."""
    uuid = "first-sight-test-old-student"
    now = datetime.now(timezone.utc)
    thread = _thread(uuid, _msg(
        mid=2001, sender_id=STUDENT_ID, body="old question",
        created_at=now - timedelta(hours=2),  # stale → backlog
    ))
    res = await circle_dm_poll._process_thread(
        db, admin_email=COACH_EMAIL, admin_member_id=ADMIN_ID,
        coach_name=COACH_NAME, thread=thread, excluded_tags_lower=set(),
    )
    assert res == {"seeded": uuid}, f"old: expected seeded, got {res}"
    state = await db.circle_dm_threads.find_one({"id": f"thread:{uuid}"}, {"_id": 0})
    assert state["last_seen_message_id"] == 2001
    assert state.get("first_sight_replied") is not True


async def _scenario_fresh_student_message():
    """Inline last_message is a student msg <10 min old → fall through and
    attempt a real reply. Circle + Claude calls are mocked."""
    uuid = "first-sight-test-fresh-student"
    now = datetime.now(timezone.utc)
    fresh_msg = _msg(
        mid=3001, sender_id=STUDENT_ID,
        body="What time is the session today?",
        created_at=now - timedelta(seconds=30),
    )
    thread = _thread(uuid, fresh_msg)
    posted_reply = {
        "id": 3002,
        "sender": {"community_member_id": ADMIN_ID, "name": COACH_NAME},
        "body": "Hi! Sessions are at 7pm UK.",
        "created_at": _iso(now),
    }
    with patch(
        "circle_api.list_thread_messages_for_admin",
        new=AsyncMock(return_value=[fresh_msg]),
    ), patch(
        "circle_api.post_dm_message",
        new=AsyncMock(return_value=posted_reply),
    ), patch(
        "circle_dm_bot._get_playbook",
        new=AsyncMock(return_value="Q&A: sessions are at 7pm UK."),
    ), patch(
        "circle_dm_bot._generate_reply",
        new=AsyncMock(return_value={
            "reply": "Hi! Sessions are at 7pm UK.",
            "resolved": True,
        }),
    ), patch(
        "circle_dm_bot._create_ticket_from_dm",
        new=AsyncMock(return_value="tkt-first-sight-test"),
    ):
        res = await circle_dm_poll._process_thread(
            db, admin_email=COACH_EMAIL, admin_member_id=ADMIN_ID,
            coach_name=COACH_NAME, thread=thread,
            excluded_tags_lower=set(),
        )
    assert "replied" in res, f"fresh: expected replied, got {res}"
    assert res["replied"] == uuid
    state = await db.circle_dm_threads.find_one({"id": f"thread:{uuid}"}, {"_id": 0})
    assert state["state"] == "active"
    # The audit marker is set during the initial minimal-seed write; the
    # subsequent successful-reply write doesn't unset it.
    assert state.get("first_sight_replied") is True
    assert state["ai_reply_count_today"] == 1
    assert 3002 in (state.get("sent_message_ids") or [])


def test_first_sight_logic_all_scenarios():
    """All three first-sight scenarios in a single asyncio.run() (motor
    binds to the first loop, so we can't safely call asyncio.run twice)."""
    async def _run_all():
        try:
            await _cleanup()
            await _scenario_admin_message()
            await _cleanup()
            await _scenario_old_student_message()
            await _cleanup()
            await _scenario_fresh_student_message()
        finally:
            await _cleanup()
    asyncio.run(_run_all())
