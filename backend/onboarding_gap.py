"""
Onboarding Gap — students who paid but haven't been added to the cohort's
Circle spaces yet.

For a given launch (e.g. APR-26):
  1. Pull every NEW-signup customer (unique customer ID) within the launch's
     date window from Stripe (deduplicated, includes email + name + tier).
  2. For each email, look up the matching row in Monday's "Academy Members"
     board and read the "On Circle" column (`color_mkqxdbm8`).
  3. Flag the student if their On Circle status is anything other than the
     cohort's expected label (e.g. "On Circle, in Apr '26 spaces" or
     "In the April cohort spaces" for an April launch).

The dashboard then surfaces this list so the onboarding team can chase up
each student before Week 2 of the cohort.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx

from connectors import (
    STRIPE_API,
    TIMEOUT,
    _stripe_auth,
    MONDAY_URL,
    _monday_headers,
)

ACADEMY_MEMBERS_BOARD_ID = 1956295952
ON_CIRCLE_COLUMN_ID = "color_mkqxdbm8"

# Map a launch code (e.g. "APR-26") to the substrings that, when present in the
# Monday "On Circle" status text, indicate the student IS in this launch's
# cohort spaces. We accept both the new "<Mon> '<YY>" pattern AND the older
# "the <Month> cohort spaces" wording.
MONTH_NAMES = {
    "JAN": ("Jan", "January"),
    "FEB": ("Feb", "February"),
    "MAR": ("Mar", "March"),
    "APR": ("Apr", "April"),
    "MAY": ("May",),
    "JUN": ("Jun", "June"),
    "JUL": ("Jul", "July"),
    "AUG": ("Aug", "August"),
    "SEP": ("Sep", "September"),
    "OCT": ("Oct", "October"),
    "NOV": ("Nov", "November"),
    "DEC": ("Dec", "December"),
}


def _expected_circle_substrings(launch_code: str) -> list[str]:
    """Substrings whose presence in 'On Circle' status text means the student
    is correctly in this launch's cohort spaces."""
    parts = (launch_code or "").upper().split("-")
    if len(parts) != 2:
        return []
    mon, yy = parts
    months = MONTH_NAMES.get(mon, ())
    out: list[str] = []
    for m in months:
        # New format: "On Circle, in Apr '26 spaces"
        out.append(f"{m} '{yy} spaces")
        out.append(f"{m} {yy} spaces")
        # Older format: "In the April cohort spaces"
        out.append(f"the {m} cohort spaces")
        out.append(f"In the {m} '{yy}")
    return out


def _is_in_cohort(status_text: str | None, expected: list[str]) -> bool:
    if not status_text:
        return False
    s = status_text.lower()
    return any(e.lower() in s for e in expected)


# ---------------------------------------------------------------------------

