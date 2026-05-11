"""
External-source connectors for the AYCI scorecard.

Each connector is: async def pull(params: dict, start_iso: str, end_iso: str) -> float

`start_iso` / `end_iso` are ISO 8601 strings in UTC bounding a Monday 00:00 – Sunday 23:59 week.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
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
    """
    params: {"tag_id": 12345}  or  {"tag_name": "..."}
         or {"tag_ids": [12345, 67890]}     # union of multiple tags
    Count of UNIQUE subscribers NEWLY tagged on any of the given tags in the
    window. Paginates newest-first and stops once we've passed start_iso (v3
    `from`/`to` params on this endpoint are unreliable, so we filter
    client-side on each subscription's created_at).

    Behaviour:
      • If a subscriber appears on multiple tags during the window, we keep
        their *earliest* timestamp (matching the AYCI Waitlist CRM spreadsheet).
      • Mass re-tag bursts (>= BURST_THRESHOLD subscriptions sharing the same
        minute timestamp on a single tag) are stripped — those are
        launch-automation imports or sheet/CSV bulk-tags rather than organic
        waitlist joins.
    """
    BURST_THRESHOLD = 10  # 10+ subs in the same minute = automation, not organic

    # Resolve tag list (singular `tag_id`, plural `tag_ids`, or `tag_name`)
    tag_ids: list[int] = []
    if params.get("tag_ids"):
        tag_ids = [int(t) for t in params["tag_ids"] if t]
    elif params.get("tag_id"):
        tag_ids = [int(params["tag_id"])]
    elif params.get("tag_name"):
        tags = await convertkit_list_tags()
        match = next(
            (t for t in tags if t["name"].strip().lower() == params["tag_name"].strip().lower()),
            None,
        )
        if not match:
            raise ValueError(f"ConvertKit tag not found: {params['tag_name']!r}")
        tag_ids = [int(match["id"])]
    if not tag_ids:
        raise ValueError("ConvertKit tag connector needs tag_id, tag_ids, or tag_name")

    from collections import Counter

    # Fetch all in-window rows per tag, applying burst filter per tag (a burst
    # on one tag shouldn't suppress organic joins on another).
    earliest_per_email: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for tag_id in tag_ids:
            in_window: list[tuple[str, str]] = []
            page = 1
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
                oldest = None
                for s in subs:
                    created = str(s.get("created_at") or "")
                    oldest = created
                    if start_iso <= created <= end_iso:
                        em = ((s.get("subscriber") or {}).get("email_address") or "").strip().lower()
                        if em:
                            in_window.append((created, em))
                if oldest and oldest < start_iso:
                    break
                total_pages = body.get("total_pages", 1)
                if page >= total_pages:
                    break
                page += 1

            # Per-tag burst filter
            minute_counts = Counter(ts[:16] for ts, _ in in_window)
            organic = [(ts, em) for ts, em in in_window if minute_counts[ts[:16]] < BURST_THRESHOLD]

            # Merge into the cross-tag map, keeping earliest timestamp
            for ts, em in organic:
                if em not in earliest_per_email or ts < earliest_per_email[em]:
                    earliest_per_email[em] = ts

    return float(len(earliest_per_email))


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


async def _circle_fetch_all_members(client: httpx.AsyncClient, sort: str = "created_at", order: str = "desc", max_pages: int = 100) -> list[dict]:
    out: list[dict] = []
    page = 1
    while page <= max_pages:
        params: dict[str, Any] = {"per_page": 100, "page": page, "sort": sort, "order": order}
        r = await client.get(f"{CIRCLE_BASE}/community_members", headers=_circle_headers(), params=params)
        r.raise_for_status()
        body = r.json()
        records = body.get("records") or body.get("data") or []
        out.extend(records)
        if not records or len(records) < 100:
            break
        page += 1
    return out


def _has_tag(member: dict, tag_name: str) -> bool:
    target = tag_name.strip().lower()
    for t in member.get("member_tags") or []:
        if str(t.get("name", "")).strip().lower() == target:
            return True
    return False


async def circle_weekly_new_non_academy(params: dict, start_iso: str, end_iso: str) -> float:
    """
    New community members created in window who HAVE the `non_academy_tag` tag
    (defaults to "Circle Member"). Paginates newest-first and stops once we
    pass the window.
    """
    tag_name = (params or {}).get("non_academy_tag", "Circle Member")
    count = 0
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while page <= 100:
            q = {"per_page": 100, "page": page, "sort": "created_at", "order": "desc"}
            r = await c.get(f"{CIRCLE_BASE}/community_members", headers=_circle_headers(), params=q)
            r.raise_for_status()
            body = r.json()
            recs = body.get("records") or body.get("data") or []
            if not recs:
                break
            oldest = None
            for m in recs:
                created = str(m.get("created_at") or "")
                oldest = created
                if start_iso <= created <= end_iso and _has_tag(m, tag_name):
                    count += 1
            if oldest and oldest < start_iso:
                break
            if len(recs) < 100:
                break
            page += 1
    return float(count)


async def circle_active_academy_members(params: dict, start_iso: str, end_iso: str) -> float:
    """
    Count members WITHOUT the `non_academy_tag` tag (defaults to "Circle Member")
    whose last_seen_at is within the 7 days leading up to end_iso.
    """
    from datetime import datetime, timedelta as _td
    tag_name = (params or {}).get("non_academy_tag", "Circle Member")
    end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    active_from = (end_dt - _td(days=7)).isoformat().replace("+00:00", "Z")
    active_to = end_iso

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        members = await _circle_fetch_all_members(c, sort="last_seen_at", order="desc", max_pages=60)
    count = 0
    for m in members:
        last_seen = str(m.get("last_seen_at") or "")
        if not last_seen:
            continue
        if last_seen > active_to or last_seen < active_from:
            continue
        if not _has_tag(m, tag_name):
            count += 1
    return float(count)


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


# ------------------------------------------------------------------ YouTube Data API v3
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"


def _yt_key() -> str:
    return os.environ.get("YOUTUBE_API_KEY", "")


async def youtube_resolve_channel(handle_or_url: str) -> dict:
    """Handle like '@DrTessaRDavis' or full URL → channel id + uploads playlist id."""
    handle = handle_or_url
    if "youtube.com" in handle_or_url:
        # extract the @handle or channel ID from URL
        if "/channel/" in handle_or_url:
            cid = handle_or_url.split("/channel/")[1].split("/")[0].split("?")[0]
            return {"channel_id": cid, "_source": "url-channel"}
        if "/@" in handle_or_url:
            handle = "@" + handle_or_url.split("/@")[1].split("/")[0].split("?")[0]
    if not handle.startswith("@"):
        handle = "@" + handle

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(
            f"{YOUTUBE_API}/channels",
            params={"part": "id,contentDetails,snippet,statistics", "forHandle": handle, "key": _yt_key()},
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            raise ValueError(f"YouTube channel not found for handle {handle}")
        ch = items[0]
        return {
            "channel_id": ch["id"],
            "title": ch["snippet"]["title"],
            "uploads_playlist_id": ch["contentDetails"]["relatedPlaylists"]["uploads"],
            "total_views": int(ch["statistics"].get("viewCount", 0)),
            "total_videos": int(ch["statistics"].get("videoCount", 0)),
        }


async def youtube_weekly_views_on_new_videos(params: dict, start_iso: str, end_iso: str) -> float:
    """
    params: {"channel_id": "UC..."}  OR  {"uploads_playlist_id": "UU..."}
    Returns the sum of current viewCount on videos uploaded within the window.
    Rationale: YouTube Data API (API-key-only) does not expose time-sliced analytics;
    Analytics API requires OAuth. For a weekly podcast, most views come in the first
    48-72h after upload, so this is a close proxy for "views this week" tied to new
    content. When channel has older evergreen videos, this is a conservative number.
    """
    uploads_playlist_id = params.get("uploads_playlist_id")
    channel_id = params.get("channel_id")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        if not uploads_playlist_id:
            if not channel_id:
                raise ValueError("YouTube connector needs channel_id or uploads_playlist_id")
            r = await c.get(
                f"{YOUTUBE_API}/channels",
                params={"part": "contentDetails", "id": channel_id, "key": _yt_key()},
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            if not items:
                raise ValueError(f"YouTube channel not found: {channel_id}")
            uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # Walk newest-first through uploads playlist until we pass the window
        video_ids_in_window: list[str] = []
        page_token: str | None = None
        while True:
            q = {
                "part": "contentDetails,snippet",
                "playlistId": uploads_playlist_id,
                "maxResults": 50,
                "key": _yt_key(),
            }
            if page_token:
                q["pageToken"] = page_token
            r = await c.get(f"{YOUTUBE_API}/playlistItems", params=q)
            r.raise_for_status()
            body = r.json()
            oldest_on_page = None
            for it in body.get("items", []):
                pub = str(it.get("contentDetails", {}).get("videoPublishedAt", ""))
                if not pub:
                    pub = str(it.get("snippet", {}).get("publishedAt", ""))
                if not pub:
                    continue
                oldest_on_page = pub
                if start_iso <= pub <= end_iso:
                    vid = it["contentDetails"]["videoId"]
                    video_ids_in_window.append(vid)
            page_token = body.get("nextPageToken")
            # stop when we've paged past the window
            if not page_token or (oldest_on_page and oldest_on_page < start_iso):
                break

        if not video_ids_in_window:
            return 0.0

        total_views = 0
        # videos.list accepts up to 50 ids per call
        for i in range(0, len(video_ids_in_window), 50):
            chunk = video_ids_in_window[i : i + 50]
            r = await c.get(
                f"{YOUTUBE_API}/videos",
                params={"part": "statistics", "id": ",".join(chunk), "key": _yt_key()},
            )
            r.raise_for_status()
            for v in r.json().get("items", []):
                total_views += int(v.get("statistics", {}).get("viewCount", 0))
    return float(total_views)


# ------------------------------------------------------------------ Tally
TALLY_BASE = "https://api.tally.so"


def _tally_headers() -> dict:
    return {"Authorization": f"Bearer {os.environ.get('TALLY_API_KEY', '')}"}


async def tally_list_forms() -> list[dict]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{TALLY_BASE}/forms", headers=_tally_headers())
        r.raise_for_status()
        body = r.json()
        items = body.get("items") or body.get("forms") or body.get("data") or []
        return [{"id": f.get("id"), "name": f.get("name") or f.get("title", "?")} for f in items]


async def tally_form_submissions_this_week(params: dict, start_iso: str, end_iso: str) -> float:
    """
    params: {
      "form_id": "nGyGj2",
      "answer_contains": "substantive job"   # optional: filter submissions by text present in any answer
    }
    Counts submissions to a Tally form with submittedAt in window.
    If `answer_contains` is set, only counts submissions where any answer (stringified)
    contains the given substring (case-insensitive).
    """
    form_id = params.get("form_id")
    if not form_id:
        raise ValueError("Tally connector needs form_id")
    needle = (params.get("answer_contains") or "").strip().lower()
    count = 0
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while page <= 100:
            r = await c.get(
                f"{TALLY_BASE}/forms/{form_id}/submissions",
                headers=_tally_headers(),
                params={"page": page, "limit": 100},
            )
            r.raise_for_status()
            body = r.json()
            items = body.get("submissions") or body.get("items") or body.get("data") or []
            if not items:
                break
            oldest = None
            for s in items:
                ts = str(s.get("submittedAt") or s.get("createdAt") or "")
                oldest = ts
                if not (start_iso <= ts <= end_iso):
                    continue
                if needle:
                    all_text = " ".join(str(r.get("answer", "")) for r in s.get("responses", [])).lower()
                    if needle not in all_text:
                        continue
                count += 1
            if oldest and oldest < start_iso:
                break
            if len(items) < 100:
                break
            page += 1
    return float(count)


async def tally_interviews_by_answer_date(params: dict, start_iso: str, end_iso: str) -> float:
    """
    Count Tally submissions whose ANSWER to a specific date question falls in
    the target week — regardless of when the submission was actually made.

    params: {
      "form_id": "nGyGj2",
      "date_question_title": "Interview Date",   # or "date_question_id": "keP4W6"
      "answer_contains": "yes."                  # optional substring filter on any answer
    }
    """
    form_id = params.get("form_id")
    if not form_id:
        raise ValueError("Tally interview-date connector needs form_id")
    date_qid = params.get("date_question_id")
    date_qtitle = (params.get("date_question_title") or "").strip().lower()
    needle = (params.get("answer_contains") or "").strip().lower()

    # window in YYYY-MM-DD (date questions store 10-char ISO dates)
    start_date = start_iso[:10]
    end_date = end_iso[:10]

    count = 0
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while page <= 50:  # cap at 5000 submissions (~1 year of form)
            r = await c.get(
                f"{TALLY_BASE}/forms/{form_id}/submissions",
                headers=_tally_headers(),
                params={"page": page, "limit": 100},
            )
            r.raise_for_status()
            body = r.json()
            items = body.get("submissions") or body.get("items") or body.get("data") or []
            if not items:
                break

            # Resolve date question id from the first page's question schema (if needed)
            if not date_qid and date_qtitle and page == 1:
                for q in body.get("questions", []) or []:
                    title = (q.get("title") or "").strip().lower()
                    if title == date_qtitle and q.get("type") == "INPUT_DATE":
                        date_qid = q.get("id")
                        break
                if not date_qid:
                    raise ValueError(
                        f"Tally question {date_qtitle!r} (INPUT_DATE) not found on form {form_id}"
                    )

            for s in items:
                interview_date: str | None = None
                all_text_parts: list[str] = []
                for resp in s.get("responses") or []:
                    ans = resp.get("answer")
                    if resp.get("questionId") == date_qid and isinstance(ans, str):
                        interview_date = ans[:10]  # YYYY-MM-DD
                    all_text_parts.append(str(ans))
                if not interview_date:
                    continue
                if not (start_date <= interview_date <= end_date):
                    continue
                if needle:
                    joined = " ".join(all_text_parts).lower()
                    if needle not in joined:
                        continue
                count += 1

            if len(items) < 100:
                break
            page += 1
    return float(count)


async def tally_avg_rating_this_week(params: dict, start_iso: str, end_iso: str) -> float:
    """
    params: {"form_id": "68koZk"}
    Averages all LINEAR_SCALE / RATING / numeric answers across submissions in window.
    Returns 0.0 if no submissions.
    """
    form_id = params.get("form_id")
    if not form_id:
        raise ValueError("Tally rating connector needs form_id")
    scores: list[float] = []
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while page <= 100:
            r = await c.get(
                f"{TALLY_BASE}/forms/{form_id}/submissions",
                headers=_tally_headers(),
                params={"page": page, "limit": 100},
            )
            r.raise_for_status()
            body = r.json()
            items = body.get("submissions") or body.get("items") or body.get("data") or []
            if not items:
                break
            oldest = None
            for s in items:
                ts = str(s.get("submittedAt") or s.get("createdAt") or "")
                oldest = ts
                if not (start_iso <= ts <= end_iso):
                    continue
                for r_ in s.get("responses", []):
                    ans = r_.get("answer")
                    if isinstance(ans, (int, float)):
                        scores.append(float(ans))
                    elif isinstance(ans, str):
                        try:
                            scores.append(float(ans))
                        except ValueError:
                            continue
            if oldest and oldest < start_iso:
                break
            if len(items) < 100:
                break
            page += 1
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 2)


async def _ck_tag_emails(tag_id: int) -> set[str]:
    """Return the set of email addresses currently subscribed to a ConvertKit tag."""
    emails: set[str] = set()
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while page <= 100:
            r = await c.get(
                f"{CONVERTKIT_V3}/tags/{tag_id}/subscriptions",
                params={"api_secret": _ck_secret(), "page": page, "per_page": 1000},
            )
            r.raise_for_status()
            body = r.json()
            for s in body.get("subscriptions", []):
                em = (s.get("subscriber") or {}).get("email_address") or s.get("email_address")
                if em:
                    emails.add(em.strip().lower())
            total_pages = body.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
    return emails


async def stripe_new_signups_from_waitlist(params: dict, start_iso: str, end_iso: str) -> float:
    """
    params: {"waitlist_tag_id": 14407524}
         or {"waitlist_tag_ids": [14407524, 19213962]}   # union of multiple tags
    Count of Stripe first-charge customers in window whose email is on ANY of
    the given ConvertKit waitlist tags. The union form lets us keep counting
    late converters from previous launch waitlists alongside the current one.
    """
    tag_ids: list[int] = []
    if params.get("waitlist_tag_ids"):
        tag_ids = [int(t) for t in params["waitlist_tag_ids"] if t]
    elif params.get("waitlist_tag_id"):
        tag_ids = [int(params["waitlist_tag_id"])]
    if not tag_ids:
        raise ValueError("waitlist signups connector needs waitlist_tag_id or waitlist_tag_ids")

    waitlist_emails: set[str] = set()
    for tid in tag_ids:
        waitlist_emails |= await _ck_tag_emails(tid)
    if not waitlist_emails:
        return 0.0

    start_ts = _to_unix(start_iso)
    end_ts = _to_unix(end_iso)
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        charges = await _stripe_list_all(
            c, "/charges", {"created[gte]": start_ts, "created[lte]": end_ts}
        )
        paid_charges = [
            ch for ch in charges
            if ch.get("currency") == "gbp" and ch.get("status") == "succeeded" and ch.get("paid")
        ]
        # Unique first-charge customers in window whose email is on waitlist
        counted_emails: set[str] = set()
        for ch in paid_charges:
            cust_id = ch.get("customer")
            receipt_email = (ch.get("billing_details") or {}).get("email") or ch.get("receipt_email")
            if not cust_id and not receipt_email:
                continue
            # Determine first-charge
            if cust_id:
                prior = await _customer_has_prior_paid(c, cust_id, start_ts)
                if prior:
                    continue
                # Fetch customer email
                cust_r = await c.get(f"{STRIPE_API}/customers/{cust_id}", auth=_stripe_auth())
                email = (cust_r.json() or {}).get("email")
            else:
                email = receipt_email
            if not email:
                continue
            em_lc = email.strip().lower()
            if em_lc in waitlist_emails and em_lc not in counted_emails:
                counted_emails.add(em_lc)
    return float(len(counted_emails))


# ------------------------------------------------------------------ Calendly
CALENDLY_BASE = "https://api.calendly.com"


def _calendly_headers() -> dict:
    return {"Authorization": f"Bearer {os.environ.get('CALENDLY_TOKEN', '')}"}


async def calendly_list_event_types() -> list[dict]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
        me.raise_for_status()
        user_uri = me.json().get("resource", {}).get("uri")
        r = await c.get(
            f"{CALENDLY_BASE}/event_types",
            headers=_calendly_headers(),
            params={"user": user_uri, "count": 100, "active": "true"},
        )
        r.raise_for_status()
        out = []
        for t in r.json().get("collection", []):
            uri = t.get("uri", "")
            out.append({"id": uri.rsplit("/", 1)[-1], "uri": uri, "name": t.get("name", "")})
        return out


async def calendly_events_this_week(params: dict, start_iso: str, end_iso: str) -> float:
    """
    params: {"event_type_uuid": "2b1cb9db-..."}  OR  {"event_type_uri": "https://.../event_types/..."}
    Counts Calendly scheduled events of a given type that started within the window.
    """
    event_type_uri = params.get("event_type_uri")
    if not event_type_uri:
        uuid = params.get("event_type_uuid")
        if not uuid:
            raise ValueError("Calendly connector needs event_type_uuid or event_type_uri")
        event_type_uri = f"{CALENDLY_BASE}/event_types/{uuid}"

    count = 0
    page_token: str | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
        me.raise_for_status()
        user_uri = me.json().get("resource", {}).get("uri")
        while True:
            q: dict[str, Any] = {
                "user": user_uri,
                "event_type": event_type_uri,
                "min_start_time": start_iso,
                "max_start_time": end_iso,
                "status": "active",
                "count": 100,
            }
            if page_token:
                q["page_token"] = page_token
            r = await c.get(f"{CALENDLY_BASE}/scheduled_events", headers=_calendly_headers(), params=q)
            r.raise_for_status()
            body = r.json()
            count += len(body.get("collection", []))
            page_token = (body.get("pagination") or {}).get("next_page_token")
            if not page_token:
                break
    return float(count)


async def calendly_events_hours_this_week(params: dict, start_iso: str, end_iso: str) -> float:
    """
    params: {"event_type_uuids": ["uuid1","uuid2"]}  OR  {"event_type_uris": [...]}
    Returns total HOURS of scheduled Calendly events across given types in window.
    """
    uris: list[str] = params.get("event_type_uris") or []
    if not uris:
        uuids = params.get("event_type_uuids") or []
        uris = [f"{CALENDLY_BASE}/event_types/{u}" for u in uuids]
    if not uris:
        raise ValueError("Calendly hours connector needs event_type_uris or event_type_uuids")

    total_seconds = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
        me.raise_for_status()
        user_uri = me.json().get("resource", {}).get("uri")
        for uri in uris:
            page_token: str | None = None
            while True:
                q: dict[str, Any] = {
                    "user": user_uri,
                    "event_type": uri,
                    "min_start_time": start_iso,
                    "max_start_time": end_iso,
                    "status": "active",
                    "count": 100,
                }
                if page_token:
                    q["page_token"] = page_token
                r = await c.get(f"{CALENDLY_BASE}/scheduled_events", headers=_calendly_headers(), params=q)
                r.raise_for_status()
                body = r.json()
                for ev in body.get("collection", []):
                    try:
                        s = datetime.fromisoformat(str(ev.get("start_time", "")).replace("Z", "+00:00"))
                        e = datetime.fromisoformat(str(ev.get("end_time", "")).replace("Z", "+00:00"))
                        total_seconds += int((e - s).total_seconds())
                    except Exception:
                        continue
                page_token = (body.get("pagination") or {}).get("next_page_token")
                if not page_token:
                    break
    return round(total_seconds / 3600.0, 2)


# ------------------------------------------------------------------ Circle — posts in a space
async def circle_list_spaces_with_posts() -> list[dict]:
    # Re-use list_spaces
    return await circle_list_spaces()


async def circle_space_posts_this_week(params: dict, start_iso: str, end_iso: str) -> float:
    """
    params: {"space_id": 996901}
    Counts posts in a specific Circle space with created_at inside the window.
    """
    space_id = params.get("space_id")
    if not space_id:
        raise ValueError("Circle posts connector needs space_id")
    count = 0
    page = 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while page <= 100:
            r = await c.get(
                f"{CIRCLE_BASE}/posts",
                headers=_circle_headers(),
                params={"space_id": int(space_id), "per_page": 100, "page": page, "sort": "created_at", "order": "desc"},
            )
            r.raise_for_status()
            body = r.json()
            recs = body.get("records") or body.get("data") or []
            if not recs:
                break
            oldest = None
            for p in recs:
                created = str(p.get("created_at") or "")
                oldest = created
                if start_iso <= created <= end_iso:
                    count += 1
            if oldest and oldest < start_iso:
                break
            if len(recs) < 100:
                break
            page += 1
    return float(count)


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
    # YouTube
    "youtube_weekly_views_on_new_videos": youtube_weekly_views_on_new_videos,
    # Tally
    "tally_form_submissions_this_week": tally_form_submissions_this_week,
    "tally_interviews_by_answer_date": tally_interviews_by_answer_date,
    "tally_avg_rating_this_week": tally_avg_rating_this_week,
    # Stripe + ConvertKit combo
    "stripe_new_signups_from_waitlist": stripe_new_signups_from_waitlist,
    # Calendly
    "calendly_events_this_week": calendly_events_this_week,
    "calendly_hours_this_week": calendly_events_hours_this_week,
    # Circle posts
    "circle_space_posts_this_week": circle_space_posts_this_week,
}


async def discover() -> dict:
    """Return every list of picker options the admin needs to configure sources."""
    out: dict = {
        "transistor_shows": [],
        "convertkit_tags": [],
        "circle_spaces": [],
        "monday_boards": [],
        "tally_forms": [],
        "calendly_event_types": [],
        "youtube_channel": None,
        "errors": {},
    }
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
    try:
        out["tally_forms"] = await tally_list_forms()
    except Exception as e:
        out["errors"]["tally"] = str(e)
    try:
        out["calendly_event_types"] = await calendly_list_event_types()
    except Exception as e:
        out["errors"]["calendly"] = str(e)
    yt_handle = os.environ.get("YOUTUBE_CHANNEL_HANDLE")
    if yt_handle:
        try:
            out["youtube_channel"] = await youtube_resolve_channel(yt_handle)
        except Exception as e:
            out["errors"]["youtube"] = str(e)
    return out


async def pull_value(connector_type: str, params: dict, start_iso: str, end_iso: str) -> float:
    fn = CONNECTORS.get(connector_type)
    if not fn:
        raise ValueError(f"Unknown connector type: {connector_type}")
    return await fn(params or {}, start_iso, end_iso)
