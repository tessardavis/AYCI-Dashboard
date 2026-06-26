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

BOOKING LINK (June '26): https://calendly.com/d/cytf-7q4-nzy/ayci-bonus-call-june-26
- a fresh round-robin event is created each cohort, so this link is updated each
launch (here and in the Kit booking-link automation).

WHO IS ELIGIBLE: A student is eligible if they hold any of these ConvertKit tags
for the current cohort (the "[AYCI MON-YY]" prefix changes each launch):
  - "Purchase - Live webinar" (live-webinar signups - the majority)
  - "Legacy Video Launch Day 1 Upgrade" and "Legacy Video Launch Last Day Upgrade"
    (legacy upgrades on day 1 / the final day of the launch)
  - "Cart Close Signup" (signups on cart-close day)
  - "Ad Hoc Bonus Call" (allocated by hand by Arub/Tessa)
The first four are applied automatically at purchase by Kit/Kajabi. The Ad Hoc
tag is applied by the dashboard when a team member marks someone eligible.

WHERE THE TAGS ARE APPLIED (Zapier zaps, Kajabi purchase -> Kit tag):
  - Live webinar: https://zapier.com/editor/356253725/published
  - Legacy Day 1 + Last day ("Legacy Video Launch Upgrade Bonus Kit Tags"):
    https://zapier.com/editor/365778218/published
  - Cart Close ("Cart Close Bonus Call - Kit tag"): https://zapier.com/editor/365778815
These purchase-tagging zaps must NOT be deleted - the bonus-call flow depends on
them. The Ad Hoc tag is the only one applied by the dashboard (no zap).

MARKING SOMEONE ELIGIBLE (AD HOC): Arub is the person who does this. On a student's record - either Student Lookup
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

SETTING UP A NEW COHORT (the team does Kit + Calendly; the dashboard needs no change):
  1. [Arub] Create the cohort's Kit tags: "Purchase - Live webinar",
     "Legacy Video Launch Day 1 Upgrade", "Legacy Video Launch Last Day Upgrade",
     "Cart Close Signup", and "Ad Hoc Bonus Call".
  2. [Tessa/Megan] The Kit automation that emails the booking link - ideally ONE
     automation with all five tags as entry points. Update the booking link and
     the cohort name in the email copy.
  3. [Megan] Ensure the "Bonus Call Reminders" sequence has all five tags as entry
     points (currently only Live Webinar gets reminders - the others should too).
  4. [Arub/Megan] Create a fresh round-robin "AYCI Bonus call - <cohort>" Calendly
     event with coach availability (Onboarding Week to before the next one). Set
     the event's booking window so it only accepts bookings until the next cohort
     starts (date-range / scheduling limit), so calls can't roll over.
  5. Dashboard: nothing to change - it auto-detects the new tags + event. Keep
     Calendly connected (Settings > Integrations).
  6. End of cohort: read the snapshot (eligible/booked/no-show/rescheduled) on the
     Cohort Dashboard or Processes board; share with Tessa then coaches.

OPEN ITEMS being sorted (if asked): the Ad Hoc tag needs a Kit automation to send
its booking link; the four booking-link automations should be consolidated into
one (with the Ad Hoc tag added); the booking-link emails currently show the wrong
cohort name; reminders need extending beyond Live Webinar signups.


# Private Tier calls

WHAT IT IS: Students on the Private Plus and VIP tiers get a set of free 1:1
coaching calls as part of their package. They can be used ANY TIME - there is no
expiry (people were previously told 12 months, but they keep the allowance for as
long as they need). This is separate from bonus calls.

WHO GETS WHAT:
  - Private Plus: 1 x 30-minute coach call.
  - VIP: 2 x 30-minute calls with Tessa, 2 x 30-minute coach calls, and 1 x
    60-minute mock interview (5 calls in total).

WHO IS ELIGIBLE / HOW IT'S IDENTIFIED: When a student buys Private Plus or VIP,
the Sales Zap tags them on Circle for the current cohort:
  - "[AYCI MON-YY] Cohort - Private Plus" / "... Private Plus (4-Pay)"
  - "[AYCI MON-YY] Cohort - VIP" / "... VIP (6-Pay)" / "... VIP (12-Pay)"
That tier flows through to the dashboard as the student's tier, which sets their
call allowance. The Sales Zap that applies these Circle tier tags:
https://zapier.com/editor/00000000-0000-c000-8000-000365773719/published

HOW THEY GET THE BOOKING LINKS: in the onboarding email via the
"[AYCI MON-YY] Onboarding (Megan)" Kit automation
(https://app.kit.com/automations/1982218/edit), and in an initial post from
Coralie in their private chat (same links).

THE BOOKING LINKS + COACHES:
  - Private Plus 30-min coach call (Becky / Charlotte / Anoop):
    https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min
  - VIP 2 x 30-min with Tessa: https://calendly.com/tessardavis/ayci-vip-30-min
  - VIP 2 x 30-min coach calls (Becky) - the SAME link as Private Plus:
    https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min
  - VIP 60-min mock interview (Becky / Charlotte / Anoop):
    https://calendly.com/d/cttc-mx5-gz6/ayci-1-1-60-min

KEEPING AVAILABILITY OPEN: these links stay live all year, so availability has to
be kept topped up - set coach availability on Calendly well ahead of each launch,
keep it running consistently through the year, and do regular checks on each link
(Private Plus 30-min, VIP 60-min mock, VIP 2x30-min coach, VIP 2x30-min Tessa).

HOW BOOKINGS ARE TRACKED: when a student books any of these calls, the dashboard
logs the call against their record (which call, coach, date), shows allowance used
vs remaining, and posts to #fulfillment-team. Reschedules update the date
automatically. If a student doesn't show up, the coach opens that student's
Student Lookup card and marks that call a no-show. (Unlike bonus calls, there is
NO Kit tag applied on booking - private-tier reminders are manual via Coralie.)

REMINDERS: Coralie tracks who has interviews coming up and checks in with
private-tier students to remind them how to book and what allowance is left.

DATA: a monthly summary of completed 1:1 calls broken down by tier, call type, and
coach; and a summary of how many private-tier students had interviews and how much
of their allowance they used.

EACH COHORT: the dashboard needs no change - it reads the tier off each student and
matches the Calendly events by name, so the same booking links carry over. The
per-launch jobs are: confirm the Sales Zap is tagging the new cohort's tier tags,
update the cohort prefix in the onboarding email + Coralie's private-chat post, and
check coach availability is set on all the booking links.
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
