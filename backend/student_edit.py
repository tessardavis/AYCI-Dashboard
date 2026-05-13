"""Mutate student data on the Monday.com Academy Members board.

Currently supports updating the item name (i.e. the student's full name).
Used by the pencil-edit affordance on the Student Lookup header so coaches
can fix typos / add missing surnames inline without a Monday tab.

Side-effects on success:
  - Busts the unified Student Lookup cache for any email tied to the item
    so the next open of the Lookup page picks up the change.
  - Also clears the Circle members cache entry by name so name-search
    suggests the corrected name (Circle cache refresh is async, so we
    update the slim in-Mongo cache row directly).
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from connectors import MONDAY_URL, _monday_headers, TIMEOUT
from student_match import ACADEMY_MEMBERS_BOARD_ID, COL_EMAIL, _txt

logger = logging.getLogger(__name__)


async def _fetch_item(item_id: str) -> Optional[dict]:
    q = """
    query ($id: [ID!]) {
      items(ids: $id) { id name url column_values { id text } }
    }
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            MONDAY_URL,
            headers={**_monday_headers(), "Content-Type": "application/json"},
            json={"query": q, "variables": {"id": [str(item_id)]}},
        )
        r.raise_for_status()
        body = r.json()
    items = (body.get("data") or {}).get("items") or []
    return items[0] if items else None


async def update_student_name(db, item_id: str, new_name: str) -> dict:
    """Rename the Monday item. Returns the updated item shape plus the
    student email (so the frontend can refetch the cache-busted lookup)."""
    # Fetch current item so we know which email cache to bust.
    current = await _fetch_item(item_id)
    if not current:
        raise ValueError(f"Monday item {item_id} not found")

    cols = current.get("column_values") or []
    email = (_txt(cols, COL_EMAIL) or "").strip().lower() or None

    # Monday's rename mutation. The item name lives at the top level, not in
    # column_values, so we use the dedicated `change_item_name` mutation.
    mutation = """
    mutation ($boardId: ID!, $itemId: ID!, $name: String!) {
      change_simple_column_value(
        item_id: $itemId,
        board_id: $boardId,
        column_id: "name",
        value: $name
      ) { id name }
    }
    """
    variables = {
        "boardId": str(ACADEMY_MEMBERS_BOARD_ID),
        "itemId": str(item_id),
        "name": new_name,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            MONDAY_URL,
            headers={**_monday_headers(), "Content-Type": "application/json"},
            json={"query": mutation, "variables": variables},
        )
        r.raise_for_status()
        body = r.json()
    if body.get("errors"):
        logger.warning(f"[student-edit] Monday rename failed: {body['errors']}")
        raise ValueError(f"Monday rejected the rename: {body['errors']}")

    # Bust caches keyed on this email so the next lookup is fresh.
    if email:
        try:
            await db.student_lookup_cache.delete_one({"_id": email})
        except Exception:
            pass

    # Update the slim Circle members cache row IN-PLACE so name-search picks
    # up the new spelling immediately (full Circle refresh runs at 05:00 UK).
    if email:
        try:
            doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
            if doc and isinstance(doc.get("members"), list):
                members = doc["members"]
                changed = False
                for m in members:
                    if (m.get("email") or "").lower() == email:
                        m["name"] = new_name
                        changed = True
                if changed:
                    await db.circle_members_cache.update_one(
                        {"_id": "all"},
                        {"$set": {"members": members}},
                    )
        except Exception:
            pass

    return {
        "ok": True,
        "monday_item_id": str(item_id),
        "name": new_name,
        "email": email,
    }
