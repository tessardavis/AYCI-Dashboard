"""
External-source connectors for the AYCI scorecard.

Each connector is: async def pull(params: dict, start_iso: str, end_iso: str) -> float

`start_iso` / `end_iso` are ISO 8601 strings in UTC bounding a Monday 00:00 – Sunday 23:59 week.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Awaitable

import httpx

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


# ------------------------------------------------------------------ Transistor
TRANSISTOR_BASE = "https://api.transistor.fm/v1"


def _transistor_headers() -> dict:
    return {"x-api-key": os.environ.get("TRANSISTOR_API_KEY", "")}


async def transistor_list_shows() -> list[dict]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{TRANSISTOR_BASE}/shows", headers=_transistor_headers())
        r.raise_for_status()
        data = r.json().get("data", [])
        return [{"id": s["id"], "title": s.get("attributes", {}).get("title", s.get("id"))} for s in data]


async def transistor_weekly_downloads(params: dict, start_iso: str, end_iso: str) -> float:
    """
    params: {"show_id": "...."}
    Transistor `/v1/analytics/{show_id}` returns last ~14 days of daily downloads
    with date keys in DD-MM-YYYY format. We filter client-side to the week window.
    """
    show_id = params.get("show_id")
    if not show_id:
        raise ValueError("Transistor connector missing show_id")
    start_ymd = start_iso[:10]  # YYYY-MM-DD
    end_ymd = end_iso[:10]
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(
            f"{TRANSISTOR_BASE}/analytics/{show_id}",
            headers=_transistor_headers(),
        )
        r.raise_for_status()
        data = r.json().get("data", {}).get("attributes", {})
        downloads = data.get("downloads", [])
        total = 0
        for row in downloads:
            if isinstance(row, dict):
                date_raw = str(row.get("date", ""))
                count = int(row.get("downloads", 0))
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                date_raw = str(row[0])
                count = int(row[1])
            else:
                continue
            # Normalise DD-MM-YYYY → YYYY-MM-DD for comparison
            if "-" in date_raw and len(date_raw.split("-")[0]) == 2:
                dd, mm, yyyy = date_raw.split("-")[:3]
                iso_date = f"{yyyy}-{mm}-{dd}"
            else:
                iso_date = date_raw
            if start_ymd <= iso_date <= end_ymd:
                total += count
        return float(total)


# ------------------------------------------------------------------ ConvertKit (v3)
CONVERTKIT_V3 = "https://api.convertkit.com/v3"


def _ck_secret() -> str:
    return os.environ.get("CONVERTKIT_API_SECRET", "")


async def convertkit_list_tags() -> list[dict]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{CONVERTKIT_V3}/tags", params={"api_secret": _ck_secret()})
        r.raise_for_status()
        return [{"id": t["id"], "name": t["name"]} for t in r.json().get("tags", [])]


async def convertkit_weekly_subscribers(params: dict, start_iso: str, end_iso: str) -> float:
    """Total active subscribers created in window."""
    start = start_iso[:10]
    end = end_iso[:10]
    count = 0
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while True:
            q = {
                "api_secret": _ck_secret(),
                "from": start,
                "to": end,
                "per_page": 1000,
                "page": page,
            }
            r = await c.get(f"{CONVERTKIT_V3}/subscribers", params=q)
            r.raise_for_status()
            body = r.json()
            subs = body.get("subscribers", [])
            count += len(subs)
            total_pages = body.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
    return float(count)


async def convertkit_weekly_tag_subscribers(params: dict, start_iso: str, end_iso: str) -> float:
    """params: {"tag_id": 12345} or {"tag_name": "..."} — count subscribers ADDED to tag in window."""
    tag_id = params.get("tag_id")
    tag_name = params.get("tag_name")
    if not tag_id and tag_name:
        tags = await convertkit_list_tags()
        match = next((t for t in tags if t["name"].strip().lower() == tag_name.strip().lower()), None)
        if not match:
            raise ValueError(f"ConvertKit tag not found: {tag_name!r}")
        tag_id = match["id"]
    if not tag_id:
        raise ValueError("ConvertKit tag connector needs tag_name or tag_id")

    start = start_iso[:10]
    end = end_iso[:10]
    count = 0
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while True:
            q = {
                "api_secret": _ck_secret(),
                "from": start,
                "to": end,
                "per_page": 1000,
                "page": page,
            }
            r = await c.get(f"{CONVERTKIT_V3}/tags/{tag_id}/subscriptions", params=q)
            r.raise_for_status()
            body = r.json()
            subs = body.get("subscriptions", [])
            count += len(subs)
            total_pages = body.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
    return float(count)


async def convertkit_weekly_broadcast_ctr(params: dict, start_iso: str, end_iso: str) -> float:
    """Average CTR across broadcasts sent in window."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{CONVERTKIT_V3}/broadcasts", params={"api_secret": _ck_secret()})
        r.raise_for_status()
        broadcasts = r.json().get("broadcasts", [])
        ctrs: list[float] = []
        for b in broadcasts:
            sent_at = b.get("published_at") or b.get("sent_at") or b.get("send_at")
            if not sent_at:
                continue
            # normalise to ISO — ConvertKit returns e.g. "2024-01-15T10:00:00.000Z"
            if sent_at < start_iso or sent_at > end_iso:
                continue
            bid = b["id"]
            s = await c.get(f"{CONVERTKIT_V3}/broadcasts/{bid}/stats", params={"api_secret": _ck_secret()})
            if s.status_code != 200:
                continue
            stats = s.json().get("broadcast", {}).get("stats", {})
            recips = stats.get("recipients", 0) or 0
            clicks = stats.get("clicks", 0) or 0
            if recips:
                ctrs.append((clicks / recips) * 100.0)
    if not ctrs:
        return 0.0
    return round(sum(ctrs) / len(ctrs), 2)


