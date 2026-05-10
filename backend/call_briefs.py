"""3-line AI briefing for each Today's Calls row.

Goal: 3 short lines a coach can read in 5 seconds before the call.
  • Line 1 — student context (tier, speciality, hospital, days-to-interview)
  • Line 2 — most recent ask / focus area
  • Line 3 — last coach reply or risk signal

Cached in `call_briefs` keyed by `(email, UK-date)` so we don't re-charge
the LLM every time the widget mounts. Cache invalidates at midnight UK.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

LONDON = ZoneInfo("Europe/London")
MAX_LINES = 3
MAX_LINE_CHARS = 140


def _uk_date_str() -> str:
    return datetime.now(timezone.utc).astimezone(LONDON).date().isoformat()


async def get_brief(db, email: str, name: str) -> dict:
    """Return {lines: [str, str, str], cached: bool}. Returns empty list of
    lines on any failure — caller renders the row plainly in that case."""
    email = (email or "").strip().lower()
    if not email:
        return {"lines": [], "cached": False}

    today = _uk_date_str()
    cache_key = f"{email}::{today}"
    cached = await db.call_briefs.find_one({"_id": cache_key}, {"_id": 0})
    if cached and cached.get("lines"):
        return {"lines": cached["lines"], "cached": True}

    # Pull context — Drive summary + Monday/student data
    context = await _build_context(db, email, name)
    if not context:
        return {"lines": [], "cached": False}

    try:
        lines = await _llm_brief(context)
    except Exception as e:
        logger.warning(f"[call-brief] LLM failed for {email}: {e}")
        return {"lines": [], "cached": False}

    if not lines:
        return {"lines": [], "cached": False}

    await db.call_briefs.update_one(
        {"_id": cache_key},
        {"$set": {"lines": lines, "email": email, "generated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"lines": lines, "cached": False}


async def _build_context(db, email: str, name: str) -> dict | None:
    """Compact dict of everything Claude needs."""
    ctx: dict = {"name": name, "email": email}

    # Drive doc summary (already cached by upcoming_call_prewarm)
    drive = await db.drive_doc_summaries.find_one(
        {"_id": email}, {"_id": 0, "summary": 1, "file": 1},
    )
    if drive:
        ctx["doc_name"] = (drive.get("file") or {}).get("name")
        ctx["doc_summary"] = (drive.get("summary") or "")[:3500]

    # Upcoming interview details (tier/speciality/hospital/date)
    try:
        import upcoming_interviews as upc
        data = await upc.fetch_upcoming_interviews(db=db, days=30)
        for s in (data.get("academy") or []) + (data.get("private") or []):
            if (s.get("email") or "").lower().strip() == email:
                ctx["tier"] = s.get("tier")
                ctx["speciality"] = s.get("speciality")
                ctx["hospital"] = s.get("hospital")
                ctx["interview_date"] = s.get("interview_date")
                ctx["interview_type"] = s.get("interview_type")
                # Most recent Tally interview prep submission
                last = s.get("tally_last_interview") or {}
                if last:
                    ctx["last_prep_questions"] = (last.get("questions") or "")[:500]
                    ctx["last_prep_outcome"] = last.get("outcome")
                # Past coaches
                past = s.get("past_coaches") or []
                if past:
                    ctx["past_coaches"] = [
                        f"{p.get('name')} ({p.get('count')} call{'s' if (p.get('count') or 0) > 1 else ''})"
                        for p in past[:5]
                    ]
                # Mock interview / calls usage
                if s.get("calls_30min"):
                    ctx["calls_30min_used"] = s["calls_30min"].get("used")
                    ctx["calls_30min_total"] = s["calls_30min"].get("total")
                if s.get("mock_interviews"):
                    ctx["mocks_used"] = s["mock_interviews"].get("used")
                    ctx["mocks_total"] = s["mock_interviews"].get("total")
                break
    except Exception as e:
        logger.info(f"[call-brief] upcoming_interviews lookup skipped: {e}")

    # Latest private-tier video question (if any)
    try:
        latest_q = await db.private_video_submissions.find_one(
            {"email": email},
            {"_id": 0, "question": 1, "submitted_at": 1, "status": 1},
            sort=[("submitted_at", -1)],
        )
        if latest_q and latest_q.get("question"):
            ctx["latest_video_question"] = latest_q["question"][:400]
            ctx["latest_video_status"] = latest_q.get("status")
            ctx["latest_video_submitted"] = latest_q.get("submitted_at")
    except Exception:
        pass

    # If we have NOTHING beyond email+name, skip the LLM call
    if not (ctx.get("doc_summary") or ctx.get("speciality") or ctx.get("latest_video_question")):
        return None
    return ctx


async def _llm_brief(ctx: dict) -> list[str]:
    """Ask Claude Sonnet 4.5 for exactly 3 short briefing lines."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return []

    system = (
        "You are an interview coach's assistant at AYCI Academy (medical-interview "
        "prep). Produce a tight pre-call briefing of EXACTLY 3 lines, plain text, "
        "no markdown, no bullets, no preamble, no sign-off. "
        "Each line MUST be under 140 characters. "
        "Line 1: who the student is + speciality + interview date or days-to-go. "
        "Line 2: their current focus / most recent question or ask. "
        "Line 3: one signal worth knowing — last coach interaction, recurring "
        "weakness, or progress note. Use the source material verbatim where "
        "possible; do not invent facts. If a field is missing, skip it (don't say "
        "'unknown'). Output the 3 lines separated by single newlines and nothing else."
    )

    # Build a compact user-message payload Claude can read fast
    parts = [
        f"Student: {ctx.get('name') or ctx.get('email')}",
        f"Tier: {ctx.get('tier')}" if ctx.get("tier") else None,
        f"Speciality: {ctx.get('speciality')}" if ctx.get("speciality") else None,
        f"Hospital: {ctx.get('hospital')}" if ctx.get("hospital") else None,
        f"Interview date: {ctx.get('interview_date')}" if ctx.get("interview_date") else None,
        f"Interview type: {ctx.get('interview_type')}" if ctx.get("interview_type") else None,
        f"30-min calls used: {ctx.get('calls_30min_used')}/{ctx.get('calls_30min_total')}" if ctx.get("calls_30min_total") else None,
        f"Mock interviews used: {ctx.get('mocks_used')}/{ctx.get('mocks_total')}" if ctx.get("mocks_total") else None,
        f"Past coaches: {', '.join(ctx.get('past_coaches') or []) }" if ctx.get("past_coaches") else None,
        f"Most recent prep questions logged: {ctx.get('last_prep_questions')}" if ctx.get("last_prep_questions") else None,
        f"Latest private-tier video question: {ctx.get('latest_video_question')}" if ctx.get("latest_video_question") else None,
        f"Doc summary:\n{ctx.get('doc_summary')}" if ctx.get("doc_summary") else None,
    ]
    user_text = "\n".join(p for p in parts if p)

    chat = LlmChat(
        api_key=key,
        session_id=f"call-brief-{ctx.get('email','x')}",
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    resp = await chat.send_message(UserMessage(text=user_text))
    text = (resp or "").strip()
    if not text:
        return []
    lines = [ln.strip(" -•").strip() for ln in text.splitlines() if ln.strip()]
    # Trim to 3 lines and length-cap each
    lines = [ln[:MAX_LINE_CHARS] for ln in lines[:MAX_LINES]]
    return lines
