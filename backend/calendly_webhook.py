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
import hashlib
import hmac
import logging
import re
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
        return {"skipped": "not_bonus_call", "event": event_name}

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
        tag_ids = await connectors._resolve_ayci_cohort_tags(KIT_BOOKED_TAG_SUFFIX)
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
        sl = await slack_dm.post_to_channel(db, SLACK_CHANNEL, msg)
        result["slack"] = bool(sl.get("ok"))
    except Exception as e:
        logger.warning(f"[calendly] Slack post failed for {email}: {e}")

    if invitee_uri:
        await db.calendly_events_seen.update_one(
            {"_id": invitee_uri},
            {"$set": {"_id": invitee_uri, "email": email, "coach": host,
                      "call_date": call_date, "start_time": start_time,
                      "status": "rescheduled" if is_reschedule else "booked",
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
        return {"skipped": "not_bonus_call", "event": event_name}

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

    tag_ids = await connectors._resolve_ayci_cohort_tags(KIT_BOOKED_TAG_SUFFIX)
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