async def _fetch_new_signup_customers(
    client: httpx.AsyncClient,
    start_iso: str,
    end_iso: str,
) -> list[dict]:
    """
    Returns one row per UNIQUE new-signup customer in window.
      [{customer_id, email, name, signup_date, tier_hint, amount_gbp}, ...]
    """
    from connectors import _customer_has_prior_paid

    start_ts = int(datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp())
    end_ts = int(datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp())

    raw_charges: list[dict] = []
    last_after: Optional[str] = None
    while True:
        params = {
            "limit": 100,
            "created[gte]": start_ts,
            "created[lte]": end_ts,
        }
        if last_after:
            params["starting_after"] = last_after
        r = await client.get(f"{STRIPE_API}/charges", auth=_stripe_auth(), params=params)
        r.raise_for_status()
        body = r.json()
        for ch in body.get("data", []):
            if ch.get("status") != "succeeded" or ch.get("refunded"):
                continue
            amount = int(ch.get("amount", 0)) - int(ch.get("amount_refunded", 0))
            if amount <= 0:
                continue
            raw_charges.append(ch)
        if not body.get("has_more"):
            break
        last_after = body["data"][-1]["id"] if body.get("data") else None
        if not last_after:
            break

    # Group by customer + check prior-paid in parallel
    unique = {ch["customer"] for ch in raw_charges if ch.get("customer")}

    async def _check(cust: str) -> tuple[str, bool]:
        try:
            return cust, await _customer_has_prior_paid(client, cust, start_ts)
        except Exception:
            return cust, False

    prior_results = dict(await asyncio.gather(*[_check(c) for c in unique]))

    # Build per-customer row using the EARLIEST charge in window
    by_cust: dict[str, dict] = {}
    for ch in sorted(raw_charges, key=lambda x: x.get("created", 0)):
        cust = ch.get("customer")
        if not cust or prior_results.get(cust, False):
            continue  # skip legacy upgrade
        if cust in by_cust:
            continue
        bd = ch.get("billing_details") or {}
        email = (bd.get("email") or ch.get("receipt_email") or "").strip().lower()
        name = bd.get("name") or ""
        amount = int(ch.get("amount", 0)) - int(ch.get("amount_refunded", 0))
        desc = (ch.get("description") or "").strip()
        # Quick tier hint from description
        d = desc.lower()
        if "boost" in d and "go" in d:
            tier_hint = "Boost & Go"
        elif "vip" in d:
            tier_hint = "VIP"
        elif "private plus" in d or "pplus" in d:
            tier_hint = "Private Plus"
        elif "academy" in d:
            tier_hint = "Academy"
        else:
            tier_hint = "—"
        by_cust[cust] = {
            "customer_id": cust,
            "email": email,
            "name": name,
            "signup_date": datetime.fromtimestamp(
                ch.get("created", 0), tz=timezone.utc
            ).date().isoformat(),
            "tier_hint": tier_hint,
            "amount_gbp": round(amount / 100.0, 2),
            "description": desc,
        }
    # Drop entries with no email — we can't cross-ref them to Monday anyway,
    # but include them in the "needs investigation" bucket.
    return list(by_cust.values())


# ---------------------------------------------------------------------------

