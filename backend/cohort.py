"""
Cohort dashboard — aggregates Monday.com Academy Members board for one
cohort (e.g. "April 26"), cross-references Circle membership via the
slim cached member list, and returns totals for the team's weekly review.

New vs Legacy split now comes from ConvertKit tags because Monday's
"Legacy" column is only populated when a student carries over from a
previous cohort — it misses the "upgrade/downgrade" nuance that Kit
captures cleanly with dedicated tags.
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Any

import httpx

from connectors import MONDAY_URL, _monday_headers, TIMEOUT, CONVERTKIT_V3, _ck_secret, CIRCLE_BASE, _circle_headers

ACADEMY_MEMBERS_BOARD_ID = 1956295952

# Column IDs (same as Upcoming Interviews)
COL_TIER = "dropdown_mkqxgqbq"
COL_EMAIL = "email_mkqxv0j0"
COL_SPECIALITY = "dropdown_mkqxk94m"
COL_COHORT_JOINED = "dropdown_mkqxhw8p"
COL_LEGACY = "dropdown_mkqxpct4"
COL_IN_ACTIVE_COHORT = "color_mkrd1evr"
MILESTONE_COLS = [
    ("color_mkqxkrrp", "Milestone 1"),
    ("color_mkqxxhp6", "Milestone 2"),
    ("color_mkqxt5y",  "Milestone 3"),
    ("color_mkqxteyn", "Milestone 4"),
    ("color_mkqx4xmy", "Milestone 5"),
]

# Defaults for April 2026 cohort
DEFAULT_NEW_TAG_ID = 14407610    # "[AYCI APR-26] Cohort - New"
DEFAULT_LEGACY_TAG_ID = 14407628  # "[AYCI APR-26] Cohort - Legacy"
DEFAULT_INTROS_SPACE_ID = 2529515  # "Introduce Yourself" (April 26)


async def _fetch_cohort_items(cohort_label: str) -> list[dict]:
    """Fetch all board items whose Cohort Joined equals cohort_label."""
    # Discover dropdown id for the label
    schema_q = f"""
    query {{ boards(ids: [{ACADEMY_MEMBERS_BOARD_ID}]) {{
      columns(ids: ["{COL_COHORT_JOINED}"]) {{ settings_str }} }} }}
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            MONDAY_URL,
            headers={**_monday_headers(), "Content-Type": "application/json"},
            json={"query": schema_q},
        )
        r.raise_for_status()
        import json
        settings = json.loads(
            r.json()["data"]["boards"][0]["columns"][0]["settings_str"]
        )
        labels = settings.get("labels", [])
        target = None
        for lab in labels:
            if str(lab.get("name", "")).strip().lower() == cohort_label.strip().lower():
                target = int(lab["id"])
                break
        if target is None:
            raise ValueError(f"Cohort label {cohort_label!r} not found on Monday board")

        items: list[dict] = []
        cursor: str | None = None
        while True:
            if cursor is None:
                query = """
                query ($boardId: ID!, $val: CompareValue!, $limit: Int!) {
                  boards(ids: [$boardId]) {
                    items_page(
                      limit: $limit,
                      query_params: { rules: [{ column_id: "%s", compare_value: $val }] }
                    ) {
                      cursor
                      items {
                        id
                        name
                        column_values { id text column { title } }
                      }
                    }
                  }
                }
                """ % COL_COHORT_JOINED
                variables = {
                    "boardId": str(ACADEMY_MEMBERS_BOARD_ID),
                    "val": [target],
                    "limit": 100,
                }
            else:
                query = """
                query ($boardId: ID!, $limit: Int!, $cursor: String!) {
                  boards(ids: [$boardId]) {
                    items_page(limit: $limit, cursor: $cursor) {
                      cursor
                      items {
                        id
                        name
                        column_values { id text column { title } }
                      }
                    }
                  }
                }
                """
                variables = {
                    "boardId": str(ACADEMY_MEMBERS_BOARD_ID),
                    "limit": 100,
                    "cursor": cursor,
                }
            r = await c.post(
                MONDAY_URL,
                headers={**_monday_headers(), "Content-Type": "application/json"},
                json={"query": query, "variables": variables},
            )
            r.raise_for_status()
            body = r.json()
            if body.get("errors"):
                raise RuntimeError(f"Monday error: {body['errors']}")
            page = (body.get("data", {}).get("boards") or [{}])[0].get("items_page") or {}
            items.extend(page.get("items") or [])
            cursor = page.get("cursor")
            if not cursor or not (page.get("items") or []):
                break
        return items


