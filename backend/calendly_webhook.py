"""Inbound Calendly webhook → dashboard actions.

Replaces the Zapier "Bonus Call Booked (Anoop's calendar)" zap. On an
`invitee.created` event for the AYCI Bonus Call (a round-robin event), we:

  1. Tag the subscriber in Kit as "[AYCI <cohort>] 1:1 Call Booked" - this is
     what removes them from the booking-reminder emails. The current cohort's
     tag is resolved automatically (newest-first), so it survives the per-cohort
     rename without any code or config change.
  2. Record `bonus_call = "Booked - <host>"` on their academy_members row,
     pinned so the Monday sync can't wipe it (replaces the old Monday column).
  3. Post a heads-up to #fulfillment-team in Slack.

Calendly signs every delivery; we verify it with the signing key stored when the
subscription was registered (app_settings.calendly_webhook). See routes/calendly.py.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx

import connectors
import slack_dm

logger = logging.getLogger(__name__)

# Calendly event whose bookings we act on. Matched case-insensitively as a
# SUBSTRING so it survives the per-cohort rename
# ("AYCI Bonus call - June' 26" → "AYCI Bonus call - Sept '26").
BONUS_EVENT_MATCH = "bonus call"
# Kit tag suffix (the bit after the "[AYCI MON-YY]" prefix) to apply on booking.
KIT_BOOKED_TAG_SUFFIX = "1:1 Call Booked"
SLACK_CHANNEL = "#fulfillment-team"

# Manual/ad-hoc eligibility tag the dashboard applies when a team member marks
# a student eligible for a bonus call.
AD_HOC_TAG_SUFFIX = "Ad Hoc Bonus Call"
# Holding ANY of these (current cohort) means a student is eligible for a bonus
# call. The first four are applied automatically at purchase by Kit/Kajabi; the
# last is the dashboard-applied ad-hoc one. Matched by suffix so they rotate
# with the cohort prefix automatically.
ELIGIBILITY_TAG_SUFFIXES = [
    "Purchase - Live webinar",
    "Legacy Video Launch Day 1 Upgrade",
    "Legacy Video Launch Last Day Upgrade",
    "Cart Close Signup",
    AD_HOC_TAG_SUFFIX,
]

# --------------------------------------------------------------------------
# Private Tier calls (Private Plus / VIP). Separate from bonus calls: no Kit
# tag on booking (reminders are manual via Coralie). We log each booking to a
# `private_calls` array on the student row and derive allowance from `tier`.
# The three Calendly events back all private-tier calls (see PROCESSES.md #2):
#   ayci-1-1-30-min  -> coach_30  (Private Plus call, or a VIP coach call)
#   ayci-vip-30-min  -> tessa_30  (VIP, with Tessa)
#   ayci-1-1-60-min  -> mock_60   (VIP 60-min mock interview)
# --------------------------------------------------------------------------
PRIVATE_KIND_LABELS = {
    "coach_30": "30-min coach call",
    "tessa_30": "30-min call with Tessa",
    "mock_60": "60-min mock interview",
}
# Allowance per normalised tier -> how many of each kind they're entitled to.
PRIVATE_ALLOWANCE = {
    "Private Plus": {"coach_30": 1},
    "VIP": {"tessa_30": 2, "coach_30": 2, "mock_60": 1},
}


def _normalize_tier(tier) -> str | None:
    """Map the raw `tier` string to 'Private Plus' / 'VIP' (or None). Tolerant of
    label variants like 'Academy Private Plus' / 'VIP (12-Pay)'."""
    t = (tier or "").lower()
    if "vip" in t:
        return "VIP"
    if "private plus" in t:
        return "Private Plus"
    return None


def _classify_private_event(name: str, slug: str | None = None) -> str | None:
    """Classify a Calendly event into a private-tier call kind, or None. Keys off
    the event-type SLUG when available (stable IDs: ayci-1-1-30-min -> coach_30,
    ayci-vip-30-min -> tessa_30, ayci-1-1-60-min -> mock_60) plus the display
    name as a fallback, so it survives a rename of either. Bonus calls are
    handled elsewhere, so they're excluded here."""
    hay = f"{slug or ''} {name or ''}".lower()
    if BONUS_EVENT_MATCH in hay or "bonus" in hay:
        return None
    has_1on1 = "1:1" in hay or "1-1" in hay or "1 to 1" in hay
    if "vip" in hay and "30" in hay:
        return "tessa_30"
    if "60" in hay and (has_1on1 or "mock" in hay):
        return "mock_60"
    if "30" in hay and has_1on1:
        return "coach_30"
    return None


