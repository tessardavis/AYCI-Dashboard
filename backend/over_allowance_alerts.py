"""
Over-Allowance Detection + Slack alerts.

A student is "over allowance" when the count of Calendly events booked
against the AYCI private 1:1 / VIP / Bonus / Mock event types EXCEEDS
the total slots tracked on their Monday Academy Members row (calls +
mocks + bonus columns combined).

This is a real-world issue because Monday allowance is updated manually
by the team — students can book ahead of the team marking the slot.

Detection flow (run by scheduler every 5 min):
  1. Pull all Private Plus / VIP rows from Monday (no interview-date filter).
  2. For each row, compute total slots = calls.total + mocks.total + bonus.total.
  3. For each row with email + total > 0, query Calendly for all-time
     scheduled events against PRIVATE_CALL_NAMES, group by invitee email.
  4. Compare calendly_count vs monday_total → if `>`, record breach.
  5. DM Oksana once per (email, over_by) pair. Re-DM only if over_by grows.

Surfaced in UI via `GET /api/coach-activity/over-allowance` (used by
Coach Activity panel + inline chip on Upcoming Interviews).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from connectors import (
    MONDAY_URL,
    _monday_headers,
    CALENDLY_BASE,
    _calendly_headers,
    TIMEOUT,
)
from upcoming_interviews import (
    ACADEMY_MEMBERS_BOARD_ID,
    COL_TIER,
    COL_EMAIL,
    COL_INTERVIEW_DATE,
    COL_SPECIALITY,
    COL_HOSPITAL,
    CALL_COLS,
    MOCK_COLS,
    BONUS_COLS,
    _allowance,
)
from private_tier_utilisation import (
    _normalise_tier,
    PRIVATE_CALL_NAMES,
)

logger = logging.getLogger(__name__)

OVER_ALLOWANCE_CACHE_KEY = "over_allowance_snapshot"
SENT_COLLECTION = "over_allowance_alerts_sent"


async def _fetch_all_private_students() -> list[dict]:
    """All Private Plus / VIP students on Monday, regardless of interview
    date. Returns name, email, tier, monday_url, and totals from the
    call/mock/bonus columns."""
    column_ids = [COL_TIER, COL_EMAIL, COL_INTERVIEW_DATE, COL_SPECIALITY, COL_HOSPITAL] + [
        c for c, _ in CALL_COLS + MOCK_COLS + BONUS_COLS
    ]
    q = """
    query ($boardId: ID!, $cursor: String) {
      boards(ids: [$boardId]) {
        items_page(limit: 200, cursor: $cursor) {
          cursor
          items {
            id name url
            column_values(ids: %s) { id text }
          }
        }
      }
    }
    """ % ("[" + ",".join(f'"{cid}"' for cid in column_ids) + "]")

    items: list[dict] = []
    cursor: Optional[str] = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for _ in range(50):  # safety
            r = await c.post(
                MONDAY_URL,
                headers={**_monday_headers(), "Content-Type": "application/json"},
                json={"query": q, "variables": {"boardId": str(ACADEMY_MEMBERS_BOARD_ID), "cursor": cursor}},
            )
            r.raise_for_status()
            body = r.json()
            page = (body.get("data", {}).get("boards") or [{}])[0].get("items_page") or {}
            items.extend(page.get("items") or [])
            cursor = page.get("cursor")
            if not cursor:
                break

    out: list[dict] = []
    for it in items:
        cols_by_id = {cv.get("id"): cv for cv in (it.get("column_values") or [])}
        tier = _normalise_tier((cols_by_id.get(COL_TIER, {}).get("text") or "").strip())
        if not tier:
            continue
        email = ((cols_by_id.get(COL_EMAIL, {}).get("text") or "").lower().strip())
        if not email:
            continue
        calls = _allowance(cols_by_id, CALL_COLS)
        mocks = _allowance(cols_by_id, MOCK_COLS)
        bonus = _allowance(cols_by_id, BONUS_COLS)
        total = calls["total"] + mocks["total"] + bonus["total"]
        if total <= 0:
            continue  # no per-student allowance configured — skip
        out.append({
            "monday_id": it.get("id"),
            "monday_url": it.get("url"),
            "name": it.get("name"),
            "email": email,
            "tier": tier,
            "interview_date": (cols_by_id.get(COL_INTERVIEW_DATE, {}).get("text") or "").split(" ")[0] or None,
            "speciality": cols_by_id.get(COL_SPECIALITY, {}).get("text") or "",
            "hospital": cols_by_id.get(COL_HOSPITAL, {}).get("text") or "",
            "monday_calls_total": calls["total"],
            "monday_mocks_total": mocks["total"],
            "monday_bonus_total": bonus["total"],
            "monday_total_allowance": total,
        })
    return out


async def _count_calendly_alltime(emails: list[str]) -> dict[str, int]:
    """For each email, count Calendly scheduled events whose event-type name
    matches one of PRIVATE_CALL_NAMES. No min/max time filter = all-time."""
    if not emails:
        return {}
    out: dict[str, int] = {e: 0 for e in emails}
    if not os.environ.get("CALENDLY_TOKEN"):
        return out

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        try:
            me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
            me.raise_for_status()
            org = me.json().get("resource", {}).get("current_organization")
        except Exception as e:
            logger.warning(f"[over-allowance] calendly /users/me failed: {e}")
            return out
        if not org:
            return out

        sem = asyncio.Semaphore(6)

        async def _per_email(em: str) -> tuple[str, int]:
            async with sem:
                count = 0
                pt: Optional[str] = None
                pages = 0
                while pages < 20:  # safety: cap at 2000 events
                    p: dict = {
                        "organization": org,
                        "invitee_email": em,
                        "count": 100,
                        "status": "active",
                    }
                    if pt:
                        p["page_token"] = pt
                    try:
                        rr = await c.get(f"{CALENDLY_BASE}/scheduled_events", headers=_calendly_headers(), params=p)
                    except Exception:
                        break
                    if rr.status_code != 200:
                        break
                    bb = rr.json()
                    for ev in bb.get("collection", []):
                        nm = (ev.get("name") or "").lower()
                        if any(t.lower() in nm for t in PRIVATE_CALL_NAMES):
                            count += 1
                    pt = (bb.get("pagination") or {}).get("next_page_token")
                    pages += 1
                    if not pt:
                        break
                return em, count

        results = await asyncio.gather(*(_per_email(em) for em in emails if em))
        out.update(dict(results))
    return out


async def find_over_allowance_students(db) -> dict:
    """Returns {"computed_at", "students": [...]} for students whose
    Calendly all-time private-call count exceeds Monday's total allowance.
    Excludes (email, over_by) pairs that the team has acknowledged — the row
    re-appears if `over_by` grows further (e.g. +1 → +2 over)."""
    students = await _fetch_all_private_students()
    emails = [s["email"] for s in students if s.get("email")]
    counts = await _count_calendly_alltime(emails)

    # Add manually-logged extra calls (off-Calendly bookings added via
    # `/api/today-calls/manual`) to each student's used-count. Each entry
    # contributes `ceil(duration_min / 30)` credits — so a 30-min call = 1,
    # a 60-min call = 2.
    try:
        import math
        tracked_emails = {e.strip().lower() for e in emails if e}
        async for row in db.manual_calls.find(
            {}, {"_id": 0, "student_email": 1, "duration_min": 1},
        ):
            em = (row.get("student_email") or "").strip().lower()
            if not em or em not in tracked_emails:
                continue
            credits = max(1, math.ceil(int(row.get("duration_min") or 30) / 30))
            counts[em] = counts.get(em, 0) + credits
    except Exception as e:
        logger.warning(f"[over-allowance] manual_calls fold-in failed: {e}")

    # Acknowledgements: per-email max over_by that was acked. A row stays
    # hidden until the student goes over by more than the acked count.
    acked: dict[str, int] = {}
    async for d in db.over_allowance_acks.find({}, {"_id": 0, "email": 1, "over_by": 1}):
        em = (d.get("email") or "").lower()
        n = int(d.get("over_by") or 0)
        if not em:
            continue
        acked[em] = max(acked.get(em, 0), n)

    over: list[dict] = []
    for s in students:
        used = counts.get(s["email"], 0)
        allow = s["monday_total_allowance"]
        if used > allow:
            over_by = used - allow
            if over_by <= acked.get(s["email"], 0):
                continue  # already acknowledged at this severity
            over.append({
                **s,
                "calendly_calls_used": used,
                "over_by": over_by,
            })
    over.sort(key=lambda r: (-r["over_by"], r["name"] or ""))
    return {"computed_at": datetime.now(timezone.utc).isoformat(), "students": over}


async def acknowledge_over_allowance(
    db, *, email: str, over_by: int, by_user_id: str | None, by_name: str | None,
) -> dict:
    """Record an acknowledgement. The widget hides this student until their
    `over_by` exceeds `over_by` again (e.g. acked at +1, re-surfaces at +2)."""
    email = (email or "").strip().lower()
    over_by = int(over_by or 0)
    if not email or over_by <= 0:
        return {"ok": False, "error": "email and over_by required"}
    now = datetime.now(timezone.utc).isoformat()
    await db.over_allowance_acks.update_one(
        {"email": email},
        {"$set": {
            "email": email,
            "over_by": over_by,
            "acked_at": now,
            "acked_by_user_id": by_user_id,
            "acked_by_name": by_name,
        }},
        upsert=True,
    )
    # Update the cached snapshot in-place: filter out the acked row so the
    # UI's next GET immediately reflects the change, without waiting for the
    # 5-min recompute cycle.
    cached = await db.fn_cache.find_one({"_id": OVER_ALLOWANCE_CACHE_KEY}, {"_id": 0, "value": 1})
    snapshot = (cached or {}).get("value") or {}
    students = snapshot.get("students") or []
    filtered = [s for s in students if not (s.get("email", "").lower() == email and int(s.get("over_by", 0)) <= over_by)]
    if filtered != students:
        snapshot["students"] = filtered
        await db.fn_cache.update_one(
            {"_id": OVER_ALLOWANCE_CACHE_KEY},
            {"$set": {"value": snapshot, "computed_at": snapshot.get("computed_at")}},
            upsert=True,
        )
    return {"ok": True, "email": email, "over_by": over_by}


# ---------- Slack alerting ----------------------------------------------------
async def _oksana_email(db) -> Optional[str]:
    member = await db.team_members.find_one(
        {"name": {"$regex": "oksana", "$options": "i"}}, {"_id": 0, "id": 1, "name": 1},
    )
    if not member:
        return None
    user = await db.users.find_one(
        {"team_member_id": member["id"]}, {"_id": 0, "email": 1},
    )
    return (user or {}).get("email")


async def notify_over_allowance_breaches(db) -> dict:
    """For each currently over-allowance student, DM Oksana once. Re-DM only
    when `over_by` grows beyond the previously notified value (so a student
    going from 1-over to 2-over triggers a fresh ping)."""
    snapshot = await find_over_allowance_students(db)
    students = snapshot.get("students") or []
    # Cache for the UI
    await db.fn_cache.update_one(
        {"_id": OVER_ALLOWANCE_CACHE_KEY},
        {"$set": {"_id": OVER_ALLOWANCE_CACHE_KEY,
                  "value": snapshot,
                  "computed_at": snapshot["computed_at"]}},
        upsert=True,
    )
    if not students:
        return {"notified": 0, "total_over": 0, "students": []}

    oksana_email = await _oksana_email(db)
    if not oksana_email:
        logger.warning("[over-allowance] no Oksana email — skipping DM")
        return {"notified": 0, "total_over": len(students), "skipped": "no_oksana_email"}

    import slack_dm
    base_url = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    notified = 0
    for s in students:
        key = f"over_allowance:{s['email']}"
        prev = await db[SENT_COLLECTION].find_one({"key": key}, {"_id": 0, "over_by": 1})
        prev_over_by = (prev or {}).get("over_by", 0)
        if s["over_by"] <= prev_over_by:
            continue  # already notified at this severity or worse
        link_line = (
            f"<{base_url}/coach-activity|Open Coach Activity board>" if base_url else "Open the Coach Activity board"
        )
        breakdown = (
            f"{s['monday_calls_total']} calls + {s['monday_mocks_total']} mock + {s['monday_bonus_total']} bonus"
        )
        text = (
            f":rotating_light: *Over-allowance booking* — {s['tier']}\n"
            f"*{s['name']}* ({s['email']})\n"
            f"Booked *{s['calendly_calls_used']}* Calendly calls — allowance is *{s['monday_total_allowance']}* ({breakdown})\n"
            f"Over by *{s['over_by']}*\n"
            f"{link_line}"
        )
        res = await slack_dm.dm_user(db, oksana_email, text)
        if res.get("ok"):
            notified += 1
            await db[SENT_COLLECTION].update_one(
                {"key": key},
                {"$set": {
                    "key": key,
                    "email": s["email"],
                    "name": s["name"],
                    "over_by": s["over_by"],
                    "notified_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
            logger.info(f"[over-allowance] DM'd Oksana about {s['name']} (over_by={s['over_by']})")
        else:
            logger.warning(f"[over-allowance] DM failed for {s['email']}: {res.get('error')}")
    return {"notified": notified, "total_over": len(students)}


async def get_cached_over_allowance(db) -> dict:
    """Return the most recent snapshot for the UI without re-fetching."""
    doc = await db.fn_cache.find_one({"_id": OVER_ALLOWANCE_CACHE_KEY}, {"_id": 0, "value": 1})
    return (doc or {}).get("value") or {"computed_at": None, "students": []}