async def cohort_summary(
    db,
    cohort_label: str,
    circle_tag: str | None = None,
    new_tag_id: int | None = None,
    legacy_tag_id: int | None = None,
    intros_space_id: int | None = None,
) -> dict:
    """
    Aggregates cohort state across Monday + Circle + ConvertKit.

    - new_tag_id / legacy_tag_id: ConvertKit tag IDs for the cohort's
      "Cohort - New" / "Cohort - Legacy" tags. When omitted and the cohort
      is April 26, defaults are used.
    - intros_space_id: Circle space id for the "Introduce Yourself" space.
    """
    # Defaults for April 2026 if unspecified
    if new_tag_id is None and cohort_label.strip().lower() == "april 26":
        new_tag_id = DEFAULT_NEW_TAG_ID
    if legacy_tag_id is None and cohort_label.strip().lower() == "april 26":
        legacy_tag_id = DEFAULT_LEGACY_TAG_ID
    if intros_space_id is None and cohort_label.strip().lower() == "april 26":
        intros_space_id = DEFAULT_INTROS_SPACE_ID

    items = await _fetch_cohort_items(cohort_label)
    total = len(items)

    def _txt(cols: list[dict], col_id: str) -> str:
        for c in cols:
            if c.get("id") == col_id:
                return (c.get("text") or "").strip()
        return ""

    tier_counter: Counter = Counter()
    emails: set[str] = set()
    active_cohort_count = 0
    milestone_totals = [0 for _ in MILESTONE_COLS]
    specialities: Counter = Counter()

    for it in items:
        cols = it.get("column_values") or []
        # Tier split (may contain multiple comma-separated values — take primary)
        tier = _txt(cols, COL_TIER) or "(no tier)"
        # Some students have tier like "Academy, Boost & Go Plus" — split
        first_tier = tier.split(",")[0].strip()
        tier_counter[first_tier] += 1

        # Email
        email = _txt(cols, COL_EMAIL).lower()
        if email:
            emails.add(email)

        # In active cohort
        if _txt(cols, COL_IN_ACTIVE_COHORT).lower() == "yes":
            active_cohort_count += 1

        # Speciality
        sp = _txt(cols, COL_SPECIALITY)
        if sp:
            specialities[sp.split(",")[0].strip()] += 1

        # Milestones
        for i, (cid, _) in enumerate(MILESTONE_COLS):
            if _txt(cols, cid).strip().lower() == "yes":
                milestone_totals[i] += 1

    # New vs Legacy from ConvertKit tags (authoritative)
    new_count = 0
    legacy_count = 0
    new_emails: set[str] = set()
    legacy_emails: set[str] = set()
    kit_error: str | None = None
    if new_tag_id or legacy_tag_id:
        try:
            if new_tag_id:
                new_emails = await _ck_tag_emails(int(new_tag_id))
                new_count = len(new_emails)
            if legacy_tag_id:
                legacy_emails = await _ck_tag_emails(int(legacy_tag_id))
                legacy_count = len(legacy_emails)
        except Exception as e:
            kit_error = str(e)

    # Circle cross-reference
    circle_tag_name = circle_tag or _derive_circle_tag(cohort_label)
    circle_matched = 0
    circle_tagged_total = 0
    circle_cache_available = False

    doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
    if doc:
        circle_cache_available = True
        members = doc.get("members", [])
        by_email = {m.get("email", "").strip().lower(): m for m in members if m.get("email")}
        for m in members:
            tags = m.get("member_tags") or []
            if any(t and t.strip().lower() == circle_tag_name.strip().lower() for t in tags):
                circle_tagged_total += 1
        for email in emails:
            m = by_email.get(email)
            if not m:
                continue
            tags = m.get("member_tags") or []
            if any(t and t.strip().lower() == circle_tag_name.strip().lower() for t in tags):
                circle_matched += 1

    milestones_payload = [
        {
            "label": lbl,
            "completed": milestone_totals[i],
            "total": total,
            "percent": round(milestone_totals[i] / total * 100, 1) if total else 0.0,
        }
        for i, (_, lbl) in enumerate(MILESTONE_COLS)
    ]

    # Intros-space post count (Circle): how many cohort students have posted there
    intros_posters = 0
    intros_total_posts = 0
    intros_error: str | None = None
    if intros_space_id:
        try:
            intros_emails = await _circle_space_post_authors(int(intros_space_id))
            intros_total_posts = intros_emails.get("post_count", 0)
            poster_emails = intros_emails.get("emails", set())
            intros_posters = len(emails & poster_emails)
        except Exception as e:
            intros_error = str(e)

    return {
        "cohort": cohort_label,
        "totals": {
            "students": total,  # Monday board headcount
            "new": new_count,
            "legacy": legacy_count,
            "new_plus_legacy": new_count + legacy_count,
            "in_active_cohort": active_cohort_count,
            "with_email": len(emails),
            "source": "convertkit" if (new_count + legacy_count) else "monday",
        },
        "tiers": [
            {"tier": t, "count": n, "percent": round(n / total * 100, 1) if total else 0.0}
            for t, n in tier_counter.most_common()
        ],
        "specialities": [
            {"speciality": s, "count": n} for s, n in specialities.most_common(10)
        ],
        "milestones": milestones_payload,
        "circle": {
            "tag": circle_tag_name,
            "cache_available": circle_cache_available,
            "students_on_circle": circle_matched,
            "students_total": total,
            "coverage_percent": round(circle_matched / total * 100, 1) if total else 0.0,
            "tag_total_in_circle": circle_tagged_total,
            "intros": {
                "space_id": intros_space_id,
                "posts_total": intros_total_posts,
                "students_posted": intros_posters,
                "students_total": total,
                "coverage_percent": round(intros_posters / total * 100, 1) if total else 0.0,
                "error": intros_error,
            },
        },
        "kit": {
            "new_tag_id": new_tag_id,
            "legacy_tag_id": legacy_tag_id,
            "error": kit_error,
        },
    }