# Event-type URI -> slug, resolved once per process (event types are stable).
_EVENT_SLUG_CACHE: dict[str, str] = {}


async def _resolve_event_slug(event_type_uri: str) -> str | None:
    """Resolve a Calendly event-type URI to its slug (best-effort, cached). The
    webhook payload only carries the event-type URI + display name, not the slug;
    the slug is the stable identifier we'd rather classify on."""
    if not event_type_uri:
        return None
    if event_type_uri in _EVENT_SLUG_CACHE:
        return _EVENT_SLUG_CACHE[event_type_uri]
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(event_type_uri, headers=connectors._calendly_headers())
            r.raise_for_status()
            slug = (r.json().get("resource") or {}).get("slug")
            if slug:
                _EVENT_SLUG_CACHE[event_type_uri] = slug
            return slug
    except Exception as e:
        logger.warning(f"[calendly] event-type slug resolve failed: {e}")
        return None


_KIND_ORDER = ["tessa_30", "coach_30", "mock_60"]


def summarize_private_calls(tier, calls: list | None, extra: dict | None = None) -> dict:
    """Build the allowance view for a student: per-kind allowance / booked /
    remaining, plus the active bookings. 'booked' counts entries that aren't
    Cancelled or No-show. `extra` is a per-student allowance override (e.g.
    {"coach_30": 1} = one extra coach call on top of the tier default), set by a
    team member. Kinds that only appear via manual calls or an override are
    surfaced too, so nothing is hidden. Pure function - safe in the lookup path."""
    norm = _normalize_tier(tier)
    base = PRIVATE_ALLOWANCE.get(norm, {})
    extra = {k: v for k, v in (extra or {}).items() if v}
    calls = calls or []

    kinds = set(base) | set(extra) | {c.get("kind") for c in calls if c.get("kind")}
    order = {k: i for i, k in enumerate(_KIND_ORDER)}
    by_kind = {}
    for kind in sorted(kinds, key=lambda k: (order.get(k, 99), k)):
        allow = base.get(kind, 0) + extra.get(kind, 0)
        entries = [c for c in calls if c.get("kind") == kind]
        active = [c for c in entries if c.get("status") not in ("Cancelled", "No-show")]
        by_kind[kind] = {
            "label": PRIVATE_KIND_LABELS.get(kind, kind),
            "allowance": allow,
            "extra": extra.get(kind, 0),
            "booked": len(active),
            "remaining": max(0, allow - len(active)),
            "calls": sorted(entries, key=lambda c: c.get("date") or ""),
        }
    total_allow = sum(v["allowance"] for v in by_kind.values())
    total_booked = sum(v["booked"] for v in by_kind.values())
    return {
        "tier": norm,
        "eligible": bool(by_kind),
        "total_allowance": total_allow,
        "total_booked": total_booked,
        "total_remaining": max(0, total_allow - total_booked),
        "by_kind": by_kind,
    }


async def _get_signing_key(db) -> str:
    doc = await db.app_settings.find_one(
        {"id": "calendly_webhook"}, {"_id": 0, "signing_key": 1}
    )
    return (doc or {}).get("signing_key") or ""


def verify_signature(raw_body: bytes, header: str, signing_key: str) -> bool:
    """Verify Calendly's `Calendly-Webhook-Signature: t=<ts>,v1=<hmac>` header.
    The signed content is `<t>.<raw body>`, HMAC-SHA256 with the signing key."""
    if not header or not signing_key:
        return False
    try:
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
        t, v1 = parts.get("t"), parts.get("v1")
        if not t or not v1:
            return False
        signed = f"{t}.".encode() + raw_body
        expected = hmac.new(signing_key.encode(), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return False


def _host_from_payload(payload: dict) -> str | None:
    """First name of the assigned host (round-robin picks one of the pool)."""
    ev = payload.get("scheduled_event") or {}
    for m in (ev.get("event_memberships") or []):
        nm = m.get("user_name") or m.get("user_email")
        if nm:
            return nm.split()[0]
    return None


async def _match_student(db, email: str):
    """Find a student row by primary, Circle, or any 'Other emails' address."""
    return await db.academy_members.find_one({"$or": [
        {"email": email},
        {"circle_email": email},
        {"other_emails": {"$regex": re.escape(email), "$options": "i"}},
    ]})


async def _set_bonus_fields(db, row: dict, fields: dict) -> None:
    """Write bonus-call fields to a student row, pinned so the Monday sync can't
    overwrite them."""
    pinned = sorted(set(row.get("dashboard_edited_fields") or []) | set(fields.keys()))
    await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
        **fields,
        "dashboard_edited_fields": pinned,
        "dashboard_edited_at": datetime.now(timezone.utc),
        "dashboard_edited_by": "calendly-bonus-call",
    }})


