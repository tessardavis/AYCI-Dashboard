"""Interview-Eve DM routes — admin view of sent check-ins + manual trigger."""
from fastapi import APIRouter, Depends

import interview_eve_dm
from db import db
from deps import require_admin, require_board

router = APIRouter(prefix="/api/interview-eve", tags=["interview-eve"])


@router.get("/records")
async def list_records(admin: dict = Depends(require_admin), limit: int = 100):
    """Recent interview-eve DM records (newest first), including any score
    the student replied with and whether a low-score alert was fired."""
    rows = await db.interview_eve_dms.find(
        {}, {"_id": 0},
    ).sort("sent_at", -1).limit(min(max(1, limit), 500)).to_list(500)
    return {"records": rows, "total": len(rows)}


@router.post("/run-now")
async def run_now(admin: dict = Depends(require_admin)):
    """Force the interview-eve job to run immediately (for testing)."""
    return await interview_eve_dm.send_interview_eve_dms(db)


@router.get("/summary")
async def summary(user: dict = Depends(require_board("coach_activity"))):
    """Aggregated view of the last 7 days of interview-eve DMs — for the
    Coach Activity widget. Returns counts (sent / replied / low / pending),
    averages, and the rows for today + tomorrow's interviews, split by
    tier so private-tier students can be tracked separately."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=7)).isoformat()
    rows = await db.interview_eve_dms.find(
        {"sent_at": {"$gte": cutoff}}, {"_id": 0},
    ).sort("interview_date", -1).to_list(None)
    today = now.date().isoformat()
    tomorrow = (now.date() + timedelta(days=1)).isoformat()

    def _stats(subset: list[dict]) -> dict:
        scored = [r for r in subset if r.get("score") is not None]
        avg = round(sum(r["score"] for r in scored) / len(scored), 1) if scored else None
        return {
            "sent": len(subset),
            "replied": len(scored),
            "pending": len(subset) - len(scored),
            "low_score": sum(1 for r in subset if (r.get("score") or 99) <= 5),
            "avg_score": avg,
        }

    private_rows = [r for r in rows if r.get("is_private_tier")]
    other_rows = [r for r in rows if not r.get("is_private_tier")]

    return {
        "window_days": 7,
        "counts": _stats(rows),
        "private_tier": _stats(private_rows),
        "academy_tier": _stats(other_rows),
        "focus": [r for r in rows if r.get("interview_date") in (today, tomorrow)],
        "private_tier_rows": [r for r in private_rows if r.get("score") is not None][:50],
        "today": today,
        "tomorrow": tomorrow,
    }


@router.get("/preview")
async def preview(admin: dict = Depends(require_admin)):
    """Dry-run: who WOULD we DM if the job ran right now? No DMs sent."""
    import upcoming_interviews
    from datetime import datetime, timezone, timedelta
    target_date = (
        (datetime.now(timezone.utc) + timedelta(hours=1)).date() + timedelta(days=1)
    ).isoformat()
    payload = await upcoming_interviews.fetch_upcoming_interviews(db=db, days=3)
    candidates = []
    for group in ("academy", "private"):
        for s in payload.get(group) or []:
            if s.get("interview_date") == target_date:
                m = await interview_eve_dm._find_circle_member_by_email(
                    db, s.get("email") or "",
                )
                already = await db.interview_eve_dms.find_one(
                    {"student_email": (s.get("email") or "").lower(),
                     "interview_date": target_date},
                    {"_id": 0, "id": 1, "score": 1},
                )
                candidates.append({
                    "name": s.get("name"),
                    "email": s.get("email"),
                    "tier": s.get("tier"),
                    "is_private_tier": interview_eve_dm._is_private_tier(s),
                    "circle_member_id": (m or {}).get("id"),
                    "already_sent": bool(already),
                    "previous_score": (already or {}).get("score"),
                })
    return {"target_date": target_date, "candidates": candidates,
            "total": len(candidates)}



@router.post("/backfill-scores")
async def backfill_scores(admin: dict = Depends(require_admin), days: int = 3):
    """Retroactively recover any interview-eve scores that were missed by
    the bot — typically because the polling bot's lookback guard fired on
    a coach's manual personal message and short-circuited before the
    score-capture step. (Fixed structurally on 2026-05-15 by moving score
    capture above the lookback guard; this endpoint cleans up records
    sent before that fix landed.)

    For each `interview_eve_dms` record in the last `days` days that
    still has `score=None`, fetch the thread's most-recent messages via
    the Circle Headless API, find the latest student message, run
    `parse_score()` on it, and persist the score if found. Fires the
    low-score Slack alert too if the parsed score is ≤ threshold.
    """
    import circle_api
    from datetime import datetime, timezone, timedelta
    days = max(1, min(int(days or 3), 14))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = await db.interview_eve_dms.find(
        {"score": None, "sent_at": {"$gte": cutoff}}, {"_id": 0},
    ).to_list(None)

    recovered: list[dict] = []
    still_pending: list[dict] = []
    errors: list[dict] = []
    for rec in rows:
        thread_uuid = rec.get("thread_uuid")
        coach_email = rec.get("coach_admin_email") or interview_eve_dm.COACH_EMAIL
        member_id = rec.get("circle_member_id")
        if not thread_uuid or not member_id:
            still_pending.append({"name": rec.get("student_name"),
                                  "reason": "missing_thread_or_member"})
            continue
        try:
            messages = await circle_api.list_thread_messages_for_admin(
                db, coach_email, thread_uuid, per_page=20,
            )
        except Exception as e:
            errors.append({"name": rec.get("student_name"), "error": str(e)[:160]})
            continue
        if not messages:
            still_pending.append({"name": rec.get("student_name"), "reason": "no_messages"})
            continue
        # Sort oldest -> newest, find latest student message.
        messages.sort(key=lambda m: m.get("created_at") or "")
        latest_student = None
        for m in reversed(messages):
            sender = (m.get("sender") or {})
            sid = sender.get("community_member_id") or sender.get("id") or m.get("community_member_id")
            try:
                if sid is not None and int(sid) == int(member_id):
                    latest_student = m
                    break
            except (ValueError, TypeError):
                continue
        if not latest_student:
            still_pending.append({"name": rec.get("student_name"),
                                  "reason": "no_student_reply"})
            continue
        body = (
            latest_student.get("body")
            or latest_student.get("plain_text")
            or (latest_student.get("rich_text_body") or {}).get("circle_ios_fallback_text")
            or latest_student.get("text")
            or ""
        ).strip()
        score = interview_eve_dm.parse_score(body)
        if score is None:
            still_pending.append({
                "name": rec.get("student_name"),
                "reason": "no_score_parsed",
                "last_student_msg": body[:140],
            })
            continue
        # Persist + fire Slack alert if low.
        scored = await interview_eve_dm.maybe_record_score(db, thread_uuid, body)
        if scored is None:
            # Could be a race — already recorded. Re-check.
            fresh = await db.interview_eve_dms.find_one({"id": rec["id"]}, {"_id": 0, "score": 1})
            recovered.append({
                "name": rec.get("student_name"),
                "score": (fresh or {}).get("score"),
                "raw": body[:140],
                "note": "already_recorded_by_concurrent_poll",
            })
        else:
            recovered.append({
                "name": rec.get("student_name"),
                "score": scored["score"],
                "raw": body[:140],
            })
    return {
        "scanned": len(rows),
        "recovered": recovered,
        "still_pending": still_pending,
        "errors": errors,
    }
