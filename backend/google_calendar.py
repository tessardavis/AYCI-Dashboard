"""
Google Calendar client for the "AYCI Interviews" calendar - keeps exactly one
interview event per student at their authoritative (Tally-reconciled) date.
See ~/.claude/plans/fluffy-discovering-cake.md (Part 2).

Mirrors google_drive.py's service-account loader. INERT until:
  - GOOGLE_INTERVIEWS_CALENDAR_ID is set, AND
  - the "AYCI Interviews" calendar is shared with the dashboard service account
    (the client_email inside GOOGLE_SERVICE_ACCOUNT_FILE) with "Make changes to
    events".
Until then is_configured() is False and ensure_interview_event() is a no-op.

Events are matched/deduped by `location == "ID: <monday_item_id>"` - verified
live: Zapier Zap 20 writes the student's Monday item id (= mirror row `_id`)
into the event location. Events are all-day, titled "<name> - <type> interview".
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _calendar_id() -> str | None:
    return (os.environ.get("GOOGLE_INTERVIEWS_CALENDAR_ID") or "").strip() or None


def is_configured() -> bool:
    return bool(_calendar_id()) and bool((os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE") or "").strip())


def _calendar_service():
    """Build a Calendar client from a service-account JSON file path OR the raw
    JSON pasted into GOOGLE_SERVICE_ACCOUNT_FILE (same convention as
    google_drive._drive_service)."""
    sa_value = (os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE") or "").strip()
    if not sa_value:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE not configured")
    if not sa_value.lstrip().startswith("{") and os.path.exists(sa_value):
        creds = service_account.Credentials.from_service_account_file(sa_value, scopes=SCOPES)
    else:
        try:
            info = json.loads(sa_value)
        except Exception as e:
            raise RuntimeError(
                f"GOOGLE_SERVICE_ACCOUNT_FILE is neither a valid path nor valid JSON: {e}"
            ) from e
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


async def selftest() -> dict:
    """Confirm the service account can WRITE to the calendar: create a throwaway
    far-future all-day event, then delete it. Returns {ok, can_write, detail}.
    A failure here means the calendar isn't shared with the service account with
    'Make changes to events'."""
    if not is_configured():
        return {"ok": False, "can_write": False,
                "detail": "not configured - GOOGLE_INTERVIEWS_CALENDAR_ID or credentials missing"}
    cal_id = _calendar_id()

    def _sync() -> str:
        svc = _calendar_service()
        ev = svc.events().insert(calendarId=cal_id, body={
            "summary": "[dashboard calendar self-test - safe to ignore]",
            "start": {"date": "2099-01-01"},
            "end": {"date": "2099-01-02"},
        }).execute()
        eid = ev.get("id")
        svc.events().delete(calendarId=cal_id, eventId=eid).execute()
        return eid

    try:
        eid = await asyncio.to_thread(_sync)
        return {"ok": True, "can_write": True, "detail": f"created + deleted test event {eid}"}
    except Exception as e:
        return {"ok": False, "can_write": False, "detail": str(e)[:300]}


def _event_title(row: dict) -> str:
    name = (row.get("name") or "").strip() or "Student"
    itype = (row.get("interview_type") or "").strip()
    return f"{name} - {itype} interview" if itype else f"{name} - interview"


async def ensure_interview_event(db_, row: dict) -> bool:
    """Guarantee exactly one all-day event at row['interview_date'] for this
    student, matched by location == "ID: <_id>". Deletes events on that key with
    a different date and creates one if none remains at the right date. Returns
    True if it created/changed anything; False on no-op or when not configured.
    """
    if not is_configured():
        return False
    target = (str(row.get("interview_date") or ""))[:10]
    monday_id = str(row.get("_id") or "").strip()
    if not target or not monday_id:
        return False
    try:
        date.fromisoformat(target)
    except ValueError:
        return False

    cal_id = _calendar_id()
    loc_key = f"ID: {monday_id}"
    title = _event_title(row)

    def _sync() -> bool:
        svc = _calendar_service()
        existing = []
        page_token = None
        while True:
            resp = svc.events().list(
                calendarId=cal_id, q=loc_key, singleEvents=True,
                maxResults=250, pageToken=page_token,
            ).execute()
            for ev in resp.get("items", []):
                if (ev.get("location") or "").strip() == loc_key:
                    existing.append(ev)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        changed = False
        has_correct = False
        for ev in existing:
            ev_date = (ev.get("start", {}).get("date") or "")[:10]
            if ev_date == target:
                has_correct = True
            else:
                svc.events().delete(calendarId=cal_id, eventId=ev["id"]).execute()
                logger.info(f"[google-calendar] deleted stale event {ev['id']} ({ev_date}) for {loc_key}")
                changed = True
        if not has_correct:
            end = (date.fromisoformat(target) + timedelta(days=1)).isoformat()
            svc.events().insert(calendarId=cal_id, body={
                "summary": title,
                "location": loc_key,
                "start": {"date": target},
                "end": {"date": end},
            }).execute()
            logger.info(f"[google-calendar] created event {target} for {loc_key}")
            changed = True
        return changed

    return await asyncio.to_thread(_sync)