def _derive_circle_tag(cohort_label: str) -> str:
    """'April 26' → \"Apr '26\" (Circle's tag convention)."""
    parts = cohort_label.strip().split()
    if len(parts) != 2:
        return cohort_label
    month, year = parts
    month_abbr = month[:3].capitalize()
    yy = year[-2:]
    return f"{month_abbr} '{yy}"


async def _ck_tag_emails(tag_id: int) -> set[str]:
    """Fetch all email addresses currently subscribed to a ConvertKit tag."""
    out: set[str] = set()
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while page <= 200:
            r = await c.get(
                f"{CONVERTKIT_V3}/tags/{tag_id}/subscriptions",
                params={"api_secret": _ck_secret(), "page": page, "sort_order": "desc"},
            )
            r.raise_for_status()
            body = r.json()
            subs = body.get("subscriptions", [])
            if not subs:
                break
            for s in subs:
                sub = s.get("subscriber") or {}
                email = (sub.get("email_address") or "").strip().lower()
                if email:
                    out.add(email)
            total_pages = body.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
    return out


async def _circle_space_post_authors(space_id: int) -> dict:
    """
    Return the emails of all users who have posted in a Circle space,
    plus the total post count.
    """
    emails: set[str] = set()
    count = 0
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while page <= 100:
            r = await c.get(
                f"{CIRCLE_BASE}/posts",
                headers=_circle_headers(),
                params={"space_id": space_id, "per_page": 100, "page": page, "sort": "created_at", "order": "desc"},
            )
            r.raise_for_status()
            body = r.json()
            recs = body.get("records") or body.get("data") or []
            if not recs:
                break
            for p in recs:
                count += 1
                e = (p.get("user_email") or "").strip().lower()
                if e:
                    emails.add(e)
            if len(recs) < 100:
                break
            page += 1
    return {"emails": emails, "post_count": count}