async def handle_invitee_created(db, payload: dict) -> dict:
    """Process one Calendly invitee.created payload. Safe to call more than once
    for the same booking (deduped by invitee URI). Handles both fresh bookings
    and the new half of a reschedule."""
    ev = payload.get("scheduled_event") or {}
    event_name = ev.get("name") or ""
    if BONUS_EVENT_MATCH not in event_name.lower():
        slug = await _resolve_event_slug(ev.get("event_type") or "")
        kind = _classify_private_event(event_name, slug)
        if kind:
            return await handle_private_created(db, payload, kind)
        return {"skipped": "not_tracked", "event": event_name, "slug": slug}

    email = (payload.get("email") or "").strip().lower()
    if not email:
        return {"skipped": "no_email", "event": event_name}

    invitee_uri = payload.get("uri") or ""
    if invitee_uri and await db.calendly_events_seen.find_one({"_id": invitee_uri}):
        return {"skipped": "duplicate", "email": email}

    host = _host_from_payload(payload)
    start_time = ev.get("start_time") or ""
    call_date = start_time[:10] or None
    when = start_time[:16].replace("T", " ")
    is_reschedule = bool(payload.get("rescheduled")) or bool(payload.get("old_invitee"))

    # New half of a reschedule: recover the original date from the old invitee's
    # stored record so we can show "was X -> now Y".
    old_date = None
    old_uri = payload.get("old_invitee")
    if old_uri:
        prev = await db.calendly_events_seen.find_one({"_id": old_uri})
        if prev:
            old_date = prev.get("call_date") or (prev.get("start_time") or "")[:10] or None

    result = {"email": email, "event": event_name, "host": host, "call_date": call_date,
              "rescheduled": is_reschedule, "kit_tagged": False, "row_updated": False, "slack": False}

    # 1) Kit tag - stops the reminder emails. Current cohort's tag, newest-first.
    try:
        tag_ids = await connectors._resolve_ayci_cohort_tags(KIT_BOOKED_TAG_SUFFIX, exclude_future=True)
        if tag_ids:
            await connectors.convertkit_add_tag_to_subscriber(email, tag_ids[0])
            result["kit_tagged"] = tag_ids[0]
        else:
            logger.warning(
                f"[calendly] no '{KIT_BOOKED_TAG_SUFFIX}' Kit tag found - {email} not tagged"
            )
    except Exception as e:
        logger.warning(f"[calendly] Kit tag failed for {email}: {e}")

    # 2) Record the booking on the student row (pinned).
    try:
        row = await _match_student(db, email)
        if row:
            fields = {
                "bonus_call": f"Booked - {host}" if host else "Booked",
                "bonus_call_coach": host,
                "bonus_call_date": call_date,
                "bonus_call_status": "Rescheduled" if is_reschedule else "Booked",
            }
            if old_date:
                fields["bonus_call_rescheduled_from"] = old_date
            await _set_bonus_fields(db, row, fields)
            result["row_updated"] = row["_id"]
            if email not in (row.get("email"), row.get("circle_email")):
                # Matched via "other emails" - the booking email isn't their main
                # one, so they may have a duplicate ConvertKit subscriber.
                result["dup_email_note"] = row.get("email") or row.get("circle_email")
        else:
            result["row_updated"] = "student_not_found"
    except Exception as e:
        logger.warning(f"[calendly] row update failed for {email}: {e}")

    # 3) Slack heads-up to #fulfillment-team.
    try:
        name = payload.get("name") or email
        if is_reschedule:
            msg = (
                f":arrows_counterclockwise: *Bonus call rescheduled* - {name} ({email})"
                + (f" with *{host}*" if host else "")
                + (f" · now {when} UTC" if when else "")
                + (f" (was {old_date})" if old_date else "")
            )
        else:
            msg = (
                f":calendar: *Bonus call booked* - {name} ({email})"
                + (f" with *{host}*" if host else "")
                + (f" · {when} UTC" if when else "")
            )
        if result["row_updated"] == "student_not_found":
            msg += " · :warning: not found in dashboard - check their email"
        elif result.get("dup_email_note"):
            msg += (f" · :warning: booked under {email} but record's main email is "
                    f"{result['dup_email_note']} - check for a duplicate Kit subscriber")
        sl = await slack_dm.post_to_channel(db, SLACK_CHANNEL, msg)
        result["slack"] = bool(sl.get("ok"))
    except Exception as e:
        logger.warning(f"[calendly] Slack post failed for {email}: {e}")

    if invitee_uri:
        await db.calendly_events_seen.update_one(
            {"_id": invitee_uri},
            {"$set": {"_id": invitee_uri, "email": email, "name": payload.get("name"),
                      "coach": host, "call_date": call_date, "start_time": start_time,
                      "status": "rescheduled" if is_reschedule else "booked",
                      "matched": isinstance(result["row_updated"], str)
                      and result["row_updated"] != "student_not_found",
                      "at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    logger.info(f"[calendly] bonus-call processed: {result}")
    return result


async def handle_invitee_canceled(db, payload: dict) -> dict:
    """Process an invitee.canceled. A reschedule fires this for the OLD slot
    (rescheduled=True) - that half is handled by the new invitee.created, so we
    only flag it. A genuine cancellation marks the student's bonus call Cancelled
    and posts to Slack."""
    ev = payload.get("scheduled_event") or {}
    event_name = ev.get("name") or ""
    if BONUS_EVENT_MATCH not in event_name.lower():
        slug = await _resolve_event_slug(ev.get("event_type") or "")
        kind = _classify_private_event(event_name, slug)
        if kind:
            return await handle_private_canceled(db, payload, kind)
        return {"skipped": "not_tracked", "event": event_name, "slug": slug}

    email = (payload.get("email") or "").strip().lower()
    if not email:
        return {"skipped": "no_email"}

    invitee_uri = payload.get("uri") or ""
    if bool(payload.get("rescheduled")):
        # The new invitee.created (carrying old_invitee) does the update + Slack;
        # keep this record so it can read the original date, just flag it.
        if invitee_uri:
            await db.calendly_events_seen.update_one(
                {"_id": invitee_uri}, {"$set": {"status": "rescheduled_away"}}
            )
        return {"email": email, "skipped": "reschedule_cancel_half"}

    # Genuine cancellation - dedupe so a Calendly resend doesn't double-post.
    seen = await db.calendly_events_seen.find_one({"_id": invitee_uri}) if invitee_uri else None
    if seen and seen.get("status") == "cancelled":
        return {"email": email, "skipped": "duplicate_cancel"}

    result = {"email": email, "row_updated": False, "slack": False}
    try:
        row = await _match_student(db, email)
        if row:
            await _set_bonus_fields(db, row, {"bonus_call_status": "Cancelled"})
            result["row_updated"] = row["_id"]
    except Exception as e:
        logger.warning(f"[calendly] cancel row update failed for {email}: {e}")

    try:
        name = payload.get("name") or email
        reason = ((payload.get("cancellation") or {}).get("reason") or "").strip()
        msg = (f":x: *Bonus call cancelled* - {name} ({email})"
               + (f" · {reason}" if reason else ""))
        sl = await slack_dm.post_to_channel(db, SLACK_CHANNEL, msg)
        result["slack"] = bool(sl.get("ok"))
    except Exception as e:
        logger.warning(f"[calendly] cancel Slack failed for {email}: {e}")

    if invitee_uri:
        await db.calendly_events_seen.update_one(
            {"_id": invitee_uri},
            {"$set": {"_id": invitee_uri, "email": email, "status": "cancelled",
                      "at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    logger.info(f"[calendly] bonus-call cancellation processed: {result}")
    return result


async def backfill_bonus_call_tags(db, days_back: int = 120, days_fwd: int = 120) -> dict:
    """One-shot catch-up: tag every AYCI Bonus Call booker (past + upcoming, in
    the window) with the current cohort's "1:1 Call Booked" Kit tag and record
    `bonus_call` on their row - for bookings missed while the Zapier zaps were
    off. Covers Anoop AND Charlotte (the round-robin pool). Idempotent (Kit
    no-ops if already tagged). Deliberately does NOT Slack - that would spam
    #fulfillment-team with old bookings."""
    headers = connectors._calendly_headers()
    base = connectors.CALENDLY_BASE
    now = datetime.now(timezone.utc)

    def _fmt(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    summary = {"events_scanned": 0, "bonus_events": 0, "invitees": 0,
               "unique_emails": 0, "tagged": 0, "recorded": 0, "not_found": 0,
               "errors": 0}

    tag_ids = await connectors._resolve_ayci_cohort_tags(KIT_BOOKED_TAG_SUFFIX, exclude_future=True)
    booked_tag = tag_ids[0] if tag_ids else None
    summary["booked_tag"] = booked_tag

    emails: dict[str, str | None] = {}  # email -> host first name

    async with httpx.AsyncClient(timeout=60) as c:
        me = await c.get(f"{base}/users/me", headers=headers)
        me.raise_for_status()
        org = (me.json().get("resource") or {}).get("current_organization")
        if not org:
            return {**summary, "error": "could not resolve organization"}

        url = f"{base}/scheduled_events"
        params = {"organization": org, "status": "active", "count": 100,
                  "min_start_time": _fmt(now - timedelta(days=days_back)),
                  "max_start_time": _fmt(now + timedelta(days=days_fwd)),
                  "sort": "start_time:asc"}
        while url:
            r = await c.get(url, headers=headers, params=params)
            r.raise_for_status()
            body = r.json()
            for ev in body.get("collection", []):
                summary["events_scanned"] += 1
                if BONUS_EVENT_MATCH not in (ev.get("name") or "").lower():
                    continue
                summary["bonus_events"] += 1
                host = None
                for m in (ev.get("event_memberships") or []):
                    nm = m.get("user_name") or m.get("user_email")
                    if nm:
                        host = nm.split()[0]
                        break
                inv_url = f"{ev.get('uri')}/invitees"
                inv_params = {"count": 100, "status": "active"}
                while inv_url:
                    ir = await c.get(inv_url, headers=headers, params=inv_params)
                    ir.raise_for_status()
                    ib = ir.json()
                    for inv in ib.get("collection", []):
                        summary["invitees"] += 1
                        em = (inv.get("email") or "").strip().lower()
                        if em and em not in emails:
                            emails[em] = host
                    inv_url = (ib.get("pagination") or {}).get("next_page")
                    inv_params = None  # next_page is a full, param-encoded URL
            url = (body.get("pagination") or {}).get("next_page")
            params = None

    summary["unique_emails"] = len(emails)

    for em, host in emails.items():
        if booked_tag:
            try:
                await connectors.convertkit_add_tag_to_subscriber(em, booked_tag)
                summary["tagged"] += 1
            except Exception as e:
                summary["errors"] += 1
                logger.warning(f"[calendly-backfill] Kit tag failed {em}: {e}")
        try:
            row = await db.academy_members.find_one({"$or": [
                {"email": em},
                {"circle_email": em},
                {"other_emails": {"$regex": re.escape(em), "$options": "i"}},
            ]})
            if row:
                pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"bonus_call"})
                await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
                    "bonus_call": f"Booked - {host}" if host else "Booked",
                    "dashboard_edited_fields": pinned,
                    "dashboard_edited_at": datetime.now(timezone.utc),
                    "dashboard_edited_by": "calendly-bonus-call-backfill",
                }})
                summary["recorded"] += 1
            else:
                summary["not_found"] += 1
        except Exception as e:
            summary["errors"] += 1
            logger.warning(f"[calendly-backfill] row update failed {em}: {e}")

    logger.info(f"[calendly-backfill] {summary}")
    return summary


# ============================== Private Tier calls =========================

async def _record_private_call(db, row: dict, entry: dict, *, replace_uri=None) -> None:
    """Insert/update one entry in the student's `private_calls` array (deduped by
    invitee_uri), pinned so the Monday sync can't wipe it. On a reschedule, pass
    the OLD invitee uri as replace_uri so the moved booking isn't duplicated."""
    calls = list(row.get("private_calls") or [])
    uri = entry.get("invitee_uri")
    drop = {uri} | ({replace_uri} if replace_uri else set())
    calls = [c for c in calls if c.get("invitee_uri") not in drop]
    calls.append(entry)
    pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"private_calls"})
    await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
        "private_calls": calls,
        "dashboard_edited_fields": pinned,
        "dashboard_edited_at": datetime.now(timezone.utc),
        "dashboard_edited_by": "calendly-private-call",
    }})