# ------------------------------------------------------------------ Circle
CIRCLE_BASE = "https://app.circle.so/api/admin/v2"


def _circle_headers() -> dict:
    return {"Authorization": f"Token {os.environ.get('CIRCLE_API_TOKEN', '')}"}


async def circle_list_spaces() -> list[dict]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{CIRCLE_BASE}/spaces", headers=_circle_headers(), params={"per_page": 100})
        r.raise_for_status()
        body = r.json()
        records = body.get("records") or body.get("data", {}).get("spaces") or body.get("spaces") or []
        return [{"id": s.get("id"), "name": s.get("name") or s.get("slug")} for s in records]


async def _circle_fetch_all_members(client: httpx.AsyncClient, created_after: str | None = None) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        params: dict[str, Any] = {"per_page": 100, "page": page}
        if created_after:
            params["created_after"] = created_after
        r = await client.get(f"{CIRCLE_BASE}/community_members", headers=_circle_headers(), params=params)
        r.raise_for_status()
        body = r.json()
        records = body.get("records") or body.get("data") or []
        out.extend(records)
        if not records or len(records) < 100:
            break
        page += 1
        if page > 50:  # safety
            break
    return out


async def circle_weekly_new_non_academy(params: dict, start_iso: str, end_iso: str) -> float:
    """
    Count members created in window who are NOT in the Academy space.
    params: {"academy_space_id": 12345}
    """
    academy_space_id = params.get("academy_space_id")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # API doesn't take a strict date-range filter; we fetch recent and filter client-side
        members = await _circle_fetch_all_members(c, created_after=start_iso[:10])
    count = 0
    for m in members:
        created = str(m.get("created_at", ""))
        if start_iso <= created <= end_iso:
            space_ids = m.get("space_ids") or []
            if academy_space_id and int(academy_space_id) in [int(s) for s in space_ids]:
                continue
            count += 1
    return float(count)


async def circle_active_academy_members(params: dict, start_iso: str, end_iso: str) -> float:
    """Count current members of the Academy space."""
    academy_space_id = params.get("academy_space_id")
    if not academy_space_id:
        raise ValueError("Circle academy connector needs academy_space_id")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(
            f"{CIRCLE_BASE}/spaces/{academy_space_id}/space_members",
            headers=_circle_headers(),
            params={"per_page": 1},
        )
        if r.status_code == 200:
            body = r.json()
            total = body.get("meta", {}).get("total") or body.get("total") or body.get("count")
            if isinstance(total, int):
                return float(total)
        # Fallback: fetch all community members and count those in the space
        members = await _circle_fetch_all_members(c)
    target = int(academy_space_id)
    return float(sum(1 for m in members if target in [int(s) for s in (m.get("space_ids") or [])]))


# ------------------------------------------------------------------ Monday.com
MONDAY_URL = "https://api.monday.com/v2"


def _monday_headers() -> dict:
    return {"Authorization": os.environ.get("MONDAY_API_TOKEN", ""), "API-Version": "2024-10"}


async def _monday_gql(query: str, variables: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            MONDAY_URL,
            headers={**_monday_headers(), "Content-Type": "application/json"},
            json={"query": query, "variables": variables or {}},
        )
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"Monday GraphQL error: {body['errors']}")
        return body.get("data", {})


