"""
Tally interview-form lookup. Pulls all submissions of the post-interview form
(form id `nGyGj2`) ONCE per ~30 min, caches them in Mongo, then serves
per-email lookups in-memory.

Returns:
  {
    "type": "Locum" | "Substantive" | None,         # latest interview type
    "history_count": N,                              # total past submissions
    "history": [
      {"date": "2026-04-12", "type": "Locum",
       "hospital": "...", "speciality": "...",
       "outcome": "Yes I got the job!", "questions": "..."},
       ...
    ]
  }
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import httpx

INTERVIEW_FORM_ID = "nGyGj2"
TALLY_BASE = "https://api.tally.so"

# Question IDs (cached from form schema; unlikely to change)
Q_EMAIL = "A2XYDB"           # Circle Email
Q_INTERVIEW_TYPE = "BdRYD7"  # Locum / Substantive
Q_INTERVIEW_DATE = "keP4W6"  # YYYY-MM-DD
Q_HOSPITAL = "VPGQ4y"
Q_SPECIALITY = "gqDzY1"
Q_PRESENTATION = "ExWO02"
Q_OUTCOME = "G9W5N2"         # "How did your interview go on @interviewdate"
Q_QUESTIONS = "qGLl7O"       # What questions did you get?
Q_RESCHEDULED = "VQgDJy"
Q_FULLNAME = "bjJMre"

CACHE_TTL_MIN = 24 * 60  # 24 hours - interview submissions trickle in, no need to refresh more often


def _tally_headers() -> dict:
    key = os.environ.get("TALLY_API_KEY")
    if not key:
        raise RuntimeError("TALLY_API_KEY missing")
    return {"Authorization": f"Bearer {key}"}


def _answer_str(ans) -> str:
    """Tally answers come back as str or list[str] for dropdowns/multi-choice."""
    if ans is None:
        return ""
    if isinstance(ans, list):
        return ", ".join(str(a) for a in ans if a)
    return str(ans)


async def _fetch_all_submissions() -> list[dict]:
    """Pull all submissions across paginated pages.

    Bounded to 20 pages (≈2000 submissions) AND 10s wall-clock so a cold
    Tally refresh can never exhaust the per-platform budget in the
    Student Lookup fan-out. The form sees maybe 1-2 submissions/day in
    practice, so 2000 is plenty; if we ever need more we'll page on
    demand.
    """
    import time as _time
    out: list[dict] = []
    page = 1
    deadline = _time.monotonic() + 10.0
    async with httpx.AsyncClient(timeout=30) as c:
        while page <= 20 and _time.monotonic() < deadline:
            r = await c.get(
                f"{TALLY_BASE}/forms/{INTERVIEW_FORM_ID}/submissions",
                headers=_tally_headers(),
                params={"page": page, "limit": 100},
            )
            r.raise_for_status()
            body = r.json()
            items = body.get("submissions") or body.get("items") or body.get("data") or []
            if not items:
                break
            out.extend(items)
            if len(items) < 100:
                break
            page += 1
    return out


async def get_cached_submissions(db) -> list[dict]:
    """Returns the cached list of submissions, refreshing if older than TTL."""
    cache_key = "tally_interviews:nGyGj2"
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CACHE_TTL_MIN)
    cached = await db.cache.find_one({"_id": cache_key}, {"_id": 0})
    if cached and cached.get("cached_at"):
        cached_at = cached["cached_at"]
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        if cached_at > cutoff:
            return cached.get("payload") or []
    submissions = await _fetch_all_submissions()
    await db.cache.update_one(
        {"_id": cache_key},
        {"$set": {
            "payload": submissions,
            "cached_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    return submissions


def _parse_submission(s: dict) -> dict | None:
    by_qid = {r.get("questionId"): r.get("answer") for r in (s.get("responses") or [])}
    email = _answer_str(by_qid.get(Q_EMAIL)).lower().strip()
    if not email:
        return None
    return {
        "email": email,
        "name": _answer_str(by_qid.get(Q_FULLNAME)),
        "date": _answer_str(by_qid.get(Q_INTERVIEW_DATE))[:10],
        "type": _answer_str(by_qid.get(Q_INTERVIEW_TYPE)) or None,
        "hospital": _answer_str(by_qid.get(Q_HOSPITAL)),
        "speciality": _answer_str(by_qid.get(Q_SPECIALITY)),
        "presentation": _answer_str(by_qid.get(Q_PRESENTATION)),
        "outcome": _answer_str(by_qid.get(Q_OUTCOME)),
        "questions": _answer_str(by_qid.get(Q_QUESTIONS)),
        "rescheduled": _answer_str(by_qid.get(Q_RESCHEDULED)),
        "submitted_at": s.get("createdAt") or s.get("submittedAt"),
    }


async def lookup_student(db, email: str) -> dict:
    """Returns interview history for a single student email."""
    if not email:
        return {"type": None, "history_count": 0, "history": []}
    target = email.lower().strip()
    submissions = await get_cached_submissions(db)
    parsed = [p for p in (_parse_submission(s) for s in submissions) if p and p["email"] == target]
    # Sort newest first by date (fall back to submitted_at)
    parsed.sort(key=lambda x: (x.get("date") or x.get("submitted_at") or ""), reverse=True)
    return {
        "type": parsed[0]["type"] if parsed else None,
        "history_count": len(parsed),
        "history": parsed,
    }


async def lookup_emails_bulk(db, emails: list[str]) -> dict[str, dict]:
    """
    Bulk version - fetches submissions ONCE then groups by email.
    Returns {email_lowercase: {type, history_count, history}}.
    """
    submissions = await get_cached_submissions(db)
    by_email: dict[str, list[dict]] = {}
    for s in submissions:
        p = _parse_submission(s)
        if not p:
            continue
        by_email.setdefault(p["email"], []).append(p)

    out: dict[str, dict] = {}
    for em in emails:
        if not em:
            continue
        key = em.lower().strip()
        rows = by_email.get(key) or []
        rows.sort(key=lambda x: (x.get("date") or x.get("submitted_at") or ""), reverse=True)
        out[key] = {
            "type": rows[0]["type"] if rows else None,
            "history_count": len(rows),
            "history": rows,
        }
    return out
