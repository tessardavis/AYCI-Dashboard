"""
Mongo mirror of Monday's Academy Members board (1956295952).

Why:
  Both Student Lookup and Upcoming Interviews currently hit Monday's
  GraphQL on every request. That's slow (1-3s per call) and tied to
  Monday's API availability + rate limits. A local Mongo mirror lets us
  serve those reads in <50ms.

Schema (db.academy_members, keyed by Monday item_id):
  {
    _id: "<monday_item_id>",
    name: "Henry Wilson",                    # Monday item name
    url: "https://...",                      # Monday item URL
    monday_created_at: ISODate,              # When the item was first added on Monday
    # Frequently-queried fields surfaced as top-level for indexing:
    email: "henry@example.com",              # email_mkqxv0j0 (lowercased)
    circle_email: "...",                     # email_mkqxyfhm (lowercased)
    first_name: "...",
    surname: "...",
    tier: "Platinum",                        # dropdown_mkqxgqbq text
    cohort_joined: "April 26",               # dropdown_mkqxhw8p text
    interview_date: "2026-06-14",            # date_mkr7rdv7 text (ISO yyyy-mm-dd)
    speciality: "...",                       # dropdown_mkqxk94m text
    hospital: "...",                         # text_mkrqzraa
    interview_type: "...",                   # color_mkr7wahg text (status)
    private_chat_url: "...",                 # text_mky9xzew
    video_allowance: 20,                     # numeric_mkxfvz1k
    videos_submitted: 4,                     # numeric_mkxfq65c
    # And the full raw columns dict for Student Lookup's card (which
    # renders any column it knows about):
    columns: {<col_title>: {text, type}, ...},        # keyed by column title
    columns_by_id: {<col_id>: {text, type, title}, ...},
    synced_at: ISODate,
  }

Indexes:
  - email (sparse, unique-ish — Monday occasionally has dupes so non-unique)
  - circle_email (sparse)
  - interview_date (for Upcoming Interviews range queries)
  - synced_at (for stale-row checks)

Manual refresh: POST /api/admin/academy-mirror/sync
Scheduled: every 15 minutes via apscheduler.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from connectors import MONDAY_URL, _monday_headers, TIMEOUT

logger = logging.getLogger(__name__)

ACADEMY_MEMBERS_BOARD_ID = 1956295952

# Column ID → top-level Mongo field mapping for the fields callers query
# directly. Everything else lives in raw columns dicts.
COL_EMAIL = "email_mkqxv0j0"
COL_CIRCLE_EMAIL = "email_mkqxyfhm"
COL_FIRST_NAME = "text_mkrmj089"
COL_SURNAME = "text_mkrm6m7v"
COL_TIER = "dropdown_mkqxgqbq"
COL_COHORT_JOINED = "dropdown_mkqxhw8p"
COL_INTERVIEW_DATE = "date_mkr7rdv7"
COL_SPECIALITY = "dropdown_mkqxk94m"
COL_HOSPITAL = "text_mkrqzraa"
COL_INTERVIEW_TYPE = "color_mkr7wahg"
COL_PRIVATE_CHAT_URL = "text_mky9xzew"
COL_VIDEO_ALLOWANCE = "numeric_mkxfvz1k"
COL_VIDEOS_SUBMITTED = "numeric_mkxfq65c"


def _to_int_or_none(s: Optional[str]) -> Optional[int]:
    if s is None or s == "":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _extract_row(item: dict) -> dict:
    """Map one Monday item → Mongo row shape."""
    cols_raw = item.get("column_values") or []
    columns_by_id: dict[str, dict] = {}
    columns_by_title: dict[str, dict] = {}
    for col in cols_raw:
        cid = col.get("id")
        title = (col.get("column") or {}).get("title")
        entry = {
            "text": col.get("text"),
            "type": col.get("type"),
        }
        if cid:
            columns_by_id[cid] = {**entry, "title": title}
        if title:
            columns_by_title[title] = entry

    def col_text(col_id: str) -> Optional[str]:
        c = columns_by_id.get(col_id)
        if not c:
            return None
        t = c.get("text")
        return t if (t and t.strip()) else None

    return {
        "_id": str(item.get("id")),
        "name": item.get("name"),
        "url": item.get("url"),
        "monday_created_at": item.get("created_at"),
        "email": (col_text(COL_EMAIL) or "").strip().lower() or None,
        "circle_email": (col_text(COL_CIRCLE_EMAIL) or "").strip().lower() or None,
        "first_name": col_text(COL_FIRST_NAME),
        "surname": col_text(COL_SURNAME),
        "tier": col_text(COL_TIER),
        "cohort_joined": col_text(COL_COHORT_JOINED),
        "interview_date": col_text(COL_INTERVIEW_DATE),
        "speciality": col_text(COL_SPECIALITY),
        "hospital": col_text(COL_HOSPITAL),
        "interview_type": col_text(COL_INTERVIEW_TYPE),
        "private_chat_url": col_text(COL_PRIVATE_CHAT_URL),
        "video_allowance": _to_int_or_none(col_text(COL_VIDEO_ALLOWANCE)),
        "videos_submitted": _to_int_or_none(col_text(COL_VIDEOS_SUBMITTED)),
        "columns": columns_by_title,
        "columns_by_id": columns_by_id,
        "synced_at": datetime.now(timezone.utc),
    }


# Fields that, once a coach has edited them in the dashboard, the
# 15-min Monday sync must NOT overwrite. Tracked per-row in
# `dashboard_edited_fields` — listing a field name there pins it to the
# dashboard value. When we eventually retire Monday, this will be the
# full schema; for now coaches add fields as they edit them.
PROTECTED_FIELDS = {
    # Scalar columns the mirror extracts from Monday today
    "name", "first_name", "surname", "email", "circle_email",
    "tier", "cohort_joined", "interview_date", "speciality", "hospital",
    "interview_type", "private_chat_url", "video_allowance",
    "videos_submitted",
    # Fields not yet extracted by the mirror but tracked on the row when
    # automations (Zapier) write them. Adding new ones here is the standard
    # path for migrating a zap — the mirror won't extract or clobber these,
    # and dashboard_edited_fields keeps them safe regardless.
    "intro_post",
    "milestone_1", "milestone_2", "milestone_3", "milestone_4", "milestone_5",
    "private_spaces",
    "testimonial_requested", "testimonial_fu_1",
    # Mock interview + 1:1 status fields (used by Calendly zaps 14, 18)
    "mock_interview_status",
    "mock_interview_1", "mock_interview_2", "gold_call", "platinum_call",
    "mock_interview_cohort_before_april",
    "call_1", "call_2", "call_3", "call_4",
    "call_1_status", "call_2_status", "call_3_status", "call_4_status",
    # 15-minute call status (Calendly zaps 15/16). Monday labels: Eligible | Booked.
    "fifteen_minute_call",
    # Boss Badge status (zap 8c — substantive success form). Monday label: Yes.
    "boss_badge",
    # Kajabi add-on purchases (order bump + upsells). Dashboard-owned — NOT on
    # Monday. Set "Yes" by the Kajabi purchase-capture zap (via update-by-email),
    # keyed to the offer the student bought. The toolkit site reads these via
    # GET/POST /api/toolkit/access to gate material access.
    #   addon_curveball_questions  → "10 Real Curveball Questions" (order bump, Kajabi offer 2151209227)
    #   addon_question_sets        → "30 Recent Question Sets" (upsell, Kajabi offer 2151209222)
    #   addon_pre_interview_toolkit→ "The Pre-Interview Visits Toolkit" (upsell, Kajabi offer 2151209231)
    "addon_curveball_questions",
    "addon_question_sets",
    "addon_pre_interview_toolkit",
}


async def full_sync(db) -> dict:
    """Pull every Academy Members row from Monday and upsert into Mongo.

    Stale rows (members removed from the board since the last sync) are
    deleted afterward so we don't keep ghosts around.

    Coach edits made via the dashboard are protected — for any field
    name listed in a row's `dashboard_edited_fields` array, this sync
    does NOT overwrite. Lets us migrate to dashboard-only edits one
    field at a time without losing changes mid-transition.

    Returns a summary dict for logging / the admin endpoint."""
    started = time.monotonic()
    q = """
    query ($boardId: ID!, $limit: Int!, $cursor: String) {
      boards(ids: [$boardId]) {
        items_page(limit: $limit, cursor: $cursor) {
          cursor
          items {
            id name url created_at
            column_values {
              id text type
              column { title }
            }
          }
        }
      }
    }
    """
    cursor: Optional[str] = None
    seen_ids: set[str] = set()
    total = 0
    errors = 0
    page = 0

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # Cap at 100 pages × 100 rows = 10k students. Board is currently ~3.5k.
        for _ in range(100):
            page += 1
            vars_: dict = {
                "boardId": str(ACADEMY_MEMBERS_BOARD_ID),
                "limit": 100,
            }
            if cursor:
                vars_["cursor"] = cursor
            try:
                r = await c.post(
                    MONDAY_URL,
                    headers={**_monday_headers(), "Content-Type": "application/json"},
                    json={"query": q, "variables": vars_},
                )
                r.raise_for_status()
                body = r.json()
            except Exception as e:
                logger.warning(f"[academy-mirror] page {page} fetch failed: {e}")
                errors += 1
                break

            if body.get("errors"):
                logger.warning(f"[academy-mirror] page {page} GraphQL errors: {body['errors']}")
                errors += 1
                break

            page_data = (
                (body.get("data") or {})
                .get("boards", [{}])[0]
                .get("items_page") or {}
            )
            items = page_data.get("items") or []
            if not items:
                break

            # Upsert this batch — but skip any fields the dashboard has
            # claimed via dashboard_edited_fields.
            for it in items:
                row = _extract_row(it)
                seen_ids.add(row["_id"])
                try:
                    # Load existing row's edited-fields list so we can
                    # filter the Monday-supplied values before writing.
                    existing = await db.academy_members.find_one(
                        {"_id": row["_id"]},
                        {"_id": 0, "dashboard_edited_fields": 1},
                    )
                    edited = set(((existing or {}).get("dashboard_edited_fields") or []))
                    # Always write the column dicts + sync metadata.
                    write = {
                        "columns": row["columns"],
                        "columns_by_id": row["columns_by_id"],
                        "synced_at": row["synced_at"],
                        "url": row["url"],
                        "monday_created_at": row["monday_created_at"],
                    }
                    # For protected scalar fields, only write if NOT
                    # dashboard-edited.
                    for f in PROTECTED_FIELDS:
                        if f in edited:
                            continue
                        if f in row:
                            write[f] = row[f]
                    await db.academy_members.update_one(
                        {"_id": row["_id"]},
                        {"$set": write},
                        upsert=True,
                    )
                    total += 1
                except Exception as e:
                    logger.info(f"[academy-mirror] upsert failed for {row['_id']}: {e}")
                    errors += 1

            cursor = page_data.get("cursor")
            if not cursor:
                break

    # Reconcile intake-created auto: rows into their Monday-origin counterpart.
    # An auto: row exists when something wrote to a student by email before
    # their Monday row had synced (e.g. a new student buying a Kajabi add-on at
    # checkout → addon_* flag written via intake). Once the Monday row is here,
    # merge the dashboard-owned fields onto it and drop the auto: row, so the
    # flag lands on the permanent record and there's no duplicate.
    reconciled = 0
    if not errors:
        try:
            reconciled = await _reconcile_auto_rows(db)
        except Exception as e:
            logger.info(f"[academy-mirror] auto-row reconcile skipped: {e}")

    # Remove rows that no longer exist on Monday (member archived / deleted).
    deleted = 0
    if seen_ids and not errors:
        # Only purge if the sync ran cleanly — never wipe rows because of a
        # half-failed sync. Exclude rows that originated in the dashboard
        # (auto: ids), which won't appear in the Monday feed but are
        # legitimate.
        try:
            res = await db.academy_members.delete_many({
                "_id": {"$nin": list(seen_ids), "$not": {"$regex": "^auto:"}},
            })
            deleted = res.deleted_count
        except Exception as e:
            logger.info(f"[academy-mirror] stale purge skipped: {e}")

    elapsed = round(time.monotonic() - started, 1)
    summary = {
        "ok": errors == 0,
        "upserted": total,
        "pages": page,
        "errors": errors,
        "reconciled": reconciled,
        "stale_deleted": deleted,
        "elapsed_seconds": elapsed,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    if errors:
        logger.warning(f"[academy-mirror] sync finished with errors: {summary}")
    else:
        logger.info(f"[academy-mirror] sync ok: {summary}")
    return summary


# Identity / structural fields the Monday row stays authoritative for — never
# carried (or pinned) from an auto: row during reconciliation, even if the
# intake write happened to mark them edited.
_RECONCILE_SKIP_FIELDS = {
    "email", "circle_email", "name", "first_name", "surname", "source",
}


async def _reconcile_auto_rows(db) -> int:
    """Merge dashboard-only `auto:` rows into their Monday-origin counterpart.

    An `auto:` row is created by the intake endpoint when a student is written
    to by email before their Monday row exists (e.g. a new student buys a
    Kajabi add-on at checkout). Once the Monday row has synced, this carries
    the auto: row's dashboard-owned fields (e.g. `addon_*`) onto it — pinned in
    `dashboard_edited_fields` so the next sync won't clobber them — and deletes
    the auto: row. Returns the number of rows merged.

    Leaves an auto: row in place if no Monday counterpart exists yet (genuinely
    dashboard-only student) — it'll reconcile on a later sync."""
    merged = 0
    cursor = db.academy_members.find({"_id": {"$regex": "^auto:"}})
    async for auto_row in cursor:
        emails = [e for e in (auto_row.get("email"), auto_row.get("circle_email")) if e]
        if not emails:
            continue
        monday_row = await db.academy_members.find_one({
            "_id": {"$not": {"$regex": "^auto:"}},
            "$or": [{"email": {"$in": emails}}, {"circle_email": {"$in": emails}}],
        })
        if not monday_row:
            continue  # no Monday row yet — leave it for a later sync

        owned = set(auto_row.get("dashboard_edited_fields") or []) - _RECONCILE_SKIP_FIELDS
        carry = {f: auto_row.get(f) for f in owned if f in auto_row}
        if carry:
            new_protected = set(monday_row.get("dashboard_edited_fields") or []) | owned
            carry["dashboard_edited_fields"] = sorted(new_protected)
            carry["dashboard_edited_at"] = datetime.now(timezone.utc)
            await db.academy_members.update_one(
                {"_id": monday_row["_id"]}, {"$set": carry}
            )
        await db.academy_members.delete_one({"_id": auto_row["_id"]})
        merged += 1
        logger.info(
            f"[academy-mirror] reconciled auto row {auto_row['_id']} → "
            f"{monday_row['_id']} (carried {sorted(carry.keys() - {'dashboard_edited_fields','dashboard_edited_at'})})"
        )
    return merged


async def lookup_by_email(db, email: str) -> Optional[dict]:
    """Find one Academy Members row by email (primary or Circle email).
    Returns None on miss. Lowercases input."""
    if not email:
        return None
    e = email.strip().lower()
    row = await db.academy_members.find_one(
        {"$or": [{"email": e}, {"circle_email": e}]}
    )
    return row
