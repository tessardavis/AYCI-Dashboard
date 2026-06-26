"""
Cohort dashboard - aggregates Monday.com Academy Members board for one
cohort (e.g. "April 26"), cross-references Circle membership via the
slim cached member list, and returns totals for the team's weekly review.

New vs Legacy split now comes from ConvertKit tags because Monday's
"Legacy" column is only populated when a student carries over from a
previous cohort - it misses the "upgrade/downgrade" nuance that Kit
captures cleanly with dedicated tags.
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Any

import httpx

from connectors import MONDAY_URL, _monday_headers, TIMEOUT, CONVERTKIT_V3, _ck_secret, CIRCLE_BASE, _circle_headers

ACADEMY_MEMBERS_BOARD_ID = 1956295952

# Team-account emails that should NEVER appear on the "still to join Circle"
# chase list, even when tagged as new signups in ConvertKit. These are AYCI
# internal accounts used for testing / auto-bots.
TEAM_ACCOUNT_EMAILS = {
    "tessadavis06@gmail.com",
    "tessadavis06+1@gmail.com",
    "arubyousufwork@gmail.com",
}

# Column IDs (same as Upcoming Interviews)
COL_TIER = "dropdown_mkqxgqbq"
COL_EMAIL = "email_mkqxv0j0"
COL_SPECIALITY = "dropdown_mkqxk94m"
COL_COHORT_JOINED = "dropdown_mkqxhw8p"
COL_LEGACY = "dropdown_mkqxpct4"
COL_IN_ACTIVE_COHORT = "color_mkrd1evr"
# Manually-curated Monday status column: "On Circle, in Apr '26 spaces" /
# "On Circle, not in spaces" / blank. When set to the in-cohort-spaces
# variant, the student has been manually verified as joined for the cohort
# - authoritative signal that bridges email mismatches between Monday and
# Circle (students often sign up to Circle with a different email).
COL_ON_CIRCLE = "color_mkqxdbm8"
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


async def fetch_cohort_labels() -> list[dict]:
    """
    Returns the live list of cohort labels from Monday's 'Cohort Joined'
    dropdown (id `dropdown_mkqxhw8p`). Newest first.
    """
    query = f"""
    query {{ boards(ids: [{ACADEMY_MEMBERS_BOARD_ID}]) {{
      columns(ids: ["{COL_COHORT_JOINED}"]) {{ settings_str }} }} }}
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            MONDAY_URL,
            headers={**_monday_headers(), "Content-Type": "application/json"},
            json={"query": query},
        )
        r.raise_for_status()
        import json
        settings = json.loads(
            r.json()["data"]["boards"][0]["columns"][0]["settings_str"]
        )
        labels = settings.get("labels", [])
    # Monday dropdown labels carry an incrementing id; higher id = more recent
    sorted_labels = sorted(labels, key=lambda x: int(x.get("id", 0)), reverse=True)
    return [{"id": int(x["id"]), "name": x["name"]} for x in sorted_labels]


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
    # Pull the cohort's config (ConvertKit tag IDs, Circle tag, Intros space)
    # from the admin-editable settings. Any value passed explicitly to this
    # function still wins; otherwise we fall back to the configured cohort,
    # then (for circle_tag) to the derived abbreviation. This replaces the old
    # April-only hardcode so every cohort works without a code change.
    import settings_store
    _configs = await settings_store.get_cohort_configs(db)
    _label = cohort_label.strip()
    cohort_cfg = _configs.get(_label) or next(
        (v for k, v in _configs.items() if k.strip().lower() == _label.lower()), {}
    )
    if new_tag_id is None:
        new_tag_id = cohort_cfg.get("new_tag_id")
    if legacy_tag_id is None:
        legacy_tag_id = cohort_cfg.get("legacy_tag_id")
    if intros_space_id is None:
        intros_space_id = cohort_cfg.get("intros_space_id")
    if circle_tag is None:
        circle_tag = cohort_cfg.get("circle_tag")

    items = await _fetch_cohort_items(cohort_label)
    monday_total = len(items)  # all Monday students with Cohort Joined = this cohort

    def _txt(cols: list[dict], col_id: str) -> str:
        for c in cols:
            if c.get("id") == col_id:
                return (c.get("text") or "").strip()
        return ""

    # New vs Legacy from ConvertKit tags (authoritative). We need `new_emails`
    # before the per-item loop so we can filter stats to new signups only -
    # the team tracks "cohort" = "new signups in this launch", not upgrades.
    new_count = 0
    legacy_count = 0
    new_emails: set[str] = set()
    new_signup_dates: dict[str, str] = {}  # email → ConvertKit subscription created_at
    legacy_emails: set[str] = set()
    kit_error: str | None = None
    if new_tag_id or legacy_tag_id:
        try:
            if new_tag_id:
                new_signup_dates = await _ck_tag_email_dates(int(new_tag_id))
                new_emails = set(new_signup_dates.keys())
                new_count = len(new_emails)
            if legacy_tag_id:
                legacy_emails = await _ck_tag_emails(int(legacy_tag_id))
                legacy_count = len(legacy_emails)
        except Exception as e:
            kit_error = str(e)

    tier_counter: Counter = Counter()
    emails: set[str] = set()  # all Monday emails for this cohort (new + legacy)
    cohort_emails: set[str] = set()  # Monday ∩ (ConvertKit Cohort-New ∪ Cohort-Legacy)
    active_cohort_count = 0
    milestone_totals = [0 for _ in MILESTONE_COLS]
    specialities: Counter = Counter()
    monday_by_email: dict[str, dict] = {}

    cohort_tag_emails = new_emails | legacy_emails

    for it in items:
        cols = it.get("column_values") or []
        email = _txt(cols, COL_EMAIL).lower()
        if email:
            emails.add(email)

        # Cohort = new + legacy signups (i.e. anyone tagged as part of this
        # launch in ConvertKit). When ConvertKit data isn't loaded yet we
        # fall back to the Monday cohort filter only.
        is_in_cohort = email in cohort_tag_emails if cohort_tag_emails else True
        if is_in_cohort and email:
            cohort_emails.add(email)

        if _txt(cols, COL_IN_ACTIVE_COHORT).lower() == "yes":
            active_cohort_count += 1

        # Skip non-cohort students for the breakdown stats
        if not is_in_cohort:
            continue

        # Tier split (may contain multiple comma-separated values - take primary)
        tier = _txt(cols, COL_TIER) or "(no tier)"
        first_tier = tier.split(",")[0].strip()
        tier_counter[first_tier] += 1

        # Speciality
        sp = _txt(cols, COL_SPECIALITY)
        if sp:
            specialities[sp.split(",")[0].strip()] += 1

        # Milestones
        for i, (cid, _) in enumerate(MILESTONE_COLS):
            if _txt(cols, cid).strip().lower() == "yes":
                milestone_totals[i] += 1

        # Stash for the "still to join Circle" list
        if email:
            monday_by_email[email] = {
                "name": (it.get("name") or "").strip(),
                "tier": first_tier,
                "monday_url": it.get("url"),
                "on_circle_status": _txt(cols, COL_ON_CIRCLE),
            }

    # Two denominators:
    # - `cohort_total` = new + legacy (the team's headline "cohort size") -
    #   used for the top stat card and the On Circle / Intros coverage.
    # - `monday_cohort_total` = the subset of those who are also on the
    #   Monday board for this cohort - used for tier/milestone/speciality
    #   breakdowns so percentages sum within the visible Monday data.
    if cohort_tag_emails:
        cohort_total = new_count + legacy_count
        monday_cohort_total = len(cohort_emails)
    else:
        cohort_total = monday_total
        monday_cohort_total = monday_total

    # Circle cross-reference - count only NEW signups (not legacy) who joined
    # Circle for this cohort. Tessa wants the "On Circle" / Pending counts to
    # measure the launch's job, i.e. getting new customers onto Circle. Legacy
    # students are already established on Circle from prior cohorts.
    circle_tag_name = circle_tag or _derive_circle_tag(cohort_label)
    circle_matched = 0
    circle_tagged_total = 0
    circle_cache_available = False
    circle_emails_with_tag: set[str] = set()  # NEW-cohort emails on Circle with cohort tag

    full_cohort_emails = (new_emails | legacy_emails) if cohort_tag_emails else emails
    new_only_emails = new_emails if cohort_tag_emails else emails  # scope for Circle stats

    by_email: dict[str, dict] = {}

    doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
    if doc:
        circle_cache_available = True
        members = doc.get("members", [])
        by_email = {m.get("email", "").strip().lower(): m for m in members if m.get("email")}
        for m in members:
            tags = m.get("member_tags") or []
            if any(t and t.strip().lower() == circle_tag_name.strip().lower() for t in tags):
                circle_tagged_total += 1
        for email in new_only_emails:
            m = by_email.get(email)
            if not m:
                continue
            tags = m.get("member_tags") or []
            if any(t and t.strip().lower() == circle_tag_name.strip().lower() for t in tags):
                circle_matched += 1
                circle_emails_with_tag.add(email)

    # Build a quick "has Boss badge" set so we can exclude students who have
    # already landed a job (Boss = job-secured indicator on Circle).
    boss_emails: set[str] = set()
    if doc:
        for m in (doc.get("members") or []):
            email = (m.get("email") or "").strip().lower()
            if not email:
                continue
            for t in (m.get("member_tags") or []):
                name = t.get("name") if isinstance(t, dict) else str(t or "")
                if (name or "").strip().lower() == "boss":
                    boss_emails.add(email)
                    break

    # ---- "Still to join Circle" - chase list (NEW signups only) -----------
    # Limit to new signups (the launch's primary onboarding job). Legacy
    # students are excluded - they're either already long-time Circle members
    # or chased through other workflows. Team test accounts (TEAM_ACCOUNT_EMAILS)
    # are also excluded so the coach doesn't chase themselves. Students with
    # the "Boss" badge on Circle are excluded too - they already have a job
    # and don't need chasing into the cohort space.
    #
    # Additionally, students whose Monday "On Circle" column is manually set
    # to "On Circle, in <cohort> spaces" are excluded. This is the team's
    # authoritative join signal and bridges email mismatches between
    # Monday/ConvertKit and Circle (students often register on Circle with a
    # different email than they gave us at signup).
    circle_tag_short = circle_tag_name.strip().lower()  # e.g. "apr '26"
    monday_confirmed_joined: set[str] = set()
    for em, info in monday_by_email.items():
        status = (info.get("on_circle_status") or "").strip().lower()
        if not status:
            continue
        # Accept either the cohort-specific variant ("on circle, in apr '26
        # spaces") or a generic "on circle, in <x> spaces" that names the
        # same circle tag. The "not in spaces" variant does NOT count -
        # those students have a Circle account but haven't joined the
        # cohort's space yet, so they should stay on the chase list.
        if "in" in status and "spaces" in status and circle_tag_short in status:
            monday_confirmed_joined.add(em)

    circle_denominator = len(new_only_emails)
    pending_emails = sorted(
        (
            ((new_only_emails - circle_emails_with_tag) - TEAM_ACCOUNT_EMAILS)
            - boss_emails
        )
        - monday_confirmed_joined
    )
    pending_list: list[dict] = []
    pending_tier_counter: Counter = Counter()
    for email in pending_emails:
        info = monday_by_email.get(email) or {}
        circle_member = by_email.get(email) or {}
        if not info.get("name"):
            cm_name = (
                circle_member.get("name")
                or " ".join(
                    filter(None, [
                        circle_member.get("first_name"),
                        circle_member.get("last_name"),
                    ])
                )
                or ""
            ).strip()
            info = {"name": cm_name, "tier": "(unknown)", "monday_url": None}
        tier = info.get("tier") or "(unknown)"
        # Has a Circle account (any tag) but not the cohort tag - useful to know
        on_circle_no_tag = email in by_email
        pending_tier_counter[tier] += 1
        pending_list.append({
            "email": email,
            "name": info.get("name") or "",
            "tier": tier,
            "monday_url": info.get("monday_url"),
            "has_circle_account": on_circle_no_tag,
            "signup_date": new_signup_dates.get(email),
        })
    # Sort: highest-tier-first (VIP / Private Plus / Boost / Academy), name asc within tier
    _tier_priority = {
        "VIP": 0, "Upgrade VIP": 0,
        "Private Plus": 1, "Academy Private Plus": 1, "Upgrade Private Plus": 1,
        "Boost": 2, "Go Plus": 2,
        "Academy": 3,
        "(no tier)": 4, "(unknown)": 5,
    }
    # Sort: tier priority first, then OLDEST signup at top (longest waiting =
    # most overdue to chase), then name as a final tiebreaker.
    pending_list.sort(key=lambda r: (
        _tier_priority.get(r["tier"], 6),
        r.get("signup_date") or "9999-99-99",
        r["name"].lower(),
    ))

    milestones_payload = [
        {
            "label": lbl,
            "completed": milestone_totals[i],
            # Milestones come from Monday columns - use the Monday subset
            # as denominator so percentages reflect the visible population.
            "total": monday_cohort_total,
            "percent": (
                round(milestone_totals[i] / monday_cohort_total * 100, 1)
                if monday_cohort_total
                else 0.0
            ),
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
            intros_posters = len(full_cohort_emails & poster_emails)
        except Exception as e:
            intros_error = str(e)

    return {
        "cohort": cohort_label,
        "totals": {
            # `students` = new + legacy from Kit (the headline cohort size).
            "students": cohort_total,
            "monday_cohort_total": monday_cohort_total,
            "monday_total": monday_total,
            "new": new_count,
            "legacy": legacy_count,
            "new_plus_legacy": new_count + legacy_count,
            "in_active_cohort": active_cohort_count,
            "with_email": len(emails),
            "source": "convertkit" if (new_count + legacy_count) else "monday",
        },
        "tiers": [
            {
                "tier": t,
                "count": n,
                "percent": (
                    round(n / monday_cohort_total * 100, 1)
                    if monday_cohort_total
                    else 0.0
                ),
            }
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
            "students_total": circle_denominator,
            "scope": "new_signups_only",
            "coverage_percent": (
                round(circle_matched / circle_denominator * 100, 1)
                if circle_denominator else 0.0
            ),
            "tag_total_in_circle": circle_tagged_total,
            "pending": {
                "count": len(pending_list),
                "by_tier": [
                    {"tier": t, "count": n}
                    for t, n in sorted(
                        pending_tier_counter.items(),
                        key=lambda x: _tier_priority.get(x[0], 6),
                    )
                ],
                "list": pending_list,
            },
            "intros": {
                "space_id": intros_space_id,
                "posts_total": intros_total_posts,
                "students_posted": intros_posters,
                "students_total": cohort_total,
                "coverage_percent": (
                    round(intros_posters / cohort_total * 100, 1) if cohort_total else 0.0
                ),
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


async def _ck_tag_email_dates(tag_id: int) -> dict[str, str]:
    """Like `_ck_tag_emails` but returns `{email: signup_date_iso}`. The
    signup date is the subscription's `created_at` (when this person was
    tagged - i.e. when they joined this cohort)."""
    out: dict[str, str] = {}
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
                created = s.get("created_at") or sub.get("created_at") or ""
                if email and email not in out:
                    out[email] = created
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
