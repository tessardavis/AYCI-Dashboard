"""
Spotlight Coaching: for each upcoming live curriculum / group-coaching session,
list students who submitted the spotlight Tally form, with their requested
topic and (if available) their upcoming interview date — so the coach can
prioritise interview-soon people on the day.

Sources
-------
1. Circle Live Calendar API (`/admin/v2/events`) — finds the next upcoming
   "Curriculum Session" or "General Coaching" event.
2. Tally spotlight forms — one per session type:
   - mY8WPq → curriculum sessions
   - wgxO1l → group coaching sessions
3. Interview Tally form (`tally_lookup.INTERVIEW_FORM_ID`) — cross-referenced
   by **full name** because the spotlight forms don't capture email.

Eligibility
-----------
A submission is "eligible" if it was made on or before the calendar day
*before* the session in UK time (Europe/London). Submissions made after that
deadline are still surfaced but flagged "late".

Caching
-------
Both Tally form fetches and the Circle events fetch are cached for 15 min in
Mongo `cache` (collection used by other modules) so repeated dashboard loads
stay sub-100 ms.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

import tally_lookup
import leaderboard as leaderboard_mod

logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")

CURRICULUM_FORM_ID = "mY8WPq"
GROUP_COACHING_FORM_ID = "wgxO1l"

# Tally question IDs (discovered via /forms/{id}/submissions schema)
# Both forms use the same titles; ids differ. We pick by title at parse time.
SPOTLIGHT_TITLES = {
    "first": "what is your first name?",
    "last": "what is your surname?",
    "has_interview": "do you have an interview date?",
    "interview_form_done": "have you submitted your interview date form?",
    "topic": "what would you like to use your spotlight coaching for?",
}

CIRCLE_BASE = "https://app.circle.so/api/admin/v2"
CACHE_TTL_MIN = 15

# Session-type detection from Circle event names. Keep the order: more specific
# first ("curriculum session" wins over general "coaching").
SESSION_TYPE_PATTERNS = [
    ("curriculum", re.compile(r"curriculum\s*session", re.I), CURRICULUM_FORM_ID),
    ("group_coaching", re.compile(r"general\s*coaching", re.I), GROUP_COACHING_FORM_ID),
]


# --------------------------------------------------------------------- helpers

def _norm_name(*parts: Optional[str]) -> str:
    joined = " ".join((p or "").strip() for p in parts).lower()
    return re.sub(r"\s+", " ", joined).strip()


def _safe_str(ans: Any) -> str:
    if ans is None:
        return ""
    if isinstance(ans, list):
        return ", ".join(str(a) for a in ans if a)
    return str(ans)


def _classify_session(name: str) -> Optional[tuple[str, str]]:
    """Returns (session_type, form_id) for an event name, or None if it's not
    a spotlight-eligible session."""
    for stype, pattern, fid in SESSION_TYPE_PATTERNS:
        if pattern.search(name or ""):
            return stype, fid
    return None


def _to_uk_date(iso_utc: str) -> str:
    """ISO-8601 UTC → YYYY-MM-DD in UK local time."""
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone(UK_TZ).date().isoformat()


# --------------------------------------------------------------------- caching

async def _cache_get(db, key: str) -> Optional[Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CACHE_TTL_MIN)
    doc = await db.cache.find_one({"_id": key}, {"_id": 0})
    if not doc:
        return None
    cached_at = doc.get("cached_at")
    if cached_at and cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    if cached_at and cached_at > cutoff:
        return doc.get("payload")
    return None


async def _cache_set(db, key: str, payload: Any) -> None:
    await db.cache.update_one(
        {"_id": key},
        {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


# --------------------------------------------------------------------- Circle events

async def _fetch_circle_events(db) -> list[dict]:
    cached = await _cache_get(db, "spotlight:circle_events")
    if cached is not None:
        return cached
    headers = {"Authorization": f"Token {os.environ.get('CIRCLE_API_TOKEN', '')}"}
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as c:
        # Paginate up to ~3 pages (150 events) to cover ~6 weeks of upcoming
        for page in range(1, 4):
            r = await c.get(
                f"{CIRCLE_BASE}/events",
                headers=headers,
                params={"per_page": 50, "page": page, "sort": "starts_at", "order": "asc"},
            )
            r.raise_for_status()
            body = r.json()
            recs = body.get("records") or body.get("data") or []
            out.extend(recs)
            if not body.get("has_next_page"):
                break
    await _cache_set(db, "spotlight:circle_events", out)
    return out


# --------------------------------------------------------------------- Tally

async def _fetch_form_submissions(db, form_id: str) -> dict:
    """Returns {'questions': [...], 'submissions': [...]} from cache or live."""
    cache_key = f"spotlight:tally:{form_id}"
    cached = await _cache_get(db, cache_key)
    if cached is not None:
        return cached
    key = os.environ.get("TALLY_API_KEY")
    if not key:
        raise RuntimeError("TALLY_API_KEY missing")
    headers = {"Authorization": f"Bearer {key}"}
    submissions: list[dict] = []
    questions: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as c:
        for page in range(1, 21):  # cap at 2000 submissions
            r = await c.get(
                f"https://api.tally.so/forms/{form_id}/submissions",
                headers=headers,
                params={"page": page, "limit": 100},
            )
            r.raise_for_status()
            body = r.json()
            if page == 1:
                questions = body.get("questions") or []
            items = body.get("submissions") or body.get("items") or []
            if not items:
                break
            submissions.extend(items)
            if len(items) < 100 or not body.get("hasMore", False):
                break
    payload = {"questions": questions, "submissions": submissions}
    await _cache_set(db, cache_key, payload)
    return payload


def _resolve_qids(questions: list[dict]) -> dict[str, Optional[str]]:
    """Map our logical field names → the Tally questionId for this form."""
    out: dict[str, Optional[str]] = {k: None for k in SPOTLIGHT_TITLES}
    for q in questions:
        title = (q.get("title") or "").strip().lower()
        for key, target in SPOTLIGHT_TITLES.items():
            if title == target:
                out[key] = q.get("id")
                break
    return out


def _parse_spotlight_submission(s: dict, qids: dict[str, Optional[str]]) -> Optional[dict]:
    by_qid = {r.get("questionId"): r.get("answer") for r in (s.get("responses") or [])}
    first = _safe_str(by_qid.get(qids["first"])).strip()
    last = _safe_str(by_qid.get(qids["last"])).strip()
    if not first and not last:
        return None
    submitted_at = s.get("submittedAt") or s.get("createdAt")
    return {
        "first_name": first,
        "last_name": last,
        "name": f"{first} {last}".strip(),
        "name_key": _norm_name(first, last),
        "topic": _safe_str(by_qid.get(qids["topic"])).strip(),
        "claims_interview": (
            _safe_str(by_qid.get(qids["has_interview"])).lower().startswith("yes")
        ),
        "interview_form_done": (
            _safe_str(by_qid.get(qids["interview_form_done"])).lower().startswith("yes")
        ),
        "submitted_at": submitted_at,
    }


# --------------------------------------------------------------------- compute

async def _interview_lookup_by_name(db) -> dict[str, dict]:
    """Build `{name_key: {date, type, days_until}}` from the post-interview
    Tally form, prioritising the MOST RECENTLY SUBMITTED entry per person.

    Why "most recently submitted" rather than "soonest future date"? When a
    student reschedules, they submit a fresh tally entry. The latest
    submission is the source of truth — even if its date is later than an
    older "ghost" entry that's still in the future. Past dates are dropped
    only after we've already picked the latest submission.
    """
    today = datetime.now(UK_TZ).date()
    submissions = await tally_lookup.get_cached_submissions(db)
    # Index by (name_key) and (first_word) — collect ALL parses, sorted by
    # submitted_at desc.
    by_full: dict[str, list[dict]] = {}
    by_first: dict[str, list[dict]] = {}
    for s in submissions:
        parsed = tally_lookup._parse_submission(s)
        if not parsed:
            continue
        name = parsed.get("name") or ""
        nk = _norm_name(name)
        if not nk:
            continue
        d = (parsed.get("date") or "")[:10]
        if not d:
            continue
        try:
            dt = datetime.fromisoformat(d).date()
        except ValueError:
            continue
        record = {
            "interview_date": dt.isoformat(),
            "interview_type": parsed.get("type"),
            "days_until": (dt - today).days,
            "submitted_at": parsed.get("submitted_at") or "",
            "_name": name,
        }
        by_full.setdefault(nk, []).append(record)
        first_word = nk.split(" ")[0]
        if first_word:
            by_first.setdefault(first_word, []).append(record)

    # For each name, pick the most recently SUBMITTED entry — but only if its
    # date is in the future. If the latest submission's date is past, the
    # student doesn't have an upcoming interview (don't fall back to older
    # entries; they're stale and the student rescheduled past).
    out: dict[str, dict] = {}
    for nk, rows in by_full.items():
        rows.sort(key=lambda r: r["submitted_at"], reverse=True)
        latest = rows[0]
        if latest["days_until"] >= 0:
            out[f"full:{nk}"] = latest
    for fw, rows in by_first.items():
        distinct_names = {_norm_name(r["_name"]) for r in rows}
        if len(distinct_names) == 1:
            rows.sort(key=lambda r: r["submitted_at"], reverse=True)
            latest = rows[0]
            if latest["days_until"] >= 0:
                out[f"first:{fw}"] = latest
    return out


def _resolve_interview(name_key: str, index: dict[str, dict]) -> Optional[dict]:
    if not name_key:
        return None
    full = index.get(f"full:{name_key}")
    if full:
        return full
    first_word = name_key.split(" ")[0]
    if first_word:
        return index.get(f"first:{first_word}")
    return None


async def _build_session_payload(
    db, event: dict, form_id: str, interview_index: dict[str, dict],
    cycle_start_iso: Optional[str],
    leaderboard_index: dict[str, int],
    cohort_rank_by_score: dict[int, int],
) -> dict:
    """Compose one session block: header + eligible students.

    `cycle_start_iso` is the ISO-8601 UTC timestamp of when the SPOTLIGHT cycle
    for this session opened — i.e. the start of the previous same-type session,
    or None to fall back to a 14-day floor.

    `leaderboard_index` is `{name_key: badge_score}` from `leaderboard_mod`,
    keyed by lowercased "first last".
    """
    starts_at = event.get("starts_at") or ""
    session_uk_date = _to_uk_date(starts_at) if starts_at else None
    deadline_uk_date = (
        (datetime.fromisoformat(session_uk_date) - timedelta(days=1)).date().isoformat()
        if session_uk_date else None
    )
    form_data = await _fetch_form_submissions(db, form_id)
    qids = _resolve_qids(form_data["questions"])
    parsed = []
    for s in form_data["submissions"]:
        p = _parse_spotlight_submission(s, qids)
        if not p:
            continue
        parsed.append(p)

    # Cycle window: submissions made AFTER the previous same-type session
    # (cycle_start_iso) and BEFORE this session starts.
    now_utc = datetime.now(timezone.utc)
    if cycle_start_iso:
        floor_dt = datetime.fromisoformat(cycle_start_iso.replace("Z", "+00:00"))
    else:
        floor_dt = now_utc - timedelta(days=14)
    in_window: list[dict] = []
    for p in parsed:
        try:
            sub_dt = datetime.fromisoformat((p["submitted_at"] or "").replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if sub_dt > now_utc:
            continue
        if sub_dt <= floor_dt:
            continue
        if starts_at:
            try:
                session_dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
            except ValueError:
                session_dt = None
            if session_dt and sub_dt > session_dt:
                continue  # submitted AFTER session has already started
        sub_uk_date = sub_dt.astimezone(UK_TZ).date().isoformat()
        # Eligibility: must be submitted on the deadline UK date itself (the
        # calendar day before the session). Submissions before or after are
        # not eligible.
        if not deadline_uk_date:
            eligibility = "unknown"
        elif sub_uk_date == deadline_uk_date:
            eligibility = "on_time"
        elif sub_uk_date < deadline_uk_date:
            eligibility = "early"
        else:
            eligibility = "late"
        eligible = eligibility == "on_time"
        # Cross-reference with interview tally form
        ix = _resolve_interview(p["name_key"], interview_index) or {}
        # Leaderboard score (Circle badge count)
        score = leaderboard_index.get(p["name_key"])
        if score is None:
            # Fallback: try first-name only for interview-style first-only matches
            score = leaderboard_index.get(p["name_key"].split(" ")[0])
        in_window.append({
            **p,
            "submitted_uk_date": sub_uk_date,
            "eligible": eligible,
            "eligibility": eligibility,
            "interview_date": ix.get("interview_date"),
            "interview_type": ix.get("interview_type"),
            "days_until_interview": ix.get("days_until"),
            "leaderboard_score": score,
        })

    # Sort:
    #   1. Eligible-on-time submissions ALWAYS rank above late/early ones
    #      (per Tessa: late/early submitters belong at the bottom of the list)
    #   2. Within each eligibility tier, interview-soon first
    #   3. Higher leaderboard score wins
    #   4. Earliest submission first
    def _sort_key(x):
        days = x.get("days_until_interview")
        score = x.get("leaderboard_score")
        return (
            0 if x.get("eligible") else 1,
            0 if days is not None else 1,
            days if days is not None else 9999,
            -(score or 0),
            x.get("submitted_at") or "",
        )

    in_window.sort(key=_sort_key)

    # Compute leaderboard rank within this session — purely based on badge
    # count (descending). Used by the UI to show "🏆 top eligible" chips so
    # the team can SEE why the top rows are prioritised. Ties share a rank
    # (standard competition ranking: 1, 2, 2, 4...).
    by_score = sorted(
        [s for s in in_window if (s.get("leaderboard_score") or 0) > 0],
        key=lambda s: -(s.get("leaderboard_score") or 0),
    )
    rank_by_key: dict[str, int] = {}
    last_score: Optional[int] = None
    last_rank = 0
    for idx, s in enumerate(by_score, start=1):
        score = s.get("leaderboard_score") or 0
        if score != last_score:
            last_rank = idx
            last_score = score
        rank_by_key[s["name_key"]] = last_rank

    # Map session badge-score → cohort-wide leaderboard rank, using the
    # pre-computed `cohort_rank_by_score` (built from get_top_leaderboard
    # so it uses proper standard competition ranking and counts each member
    # exactly once).
    for s in in_window:
        s["leaderboard_rank"] = rank_by_key.get(s["name_key"])
        ls = s.get("leaderboard_score") or 0
        s["cohort_leaderboard_rank"] = (
            cohort_rank_by_score.get(ls) if ls > 0 else None
        )

    return {
        "id": event.get("id"),
        "name": event.get("name"),
        "session_type": "curriculum" if form_id == CURRICULUM_FORM_ID else "group_coaching",
        "starts_at": starts_at,
        "ends_at": event.get("ends_at"),
        "session_uk_date": session_uk_date,
        "deadline_uk_date": deadline_uk_date,
        "circle_url": (
            f"https://academy.youaretheconsultant.com/c/live-streams/{event.get('slug')}"
            if event.get("slug") else None
        ),
        "students": in_window,
        "submissions_total": len(in_window),
        "eligible_total": sum(1 for s in in_window if s["eligible"]),
        "with_interview_total": sum(1 for s in in_window if s.get("days_until_interview") is not None),
    }


async def get_upcoming_spotlight_sessions(db, limit: int = 3) -> dict:
    """Return the next `limit` upcoming (or currently-live) spotlight-eligible
    Circle sessions with their submission rosters.

    A session is considered "still current" until its `ends_at` (or
    `starts_at + 2h` if no end is published). This way today's session stays
    visible while it's actually happening — coaches still need to see the
    prep list during the call."""
    events = await _fetch_circle_events(db)
    now_utc = datetime.now(timezone.utc)

    def _still_current(e: dict) -> bool:
        """A session stays on the upcoming list until the END of its calendar
        day in UK local time — so coaches can still record outcomes the
        evening of the session (not just during its run window)."""
        starts = e.get("starts_at") or ""
        if not starts:
            return False
        try:
            start_dt = datetime.fromisoformat(starts.replace("Z", "+00:00"))
        except ValueError:
            return False
        uk_date = start_dt.astimezone(UK_TZ).date()
        end_of_day_uk = datetime.combine(
            uk_date + timedelta(days=1), datetime.min.time(), tzinfo=UK_TZ
        )
        return end_of_day_uk > now_utc

    upcoming: list[tuple[dict, str]] = []  # (event, form_id)
    for e in events:
        if not _still_current(e):
            continue
        cls = _classify_session(e.get("name") or "")
        if not cls:
            continue
        _, form_id = cls
        upcoming.append((e, form_id))
    upcoming.sort(key=lambda x: x[0].get("starts_at") or "")
    # Dedupe events that share the same (name, starts_at) — Circle stores one
    # row per recurring/host duplicate, but we only want to display one card.
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[dict, str]] = []
    for ev, fid in upcoming:
        key = ((ev.get("name") or "").strip(), ev.get("starts_at") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append((ev, fid))
    upcoming = deduped[:limit]

    if not upcoming:
        return {
            "sessions": [],
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "note": "No upcoming Curriculum or General Coaching sessions on Circle in the next ~6 weeks.",
        }

    interview_index = await _interview_lookup_by_name(db)
    leaderboard_index = await leaderboard_mod.build_leaderboard_index(db, cohort_tag="Apr '26")
    # Pre-compute the cohort-wide score → rank map (standard competition
    # ranking) by walking the actual ranked leaderboard once. Counting via
    # leaderboard_index would double-count (it stores full name + first
    # name keys), so we use the canonical get_top_leaderboard result.
    full_lb = await leaderboard_mod.get_top_leaderboard(db, cohort_tag="Apr '26", limit=500)
    cohort_rank_by_score: dict[int, int] = {}
    for idx, row in enumerate(full_lb, start=1):
        sc = row.get("score") or 0
        if sc > 0 and sc not in cohort_rank_by_score:
            cohort_rank_by_score[sc] = idx

    # Build a per-(form_id) timeline of past events so we can derive the cycle
    # start (when the *previous* same-type session ran) for each upcoming
    # session. "Past" here means anything whose `starts_at` is before the
    # earliest currently-displayed session — today's session is displayed so
    # its start time acts as the lower cutoff, not `now`.
    earliest_displayed = upcoming[0][0].get("starts_at") or now_utc.isoformat()
    past_by_form: dict[str, list[str]] = {}
    for e in events:
        cls = _classify_session(e.get("name") or "")
        if not cls:
            continue
        starts = e.get("starts_at") or ""
        if not starts or starts >= earliest_displayed:
            continue
        past_by_form.setdefault(cls[1], []).append(starts)
    for fid, lst in past_by_form.items():
        lst.sort()  # ascending

    sessions = []
    seen_for_cycle: dict[str, str] = {}  # form_id → previous-session-starts seen so far
    for event, form_id in upcoming:
        # Cycle start = the most recent same-type session strictly before this one.
        history = past_by_form.get(form_id, [])
        # Combine with previously processed upcoming sessions of the same type
        prior_in_window = seen_for_cycle.get(form_id)
        candidate_starts: list[str] = list(history)
        if prior_in_window:
            candidate_starts.append(prior_in_window)
        candidate_starts = [s for s in candidate_starts if s and s < (event.get("starts_at") or "")]
        cycle_start_iso = max(candidate_starts) if candidate_starts else None
        sessions.append(
            await _build_session_payload(db, event, form_id, interview_index, cycle_start_iso, leaderboard_index, cohort_rank_by_score)
        )
        seen_for_cycle[form_id] = event.get("starts_at") or seen_for_cycle.get(form_id, "")
    return {
        "sessions": sessions,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
