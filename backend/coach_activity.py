"""
Coach Activity Dashboard.

Aggregates engagement across two Circle spaces and one Monday board so the
coaching team can see, at a glance:

  - How many videos / posts students have submitted each day since cohort
    Day 1.
  - How many of those each coach has replied to (Circle comment by a coach).
  - Which posts have NO coach reply after 48 h (escalation flag).
  - Students posting more than 3 videos in a calendar week (rate-limit flag).
  - Private-tier video submissions on Monday board 5083952249 — total
    submitted vs total each coach has been assigned to reply to.

Caching: 30-minute Mongo SWR cache (per `coach_activity:*` key) — Circle
post + comment fetches are slow (a couple of seconds for a few dozen posts),
and the data is fine to be a few minutes stale.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone, timedelta, date
from typing import Any

import httpx

from connectors import CIRCLE_BASE, _circle_headers, MONDAY_URL, _monday_headers, TIMEOUT


# Circle space IDs for the April 26 cohort
RECORDED_ANSWER_SPACE_ID = 2529508          # /c/recorded-answer-review-apr-26/
INTERVIEW_SUPPORT_SPACE_ID = 2529509        # /c/specific-interview-support-apr-26/
PRIVATE_VIDEOS_BOARD_ID = 5083952249        # AYCI - Private video responses

# Day 1 cut-offs (cohort April 26)
RECORDED_ANSWERS_START = date(2026, 4, 4)   # Mon 4 Apr — recorded answer review
INTERVIEW_SUPPORT_START = date(2026, 4, 23) # Thu 23 Apr — interview support

# Coach roster — names must match Circle community_member display names exactly.
COACHES = [
    "Zinnirah Zainodin",
    "Anne Beh",
    "Charlotte Wyeth",
    "Anoop Chidambaram",
    "Kat Priddis",
    "Tessa Davis",
    "Becky Platt",
]
# Lowercased lookup so we can do tolerant matches against Circle's user_name.
COACHES_LC = {c.lower(): c for c in COACHES}

NO_REPLY_SLA_HOURS = 48
WEEKLY_VIDEO_LIMIT = 3


def _is_coach(name: str | None) -> bool:
    if not name:
        return False
    n = name.strip().lower()
    if n in COACHES_LC:
        return True
    # Tolerant: drop whitespace
    n2 = n.replace(" ", "")
    return any(c.lower().replace(" ", "") == n2 for c in COACHES)


def _coach_canonical(name: str | None) -> str | None:
    if not name:
        return None
    n = name.strip().lower()
    if n in COACHES_LC:
        return COACHES_LC[n]
    n2 = n.replace(" ", "")
    for c in COACHES:
        if c.lower().replace(" ", "") == n2:
            return c
    return None


# ---------- Circle helpers ----------------------------------------------------

async def _circle_list_posts_in_space(client: httpx.AsyncClient, space_id: int) -> list[dict]:
    """Pulls every post in a space, paginated."""
    out: list[dict] = []
    page = 1
    while page <= 50:
        r = await client.get(
            f"{CIRCLE_BASE}/posts",
            headers=_circle_headers(),
            params={"space_id": int(space_id), "per_page": 100, "page": page},
        )
        r.raise_for_status()
        body = r.json()
        recs = body.get("records") or body.get("data") or []
        out.extend(recs)
        if len(recs) < 100:
            break
        page += 1
    return out


async def _circle_list_comments_for_post(client: httpx.AsyncClient, post_id: int) -> list[dict]:
    """Pulls every comment for one post."""
    out: list[dict] = []
    page = 1
    while page <= 20:
        r = await client.get(
            f"{CIRCLE_BASE}/comments",
            headers=_circle_headers(),
            params={"post_id": int(post_id), "per_page": 100, "page": page},
        )
        if r.status_code != 200:
            break
        body = r.json()
        recs = body.get("records") or body.get("data") or []
        out.extend(recs)
        if len(recs) < 100:
            break
        page += 1
    return out


def _post_author_name(post: dict) -> str | None:
    return (post.get("user_name")
            or (post.get("community_member") or {}).get("name")
            or (post.get("user") or {}).get("name"))


def _comment_author_name(comment: dict) -> str | None:
    return (comment.get("user_name")
            or (comment.get("community_member") or {}).get("name")
            or (comment.get("user") or {}).get("name"))


def _post_url(post: dict) -> str | None:
    url = post.get("url")
    if url and url.startswith("http"):
        return url
    return None


# ---------- Public: Circle space analysis -------------------------------------

async def analyse_circle_space(
    space_id: int,
    start_date: date,
    label: str,
) -> dict:
    """
    Aggregate post + comment activity in one Circle space since `start_date`.

    Returns:
      {
        label, space_id,
        window: {start, end_today, days},
        total_posts, total_unique_authors,
        per_day:        [{date, count}, ...],   # zero-filled
        per_coach:      [{name, replies}],
        unanswered:     [post {id, name, url, author, created_at, hours_old}],   # > 48 h, no coach reply
        rate_limited:   [student {name, week_start, count, post_ids}],            # > 3 videos in calendar week
        last_refreshed: iso
      }
    """
    today = datetime.now(timezone.utc).date()
    cutoff_iso = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc).isoformat()
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        posts = await _circle_list_posts_in_space(c, space_id)

    # Filter: only top-level posts created on/after start_date (drop the pinned
    # "post your videos here" header that was created in March).
    in_window = [
        p for p in posts
        if (p.get("created_at") or "") >= cutoff_iso
    ]

    # Fan out comment lookups in parallel (cap concurrency)
    sem = asyncio.Semaphore(8)
    comments_by_post: dict[int, list[dict]] = {}

    async def _load(p: dict, client: httpx.AsyncClient):
        async with sem:
            try:
                cs = await _circle_list_comments_for_post(client, p["id"])
            except Exception:
                cs = []
            comments_by_post[p["id"]] = cs

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        await asyncio.gather(*(_load(p, c) for p in in_window))

    # Per-day counts (zero-filled)
    per_day_map: dict[str, int] = {}
    cur = start_date
    while cur <= today:
        per_day_map[cur.isoformat()] = 0
        cur = cur + timedelta(days=1)
    for p in in_window:
        d = (p.get("created_at") or "")[:10]
        if d in per_day_map:
            per_day_map[d] += 1
    per_day = [{"date": d, "count": n} for d, n in sorted(per_day_map.items())]

    # Per-coach reply count: count UNIQUE posts each coach replied to
    posts_replied_by_coach: dict[str, set[int]] = {c: set() for c in COACHES}
    answered_post_ids: set[int] = set()
    for pid, cs in comments_by_post.items():
        for cm in cs:
            canon = _coach_canonical(_comment_author_name(cm))
            if canon:
                posts_replied_by_coach[canon].add(pid)
                answered_post_ids.add(pid)

    per_coach = [
        {"name": c, "replies": len(posts_replied_by_coach[c])}
        for c in COACHES
    ]
    per_coach.sort(key=lambda x: x["replies"], reverse=True)

    # Unanswered (> 48 h, no coach reply)
    unanswered: list[dict] = []
    for p in in_window:
        if p["id"] in answered_post_ids:
            continue
        try:
            created = datetime.fromisoformat((p.get("created_at") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        age = now - created
        if age >= timedelta(hours=NO_REPLY_SLA_HOURS):
            unanswered.append({
                "id": p["id"],
                "name": p.get("name") or "(untitled)",
                "url": _post_url(p),
                "author": _post_author_name(p),
                "created_at": p.get("created_at"),
                "hours_old": int(age.total_seconds() // 3600),
            })
    unanswered.sort(key=lambda x: x["hours_old"], reverse=True)

    # Rate-limit: any student with > 3 posts in a single calendar (Mon-Sun) week
    by_author_week: dict[tuple[str, str], list[int]] = {}
    for p in in_window:
        author = _post_author_name(p) or "Unknown"
        if _is_coach(author):
            continue  # don't flag coach pinned posts
        try:
            created = datetime.fromisoformat((p.get("created_at") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        d = created.date()
        # Monday of that week (ISO weekday: Mon=1)
        monday = d - timedelta(days=d.weekday())
        key = (author, monday.isoformat())
        by_author_week.setdefault(key, []).append(p["id"])

    rate_limited = [
        {
            "name": author,
            "week_start": wk_start,
            "count": len(post_ids),
            "post_ids": post_ids,
        }
        for (author, wk_start), post_ids in by_author_week.items()
        if len(post_ids) > WEEKLY_VIDEO_LIMIT
    ]
    rate_limited.sort(key=lambda x: (x["count"], x["week_start"]), reverse=True)

    # Distinct authors (students)
    student_authors = {(_post_author_name(p) or "Unknown") for p in in_window if not _is_coach(_post_author_name(p))}

    return {
        "label": label,
        "space_id": space_id,
        "window": {
            "start": start_date.isoformat(),
            "end_today": today.isoformat(),
            "days": (today - start_date).days + 1,
        },
        "total_posts": len(in_window),
        "total_unique_authors": len(student_authors),
        "per_day": per_day,
        "per_coach": per_coach,
        "unanswered": unanswered,
        "rate_limited": rate_limited,
        "last_refreshed": now.isoformat(),
    }


# ---------- Monday: Private tier video submissions ----------------------------

async def fetch_private_video_submissions() -> dict:
    """
    Pull every item from the AYCI - Private video responses board and bucket
    by `Assigned to` (coach) + Status (Replied / New / etc.).
    """
    q = """
    query ($boardId: ID!, $cursor: String) {
      boards(ids: [$boardId]) {
        items_page(limit: 200, cursor: $cursor) {
          cursor
          items {
            id
            name
            url
            column_values {
              id
              text
              column { title }
              ... on PeopleValue { persons_and_teams { id kind } }
            }
          }
        }
      }
    }
    """

    items: list[dict] = []
    cursor: str | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while True:
            r = await c.post(
                MONDAY_URL,
                headers={**_monday_headers(), "Content-Type": "application/json"},
                json={"query": q, "variables": {"boardId": str(PRIVATE_VIDEOS_BOARD_ID), "cursor": cursor}},
            )
            r.raise_for_status()
            body = r.json()
            if body.get("errors"):
                break
            page = (body.get("data", {}).get("boards") or [{}])[0].get("items_page") or {}
            items.extend(page.get("items") or [])
            cursor = page.get("cursor")
            if not cursor:
                break

    # Resolve assigned coach person_id → name. We need a single user fetch.
    person_ids: set[int] = set()
    for it in items:
        for cv in it.get("column_values") or []:
            if cv.get("id") == "person":
                for p in cv.get("persons_and_teams") or []:
                    if p.get("kind") == "person":
                        person_ids.add(int(p["id"]))

    persons_by_id: dict[int, str] = {}
    if person_ids:
        ids_csv = ",".join(str(i) for i in person_ids)
        uq = f"query {{ users(ids: [{ids_csv}]) {{ id name }} }}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(
                MONDAY_URL,
                headers={**_monday_headers(), "Content-Type": "application/json"},
                json={"query": uq},
            )
            try:
                ud = r.json().get("data", {}).get("users") or []
                for u in ud:
                    persons_by_id[int(u["id"])] = u["name"]
            except Exception:
                pass

    # Aggregate
    by_coach_count: dict[str, int] = {c: 0 for c in COACHES}
    unassigned = 0
    new_count = 0
    replied_count = 0
    for it in items:
        cols = {cv["id"]: cv for cv in (it.get("column_values") or [])}
        # Status
        status = (cols.get("status", {}).get("text") or "").strip()
        if status.lower() == "replied":
            replied_count += 1
        elif status.lower() in ("new", ""):
            new_count += 1

        # Assigned coach
        person_cv = cols.get("person") or {}
        names: list[str] = []
        for p in person_cv.get("persons_and_teams") or []:
            if p.get("kind") == "person" and int(p["id"]) in persons_by_id:
                names.append(persons_by_id[int(p["id"])])
        if not names:
            unassigned += 1
            continue
        for n in names:
            canon = _coach_canonical(n)
            if canon:
                by_coach_count[canon] += 1

    per_coach = [{"name": c, "replies": by_coach_count[c]} for c in COACHES]
    per_coach.sort(key=lambda x: x["replies"], reverse=True)

    return {
        "board_id": PRIVATE_VIDEOS_BOARD_ID,
        "board_name": "AYCI - Private video responses",
        "total_submissions": len(items),
        "replied": replied_count,
        "new": new_count,
        "unassigned": unassigned,
        "per_coach": per_coach,
        "last_refreshed": datetime.now(timezone.utc).isoformat(),
    }


# ---------- Top-level fan-out -------------------------------------------------

async def fetch_coach_activity_summary() -> dict:
    """Top-level payload for the Coach Activity dashboard. Run all 3 fetches in parallel."""
    recorded_task = analyse_circle_space(RECORDED_ANSWER_SPACE_ID, RECORDED_ANSWERS_START, "Recorded Answer Review")
    interview_task = analyse_circle_space(INTERVIEW_SUPPORT_SPACE_ID, INTERVIEW_SUPPORT_START, "Specific Interview Support")
    private_task = fetch_private_video_submissions()
    recorded, interview, private = await asyncio.gather(
        recorded_task, interview_task, private_task, return_exceptions=True,
    )

    def safe(r):
        if isinstance(r, Exception):
            return {"error": str(r)}
        return r

    return {
        "coaches": COACHES,
        "recorded_answers": safe(recorded),
        "interview_support": safe(interview),
        "private_videos": safe(private),
    }
