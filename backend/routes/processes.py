"""Processes Q&A - lets the team ask questions about documented processes and
get answers grounded ONLY in the process docs. Uses the existing Anthropic
client (llm_client / ANTHROPIC_API_KEY, already configured for doc briefings).
Powers the "Ask about the processes" box on the Processes board.
"""
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

import llm_client
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["processes"])
logger = logging.getLogger(__name__)

# Knowledge base the assistant answers from. Keep in sync with PROCESSES.md /
# the Processes board. Add a new process as a new section here.
PROCESS_DOCS = """
# Bonus calls

WHAT IT IS: Some students get a free 30-minute 1:1 coaching ("bonus") call
depending on when they signed up. It's booked via a round-robin Calendly event
shared by the bonus-call coaches (currently Anoop and Charlotte) and should be
used before the next cohort starts.

WHO IS ELIGIBLE: A student is eligible if they hold any of these ConvertKit tags
for the current cohort (the "[AYCI MON-YY]" prefix changes each launch):
  - "Purchase - Live webinar" (live-webinar signups - the majority)
  - "Legacy Video Launch Day 1 Upgrade" and "Legacy Video Launch Last Day Upgrade"
    (legacy upgrades on day 1 / the final day of the launch)
  - "Cart Close Signup" (signups on cart-close day)
  - "Ad Hoc Bonus Call" (allocated by hand by Arub/Tessa)
The first four are applied automatically at purchase by Kit/Kajabi. The Ad Hoc
tag is applied by the dashboard when a team member marks someone eligible.

MARKING SOMEONE ELIGIBLE (AD HOC): On a student's record - either Student Lookup
(the "Coach view" card at the top) or Students DB > Edit - click
"Mark eligible (ad hoc)". That tags them "Ad Hoc Bonus Call" in Kit, which
triggers Kit's email with the booking link.

GETTING THE LINK + REMINDERS: When eligible, Kit emails them the booking link.
Everyone with "Purchase - Live webinar" also enters the "Bonus Call Reminders
(Megan)" Kit sequence (4 reminders: 5 days after tagging, then +7, +7, +3 days).
They are removed from the reminders the moment they book, because booking applies
the "1:1 Call Booked" tag, which is the sequence's exclusion tag.

WHEN A STUDENT BOOKS: The Calendly bonus-call event posts straight to the
dashboard (no Zapier). The dashboard then: (1) tags them "1:1 Call Booked" in Kit
so the reminders stop; (2) records the booking (coach + date) on their student
record; (3) posts a note to the #fulfillment-team Slack channel. Reschedules and
cancellations are picked up automatically too (with the old and new dates).

WHERE THE BOOKING SHOWS: On the student's record (the Coach-view "Bonus call"
line shows Booked/Attended/No-show with the date and coach; the Calendly Calls
card also lists it).

LOGGING AN AD-HOC / OFF-CALENDLY CALL, OR NO-SHOW: Open the student in Students DB
> Edit and set "Bonus call status" (Booked / Attended / No-show / Rescheduled /
Cancelled / Done), plus the date and coach. This is also how a coach marks that a
student did not show up.

BOOKING UNDER A DIFFERENT EMAIL: The dashboard matches a booking to a student
across their primary, Circle, and "Other emails". If a booking comes in under a
brand-new email, it's flagged "not found" in the Slack alert and appears under
Settings > Integrations > "Unmatched bonus-call bookings", where you link it to
the right student (which saves that email to their Other emails so it matches in
future). If the same person has two ConvertKit subscribers, consolidate them in
Kit so they don't get double emails.

EACH COHORT: The team sets up the new cohort's Kit tags, their email automations,
and a fresh round-robin Calendly event each launch (confirm coach dates with Arub;
usually 50-70 calls). The dashboard adapts automatically - it finds the current
cohort's tags by pattern and matches the Calendly event by the words "bonus call",
so no dashboard change is needed per cohort.
"""


class AskBody(BaseModel):
    question: str


@router.post("/processes/ask")
async def ask_processes(body: AskBody, user: dict = Depends(get_current_user)):
    """Answer a team question from the process docs only."""
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(400, "question required")
    if llm_client.get_client() is None:
        raise HTTPException(503, "The processes assistant isn't switched on yet (no API key on the server).")
    system = (
        "You are a concise, practical assistant for the AYCI Academy team's "
        "internal dashboard. Answer the team member's question using ONLY the "
        "process documentation below. If the answer isn't in the docs, say you're "
        "not sure and suggest they check with Tessa - never invent steps, tags, or "
        "field names. Keep answers short and actionable.\n\n"
        "=== PROCESS DOCUMENTATION ===\n" + PROCESS_DOCS
    )
    try:
        answer = await llm_client.complete(system=system, user=q, max_tokens=600)
    except Exception as e:
        logger.warning(f"[processes-qa] LLM call failed: {e}")
        raise HTTPException(502, "Couldn't reach the assistant - try again in a moment.")
    return {"answer": answer}