async def _fetch_monday_circle_status_bulk(emails: list[str]) -> dict[str, dict]:
    """
    For a batch of emails, look up each on Monday's Academy Members board and
    return {email_lower: {item_id, item_name, item_url, on_circle_text,
    circle_join_followup_text, tier_text, cohort_joined_text}}.

    Uses Monday's `items_page_by_column_values` for an efficient one-call match
    by email address. Falls back to no-match silently for any email not on the
    board.
    """
    out: dict[str, dict] = {}
    if not emails:
        return out

    # Monday accepts a list of emails per query; chunk in 50s to stay polite.
    # We also try the "Circle Email" column as a fallback because some
    # students have their Circle account on a different email.
    CHUNK = 50
    EMAIL_COLUMNS = ["email_mkqxv0j0", "email_mkqxyfhm"]
    query = """
    query ($boardId: ID!, $emails: [String!]!, $colId: String!) {
      items_page_by_column_values(
        board_id: $boardId,
        limit: 200,
        columns: [{ column_id: $colId, column_values: $emails }]
      ) {
        items {
          id
          name
          url
          column_values {
            id
            text
            column { title }
          }
        }
      }
    }
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for col_id in EMAIL_COLUMNS:
            for i in range(0, len(emails), CHUNK):
                chunk = [e for e in emails[i: i + CHUNK] if e and e not in out]
                if not chunk:
                    continue
                r = await c.post(
                    MONDAY_URL,
                    headers={**_monday_headers(), "Content-Type": "application/json"},
                    json={
                        "query": query,
                        "variables": {
                            "boardId": str(ACADEMY_MEMBERS_BOARD_ID),
                            "emails": chunk,
                            "colId": col_id,
                        },
                    },
                )
                try:
                    r.raise_for_status()
                except Exception:
                    continue
                body = r.json()
                items = (body.get("data") or {}).get("items_page_by_column_values") or {}
                for it in items.get("items") or []:
                    cols = {cv.get("id"): cv for cv in it.get("column_values") or []}
                    # Determine which input email matched this row
                    primary_email = (cols.get("email_mkqxv0j0") or {}).get("text") or ""
                    circle_email = (cols.get("email_mkqxyfhm") or {}).get("text") or ""
                    matched_email = None
                    for e in chunk:
                        if e == primary_email.strip().lower() or e == circle_email.strip().lower():
                            matched_email = e
                            break
                    if not matched_email:
                        continue
                    out[matched_email] = {
                        "item_id": it.get("id"),
                        "item_name": it.get("name"),
                        "item_url": it.get("url"),
                        "on_circle_text": (cols.get(ON_CIRCLE_COLUMN_ID) or {}).get("text") or "",
                        "circle_join_followup_text": (cols.get("color_mkxsnshw") or {}).get("text") or "",
                        "tier_text": (cols.get("color_mkqxhw88") or {}).get("text") or "",
                        "cohort_joined_text": (cols.get("dropdown_mkqxhw8p") or {}).get("text") or "",
                    }
    return out


# ---------------------------------------------------------------------------

async def fetch_onboarding_gap(launch: dict) -> dict:
    """
    Top-level entry. Given a launch dict (must have `code`, `start_date`,
    `end_date`), return:
      {
        launch_code, window: {start, end},
        expected_circle_label,
        new_signups_total,
        gap_count,
        gap: [
          { email, name, signup_date, tier_hint, amount_gbp,
            on_circle_status, circle_join_followup, monday_url, reason }
        ],
        in_cohort_count,
        unmatched: [ ... emails without a Monday row ],
        last_refreshed
      }
    """
    code = launch.get("code") or ""
    start = launch.get("start_date")
    end = launch.get("end_date")
    if not (code and start and end):
        return {"error": "Launch missing code/start_date/end_date"}

    expected = _expected_circle_substrings(code)
    today = datetime.now(timezone.utc).date()

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        signups = await _fetch_new_signup_customers(
            c, start + "T00:00:00Z", end + "T23:59:59Z",
        )

    emails = [s["email"] for s in signups if s.get("email")]
    monday_map = await _fetch_monday_circle_status_bulk(emails)

    gap: list[dict] = []
    unmatched: list[dict] = []
    in_cohort = 0
    for s in signups:
        em = (s.get("email") or "").strip().lower()
        m = monday_map.get(em)
        if not m:
            unmatched.append({**s, "reason": "Not yet on Monday Academy Members board"})
            continue
        status = m["on_circle_text"]
        if _is_in_cohort(status, expected):
            in_cohort += 1
            continue
        if not status:
            reason = "Monday 'On Circle' field empty"
        elif "not on circle" in status.lower():
            reason = "Hasn't joined Circle yet"
        elif "not in spaces" in status.lower() or "/not in spaces" in status.lower():
            reason = "On Circle but not added to cohort spaces"
        else:
            reason = f"In a different cohort: {status}"
        gap.append({
            **s,
            "on_circle_status": status,
            "circle_join_followup": m.get("circle_join_followup_text") or "",
            "monday_url": m.get("item_url"),
            "monday_name": m.get("item_name"),
            "reason": reason,
        })

    # Sort: oldest signup date first (most overdue at the top)
    gap.sort(key=lambda x: x.get("signup_date") or "")

    return {
        "launch_code": code,
        "window": {"start": start, "end": end, "today": today.isoformat()},
        "expected_circle_label": expected[0] if expected else None,
        "new_signups_total": len(signups),
        "in_cohort_count": in_cohort,
        "gap_count": len(gap),
        "unmatched_count": len(unmatched),
        "gap": gap,
        "unmatched": unmatched,
        "last_refreshed": datetime.now(timezone.utc).isoformat(),
    }