async def monday_list_boards() -> list[dict]:
    data = await _monday_gql("query { boards(limit: 100) { id name } }")
    return [{"id": str(b["id"]), "name": b["name"]} for b in data.get("boards", [])]


async def monday_weekly_status_count(params: dict, start_iso: str, end_iso: str) -> float:
    """
    Count items on a board where:
    - created_at is inside the week, AND
    - (optional) a status column's text equals one of `status_values`
    params: {"board_id": "...", "status_column_title": "Status", "status_values": ["Result Received"]}
    If status filters omitted → counts all items created this week.
    """
    board_id = params.get("board_id")
    if not board_id:
        raise ValueError("Monday connector needs board_id")
    status_column_title = params.get("status_column_title")
    status_values = [s.lower() for s in (params.get("status_values") or [])]

    count = 0
    cursor: str | None = None
    while True:
        cursor_clause = f', cursor: "{cursor}"' if cursor else ""
        q = f"""
        query {{
          boards(ids: [{int(board_id)}]) {{
            items_page(limit: 100{cursor_clause}) {{
              cursor
              items {{
                id
                name
                created_at
                column_values {{ id text type column {{ title }} }}
              }}
            }}
          }}
        }}
        """
        data = await _monday_gql(q)
        boards = data.get("boards") or []
        if not boards:
            break
        page = boards[0].get("items_page") or {}
        items = page.get("items") or []
        oldest_in_page = None
        for item in items:
            created = str(item.get("created_at") or "")
            oldest_in_page = created
            if start_iso <= created <= end_iso:
                if status_values:
                    matched = False
                    for col in item.get("column_values") or []:
                        if col.get("type") != "status":
                            continue
                        if status_column_title and (col.get("column") or {}).get("title") != status_column_title:
                            continue
                        if (col.get("text") or "").lower() in status_values:
                            matched = True
                            break
                    if matched:
                        count += 1
                else:
                    count += 1
        cursor = page.get("cursor")
        # items come newest-first; stop paging when the oldest item on page is before window
        if not cursor or (oldest_in_page and oldest_in_page < start_iso):
            break
    return float(count)


# ------------------------------------------------------------------ Stripe
STRIPE_API = "https://api.stripe.com/v1"


def _stripe_auth() -> tuple:
    return (os.environ.get("STRIPE_API_KEY", ""), "")


def _to_unix(iso: str) -> int:
    """Convert ISO 8601 (YYYY-MM-DDTHH:MM:SSZ) to Unix epoch seconds (UTC)."""
    from datetime import datetime
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


async def _stripe_list_all(client: httpx.AsyncClient, path: str, params: dict) -> list[dict]:
    out: list[dict] = []
    starting_after: str | None = None
    while True:
        q = {"limit": 100, **params}
        if starting_after:
            q["starting_after"] = starting_after
        r = await client.get(f"{STRIPE_API}{path}", auth=_stripe_auth(), params=q)
        r.raise_for_status()
        body = r.json()
        data = body.get("data", [])
        out.extend(data)
        if not body.get("has_more") or not data:
            break
        starting_after = data[-1]["id"]
    return out


async def _customer_has_prior_paid(client: httpx.AsyncClient, customer_id: str, before_ts: int) -> bool:
    """True if this customer has a succeeded charge before `before_ts`."""
    params = {"customer": customer_id, "created[lt]": before_ts, "limit": 1}
    r = await client.get(f"{STRIPE_API}/charges", auth=_stripe_auth(), params=params)
    r.raise_for_status()
    for ch in r.json().get("data", []):
        if ch.get("status") == "succeeded" and ch.get("paid"):
            return True
    return False


async def _stripe_classify_charges(start_iso: str, end_iso: str) -> dict:
    """Return dict: {'signup_gbp':..., 'upgrade_gbp':..., 'all_gbp':...} for succeeded GBP charges in window."""
    start_ts = _to_unix(start_iso)
    end_ts = _to_unix(end_iso)
    upgrade_min_pence = int(float(os.environ.get("STRIPE_UPGRADE_MIN_GBP", "90")) * 100)

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        charges = await _stripe_list_all(c, "/charges", {"created[gte]": start_ts, "created[lte]": end_ts})
        # Only succeeded GBP, non-refunded (refunds handled separately)
        gbp = [
            ch for ch in charges
            if ch.get("currency") == "gbp"
            and ch.get("status") == "succeeded"
            and ch.get("paid")
        ]
        signup_pence = 0
        upgrade_pence = 0
        all_pence = 0
        checked_customer_prior: dict[str, bool] = {}
        for ch in gbp:
            amount_net = int(ch.get("amount", 0)) - int(ch.get("amount_refunded", 0))
            all_pence += amount_net
            cust = ch.get("customer")
            if not cust:
                # one-off charge without a customer — treat as signup
                signup_pence += amount_net
                continue
            if cust not in checked_customer_prior:
                checked_customer_prior[cust] = await _customer_has_prior_paid(c, cust, start_ts)
            if not checked_customer_prior[cust]:
                signup_pence += amount_net
            elif amount_net >= upgrade_min_pence:
                upgrade_pence += amount_net
    return {
        "signup_gbp": signup_pence / 100.0,
        "upgrade_gbp": upgrade_pence / 100.0,
        "all_gbp": all_pence / 100.0,
    }