async def set_private_call_status(db, row: dict, invitee_uri: str, status: str) -> bool:
    """Set the status (e.g. Attended / No-show / Cancelled) of one private call on
    a student row, keyed by invitee_uri. Returns False if no call matched."""
    calls = list(row.get("private_calls") or [])
    changed = False
    for c in calls:
        if c.get("invitee_uri") == invitee_uri:
            c["status"] = status
            changed = True
    if not changed:
        return False
    pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"private_calls"})
    await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
        "private_calls": calls,
        "dashboard_edited_fields": pinned,
        "dashboard_edited_at": datetime.now(timezone.utc),
        "dashboard_edited_by": "dashboard-private-call",
    }})
    return True


async def add_manual_private_call(db, row: dict, kind: str, coach, date, status: str) -> dict:
    """Log a private-tier call that wasn't booked through Calendly (counts as one
    of the student's eligible calls). Gets a synthetic 'manual:' invitee_uri so it
    dedupes and so the Attended/No-show action works on it like any booking."""
    uri = f"manual:{kind}:{uuid.uuid4().hex[:12]}"
    entry = {"kind": kind, "coach": (coach or None), "date": (date or None),
             "status": status, "invitee_uri": uri, "event_name": "Logged manually",
             "manual": True}
    await _record_private_call(db, row, entry)
    logger.info(f"[private-call] manual call logged for {row.get('_id')}: {kind} {status}")
    return entry


