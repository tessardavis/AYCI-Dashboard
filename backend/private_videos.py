"""
Private-Tier Video Submissions - read + write to Monday board 5083952249.

The Tally form + Monday automations (board webhook, "Send reply via Circle"
button) remain the source of truth. This module only:
  - GETs the rows so the dashboard can render them in a sortable table
  - PATCHes the columns Becky/Tessa actively edit (Status, Assigned-to,
    Replied date, Link to reply)

Result: the team uses our dashboard daily and never opens Monday. There are
no duplicated automations because we add zero new automations on top.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from connectors import _monday_gql, MONDAY_URL, _monday_headers

logger = logging.getLogger(__name__)

BOARD_ID = 5083952249

# Column id → friendly name for the API response
COL = {
    "person":             "person",        # people column (Assigned to)
    "status":             "status",        # status column
    "first_name":         "text_mkxf1fjb",
    "last_name":          "text_mkxff2wh",
    "email":              "email_mkxfpqnv",
    "submitted":          "date4",
    "question":           "text_mkxnzbmt",
    "tally_video":        "link_mkzhtnn5",
    "video":              "link_mkxfd9d",
    "reply_link":         "link_mkxfg1df",
    "total_allowance":    "numeric_mkxfy21v",
    "submission_number":  "numeric_mkxft4es",
    "replied":            "date_mkxf8p00",
    "private_chat":       "text_mky9myt2",
    "interview_date":     "date_mm1ac68r",
}

# 5-min Mongo cache so re-renders feel fast.
CACHE_KEY = "private_videos:list"
CACHE_TTL_SECONDS = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_link_value(text: str | None) -> dict:
    """Monday's `link` columns return text like 'Video URL - https://...'.
    The actual URL is the second token after ' - '. Return {label, url}."""
    if not text:
        return {"label": None, "url": None}
    # Some links come as 'https://...', others as 'Label - https://...'
    if " - " in text:
        label, url = text.split(" - ", 1)
        return {"label": label.strip() or None, "url": url.strip() or None}
    return {"label": None, "url": text.strip() or None}


def _decode_item(item: dict) -> dict:
    cv_by_id = {cv["id"]: cv for cv in (item.get("column_values") or [])}

    def text_of(col_id: str) -> str | None:
        cv = cv_by_id.get(col_id)
        return (cv or {}).get("text") or None

    def value_of(col_id: str) -> dict | None:
        cv = cv_by_id.get(col_id)
        raw = (cv or {}).get("value")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    person_val = value_of(COL["person"]) or {}
    persons = person_val.get("personsAndTeams") or []
    person_id = persons[0].get("id") if persons else None

    status_val = value_of(COL["status"]) or {}
    status_index = status_val.get("index")

    out = {
        "id": str(item["id"]),
        "name": item.get("name"),
        "created_at": item.get("created_at"),
        "first_name": text_of(COL["first_name"]),
        "last_name": text_of(COL["last_name"]),
        "email": text_of(COL["email"]),
        "submitted": text_of(COL["submitted"]),
        "question": text_of(COL["question"]),
        "tally_video": _parse_link_value(text_of(COL["tally_video"])),
        "video": _parse_link_value(text_of(COL["video"])),
        "reply_link": _parse_link_value(text_of(COL["reply_link"])),
        "total_allowance": text_of(COL["total_allowance"]),
        "submission_number": text_of(COL["submission_number"]),
        "replied": text_of(COL["replied"]),
        "private_chat": text_of(COL["private_chat"]),
        "interview_date": text_of(COL["interview_date"]),
        "status": text_of(COL["status"]),
        "status_index": status_index,
        "assignee_id": str(person_id) if person_id else None,
        "assignee_name": text_of(COL["person"]),
    }
    return out


# ---------------------------------------------------------------- Read
async def list_submissions(db, force: bool = False) -> dict:
    if not force:
        cached = await db.fn_cache.find_one({"_id": CACHE_KEY})
        if cached:
            try:
                age = (datetime.now(timezone.utc) - cached["cached_at"]).total_seconds()
                if age < CACHE_TTL_SECONDS:
                    return cached["payload"]
            except Exception:
                pass

    query = """
    query ($board_id: [ID!]) {
      boards(ids: $board_id) {
        items_page(limit: 500) {
          cursor
          items {
            id name created_at
            column_values {
              id type text value
              ... on StatusValue { label }
              ... on PeopleValue { persons_and_teams { id kind } }
            }
          }
        }
      }
    }
    """
    items: list[dict] = []
    cursor: Optional[str] = None
    while True:
        if cursor:
            page_q = """
            query ($cursor: String!) {
              next_items_page(cursor: $cursor, limit: 500) {
                cursor
                items {
                  id name created_at
                  column_values { id type text value }
                }
              }
            }
            """
            data = await _monday_gql(page_q, {"cursor": cursor})
            page = data.get("next_items_page") or {}
        else:
            data = await _monday_gql(query, {"board_id": [BOARD_ID]})
            board = (data.get("boards") or [{}])[0]
            page = board.get("items_page") or {}
        for it in page.get("items") or []:
            items.append(_decode_item(it))
        cursor = page.get("cursor")
        if not cursor:
            break

    # Sort: New / Working on it first, then by submitted desc
    def _sort_key(x):
        s = (x.get("status") or "").lower()
        weight = 0 if s in ("new",) else (1 if s == "working on it" else 2)
        return (weight, -(int((x.get("submitted") or "1900-01-01")[:10].replace("-", "")) if x.get("submitted") else 0))

    items.sort(key=_sort_key)

    payload = {"items": items, "fetched_at": _now_iso()}
    await db.fn_cache.update_one(
        {"_id": CACHE_KEY},
        {"$set": {"_id": CACHE_KEY, "cached_at": datetime.now(timezone.utc), "payload": payload}},
        upsert=True,
    )
    return payload


# ---------------------------------------------------------------- Write
async def get_team_users() -> list[dict]:
    """Return Monday users so the assignee dropdown can show real names."""
    data = await _monday_gql("query { users(kind: non_guests, limit: 50) { id name email } }")
    return [{"id": str(u["id"]), "name": u["name"], "email": u.get("email")} for u in data.get("users", [])]


async def update_submission(db, item_id: str, patch: dict) -> dict:
    """PATCH allowed columns. Accepts:
       - status_label (string label like 'Done')
       - assignee_id (Monday user id, or '' to clear)
       - replied (YYYY-MM-DD or null)
       - reply_link (URL string)"""
    column_values: dict = {}
    if "status_label" in patch:
        # Monday expects {"label": "Done"} - ignored if label not in board's options
        column_values[COL["status"]] = {"label": patch["status_label"] or ""}
    if "assignee_id" in patch:
        if patch["assignee_id"]:
            column_values[COL["person"]] = {
                "personsAndTeams": [{"id": int(patch["assignee_id"]), "kind": "person"}]
            }
        else:
            column_values[COL["person"]] = {"personsAndTeams": []}
    if "replied" in patch:
        if patch["replied"]:
            column_values[COL["replied"]] = {"date": patch["replied"]}
        else:
            column_values[COL["replied"]] = {}
    if "reply_link" in patch:
        url = (patch["reply_link"] or "").strip()
        if url:
            column_values[COL["reply_link"]] = {"url": url, "text": url}
        else:
            column_values[COL["reply_link"]] = {"url": "", "text": ""}

    if not column_values:
        return {"ok": False, "reason": "no editable fields supplied"}

    mutation = """
    mutation ($board_id: ID!, $item_id: ID!, $values: JSON!) {
      change_multiple_column_values(board_id: $board_id, item_id: $item_id, column_values: $values) {
        id
      }
    }
    """
    await _monday_gql(mutation, {
        "board_id": str(BOARD_ID),
        "item_id": str(item_id),
        "values": json.dumps(column_values),
    })
    # Invalidate cache so next list reflects the change immediately
    await db.fn_cache.delete_one({"_id": CACHE_KEY})
    return {"ok": True, "item_id": str(item_id)}