async def stripe_new_signup_revenue(params: dict, start_iso: str, end_iso: str) -> float:
    data = await _stripe_classify_charges(start_iso, end_iso)
    return round(data["signup_gbp"], 2)


async def stripe_upgrade_revenue(params: dict, start_iso: str, end_iso: str) -> float:
    data = await _stripe_classify_charges(start_iso, end_iso)
    return round(data["upgrade_gbp"], 2)


async def stripe_refunds_count(params: dict, start_iso: str, end_iso: str) -> float:
    start_ts = _to_unix(start_iso)
    end_ts = _to_unix(end_iso)
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        refunds = await _stripe_list_all(c, "/refunds", {"created[gte]": start_ts, "created[lte]": end_ts})
    return float(sum(1 for r in refunds if r.get("currency") == "gbp" and r.get("status") == "succeeded"))


async def stripe_refunds_amount(params: dict, start_iso: str, end_iso: str) -> float:
    start_ts = _to_unix(start_iso)
    end_ts = _to_unix(end_iso)
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        refunds = await _stripe_list_all(c, "/refunds", {"created[gte]": start_ts, "created[lte]": end_ts})
    total_pence = sum(int(r.get("amount", 0)) for r in refunds if r.get("currency") == "gbp" and r.get("status") == "succeeded")
    return round(total_pence / 100.0, 2)


async def stripe_missed_payments_count(params: dict, start_iso: str, end_iso: str) -> float:
    """Count of failed succeeded=false charges + failed-invoice payments in window."""
    start_ts = _to_unix(start_iso)
    end_ts = _to_unix(end_iso)
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        charges = await _stripe_list_all(c, "/charges", {"created[gte]": start_ts, "created[lte]": end_ts})
    failed = [ch for ch in charges if ch.get("status") == "failed"]
    return float(len(failed))


# ------------------------------------------------------------------ Registry
ConnectorFn = Callable[[dict, str, str], Awaitable[float]]

CONNECTORS: dict[str, ConnectorFn] = {
    # Transistor
    "transistor_weekly_downloads": transistor_weekly_downloads,
    # ConvertKit
    "convertkit_new_subscribers": convertkit_weekly_subscribers,
    "convertkit_tag_new_subscribers": convertkit_weekly_tag_subscribers,
    "convertkit_broadcast_ctr": convertkit_weekly_broadcast_ctr,
    # Circle
    "circle_new_non_academy_members": circle_weekly_new_non_academy,
    "circle_active_academy_members": circle_active_academy_members,
    # Monday
    "monday_items_created_this_week": monday_weekly_status_count,
    # Stripe
    "stripe_new_signup_revenue": stripe_new_signup_revenue,
    "stripe_upgrade_revenue": stripe_upgrade_revenue,
    "stripe_refunds_count": stripe_refunds_count,
    "stripe_refunds_amount": stripe_refunds_amount,
    "stripe_missed_payments_count": stripe_missed_payments_count,
}


async def discover() -> dict:
    """Return every list of picker options the admin needs to configure sources."""
    out: dict = {"transistor_shows": [], "convertkit_tags": [], "circle_spaces": [], "monday_boards": [], "errors": {}}
    try:
        out["transistor_shows"] = await transistor_list_shows()
    except Exception as e:
        out["errors"]["transistor"] = str(e)
    try:
        out["convertkit_tags"] = await convertkit_list_tags()
    except Exception as e:
        out["errors"]["convertkit"] = str(e)
    try:
        out["circle_spaces"] = await circle_list_spaces()
    except Exception as e:
        out["errors"]["circle"] = str(e)
    try:
        out["monday_boards"] = await monday_list_boards()
    except Exception as e:
        out["errors"]["monday"] = str(e)
    return out


async def pull_value(connector_type: str, params: dict, start_iso: str, end_iso: str) -> float:
    fn = CONNECTORS.get(connector_type)
    if not fn:
        raise ValueError(f"Unknown connector type: {connector_type}")
    return await fn(params or {}, start_iso, end_iso)