async def adjust_private_allowance(db, row: dict, kind: str, delta: int) -> dict:
    """Adjust a student's extra (above-tier) allowance for one call kind by delta.
    Stored in `private_call_allowance` ({kind: extra_count}), pinned. Clamped at 0;
    a kind that drops to 0 is removed. Returns the new override dict."""
    extra = dict(row.get("private_call_allowance") or {})
    extra[kind] = max(0, int(extra.get(kind) or 0) + int(delta))
    if not extra[kind]:
        extra.pop(kind, None)
    pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"private_call_allowance"})
    await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
        "private_call_allowance": extra,
        "dashboard_edited_fields": pinned,
        "dashboard_edited_at": datetime.now(timezone.utc),
        "dashboard_edited_by": "dashboard-private-call",
    }})
    logger.info(f"[private-call] allowance for {row.get('_id')} {kind} -> +{extra.get(kind, 0)}")
    return extra


async def handle_private_created(db, payload: dict, kind: str) -> dict:
    """Process one private-tier (Private Plus / VIP) booking. Logs it to the
    student's `private_calls` array and posts to Slack. No Kit tag (private-tier
    reminders are manual). Handles fresh bookings and the new half of a reschedule."""
    email = (payload.get("email") or "").strip().lower()
    if not email:
        return {"skipped": "no_email", "kind": kind}
    ev = payload.get("scheduled_event") or {}
    event_name = ev.get("name") or ""
    invitee_uri = payload.get("uri") or ""
    if invitee_uri and await db.calendly_events_seen.find_one({"_id": invitee_uri}):
        return {"skipped": "duplicate", "email": email, "kind": kind}

    host = _host_from_payload(payload)
    start_time = ev.get("start_time") or ""
    call_date = start_time[:10] or None
    when = start_time[:16].replace("T", " ")
    is_reschedule = bool(payload.get("rescheduled")) or bool(payload.get("old_invitee"))

    old_uri = payload.get("old_invitee")
    old_date = None
    if old_uri:
        prev = await db.calendly_events_seen.find_one({"_id": old_uri})
        if prev:
            old_date = prev.get("call_date") or (prev.get("start_time") or "")[:10] or None

    label = PRIVATE_KIND_LABELS.get(kind, kind)
    result = {"email": email, "kind": kind, "event": event_name, "host": host,
              "call_date": call_date, "rescheduled": is_reschedule,
              "row_updated": False, "slack": False}

    summary = None
    try:
        row = await _match_student(db, email)
        if row:
            entry = {"kind": kind, "coach": host, "date": call_date,
                     "status": "Rescheduled" if is_reschedule else "Booked",
                     "invitee_uri": invitee_uri, "event_name": event_name}
            if old_date:
                entry["rescheduled_from"] = old_date
            await _record_private_call(db, row, entry, replace_uri=old_uri)
            result["row_updated"] = row["_id"]
            fresh = await db.academy_members.find_one(
                {"_id": row["_id"]}, {"tier": 1, "private_calls": 1})
            summary = summarize_private_calls(
                (fresh or {}).get("tier"), (fresh or {}).get("private_calls"))
            if email not in (row.get("email"), row.get("circle_email")):
                result["dup_email_note"] = row.get("email") or row.get("circle_email")
        else:
            result["row_updated"] = "student_not_found"
    except Exception as e:
        logger.warning(f"[calendly] private-call row update failed for {email}: {e}")

    try:
        name = payload.get("name") or email
        kinfo = (summary or {}).get("by_kind", {}).get(kind)
        used = (f" ({kinfo['booked']}/{kinfo['allowance']} used)"
                if kinfo and kinfo["allowance"] > 1 else "")
        if is_reschedule:
            msg = (f":arrows_counterclockwise: *Private Tier call rescheduled* - {name} ({email}) - {label}"
                   + (f" with *{host}*" if host else "")
                   + (f" · now {when} UTC" if when else "")
                   + (f" (was {old_date})" if old_date else ""))
        else:
            msg = (f":telephone_receiver: *Private Tier call booked* - {name} ({email}) - {label}"
                   + (f" with *{host}*" if host else "")
                   + (f" · {when} UTC" if when else "") + used)
        if result["row_updated"] == "student_not_found":
            msg += " · :warning: not found in dashboard - check their email"
        elif result.get("dup_email_note"):
            msg += (f" · :warning: booked under {email} but record's main email is "
                    f"{result['dup_email_note']} - check for a duplicate subscriber")
        sl = await slack_dm.post_to_channel(db, SLACK_CHANNEL, msg)
        result["slack"] = bool(sl.get("ok"))
    except Exception as e:
        logger.warning(f"[calendly] private-call Slack post failed for {email}: {e}")

    if invitee_uri:
        await db.calendly_events_seen.update_one(
            {"_id": invitee_uri},
            {"$set": {"_id": invitee_uri, "email": email, "name": payload.get("name"),
                      "coach": host, "call_date": call_date, "start_time": start_time,
                      "kind": kind, "private": True,
                      "status": "rescheduled" if is_reschedule else "booked",
                      "matched": result["row_updated"] not in (False, "student_not_found"),
                      "at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    logger.info(f"[calendly] private-call processed: {result}")
    return result


async def handle_private_canceled(db, payload: dict, kind: str) -> dict:
    """invitee.canceled for a private-tier event. A reschedule fires this for the
    OLD slot (handled by the new invitee.created); a genuine cancel marks that
    call Cancelled on the student row and posts to Slack."""
    email = (payload.get("email") or "").strip().lower()
    invitee_uri = payload.get("uri") or ""
    if bool(payload.get("rescheduled")):
        if invitee_uri:
            await db.calendly_events_seen.update_one(
                {"_id": invitee_uri}, {"$set": {"status": "rescheduled_away"}})
        return {"email": email, "kind": kind, "skipped": "reschedule_cancel_half"}

    seen = await db.calendly_events_seen.find_one({"_id": invitee_uri}) if invitee_uri else None
    if seen and seen.get("status") == "cancelled":
        return {"email": email, "skipped": "duplicate_cancel"}

    result = {"email": email, "kind": kind, "row_updated": False, "slack": False}
    try:
        row = await _match_student(db, email)
        if row:
            ok = await set_private_call_status(db, row, invitee_uri, "Cancelled")
            result["row_updated"] = row["_id"] if ok else "no_matching_call"
    except Exception as e:
        logger.warning(f"[calendly] private cancel row update failed for {email}: {e}")

    try:
        name = payload.get("name") or email
        label = PRIVATE_KIND_LABELS.get(kind, kind)
        reason = ((payload.get("cancellation") or {}).get("reason") or "").strip()
        msg = (f":x: *Private Tier call cancelled* - {name} ({email}) - {label}"
               + (f" · {reason}" if reason else ""))
        sl = await slack_dm.post_to_channel(db, SLACK_CHANNEL, msg)
        result["slack"] = bool(sl.get("ok"))
    except Exception as e:
        logger.warning(f"[calendly] private cancel Slack failed for {email}: {e}")

    if invitee_uri:
        await db.calendly_events_seen.update_one(
            {"_id": invitee_uri},
            {"$set": {"_id": invitee_uri, "email": email, "kind": kind, "private": True,
                      "status": "cancelled", "at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    logger.info(f"[calendly] private-call cancellation processed: {result}")
    return result


async def backfill_private_calls(db, days_back: int = 180, days_fwd: int = 180) -> dict:
    """One-shot catch-up: scan past + upcoming Calendly bookings in the window,
    classify the private-tier events, and record each booking on the matching
    student's `private_calls` array. Idempotent (deduped by invitee uri). No
    Slack, no Kit tag."""
    headers = connectors._calendly_headers()
    base = connectors.CALENDLY_BASE
    now = datetime.now(timezone.utc)

    def _fmt(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    summary = {"events_scanned": 0, "private_events": 0, "invitees": 0,
               "recorded": 0, "not_found": 0, "errors": 0, "by_kind": {}}
    bookings: list[dict] = []

    async with httpx.AsyncClient(timeout=60) as c:
        me = await c.get(f"{base}/users/me", headers=headers)
        me.raise_for_status()
        org = (me.json().get("resource") or {}).get("current_organization")
        if not org:
            return {**summary, "error": "could not resolve organization"}

        url = f"{base}/scheduled_events"
        params = {"organization": org, "status": "active", "count": 100,
                  "min_start_time": _fmt(now - timedelta(days=days_back)),
                  "max_start_time": _fmt(now + timedelta(days=days_fwd)),
                  "sort": "start_time:asc"}
        while url:
            r = await c.get(url, headers=headers, params=params)
            r.raise_for_status()
            body = r.json()
            for ev in body.get("collection", []):
                summary["events_scanned"] += 1
                slug = await _resolve_event_slug(ev.get("event_type") or "")
                kind = _classify_private_event(ev.get("name") or "", slug)
                if not kind:
                    continue
                summary["private_events"] += 1
                summary["by_kind"][kind] = summary["by_kind"].get(kind, 0) + 1
                host = None
                for m in (ev.get("event_memberships") or []):
                    nm = m.get("user_name") or m.get("user_email")
                    if nm:
                        host = nm.split()[0]
                        break
                ev_date = (ev.get("start_time") or "")[:10] or None
                ev_name = ev.get("name") or ""
                inv_url = f"{ev.get('uri')}/invitees"
                inv_params = {"count": 100, "status": "active"}
                while inv_url:
                    ir = await c.get(inv_url, headers=headers, params=inv_params)
                    ir.raise_for_status()
                    ib = ir.json()
                    for inv in ib.get("collection", []):
                        summary["invitees"] += 1
                        em = (inv.get("email") or "").strip().lower()
                        if not em:
                            continue
                        bookings.append({"email": em, "kind": kind, "coach": host,
                                         "date": ev_date, "invitee_uri": inv.get("uri") or "",
                                         "event_name": ev_name})
                    inv_url = (ib.get("pagination") or {}).get("next_page")
                    inv_params = None
            url = (body.get("pagination") or {}).get("next_page")
            params = None

    by_email: dict[str, list] = {}
    for b in bookings:
        by_email.setdefault(b["email"], []).append(b)

    for em, items in by_email.items():
        try:
            row = await db.academy_members.find_one({"$or": [
                {"email": em}, {"circle_email": em},
                {"other_emails": {"$regex": re.escape(em), "$options": "i"}}]})
            if not row:
                summary["not_found"] += 1
                continue
            calls = list(row.get("private_calls") or [])
            existing = {c.get("invitee_uri") for c in calls}
            for b in items:
                if b["invitee_uri"] in existing:
                    continue
                calls.append({"kind": b["kind"], "coach": b["coach"], "date": b["date"],
                              "status": "Booked", "invitee_uri": b["invitee_uri"],
                              "event_name": b["event_name"]})
                existing.add(b["invitee_uri"])
                summary["recorded"] += 1
            pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"private_calls"})
            await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
                "private_calls": calls,
                "dashboard_edited_fields": pinned,
                "dashboard_edited_at": datetime.now(timezone.utc),
                "dashboard_edited_by": "calendly-private-backfill",
            }})
        except Exception as e:
            summary["errors"] += 1
            logger.warning(f"[private-backfill] row update failed {em}: {e}")

    logger.info(f"[private-backfill] {summary}")
    return summary
