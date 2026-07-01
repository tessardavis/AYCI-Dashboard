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


# Private tier calls

WHAT IT IS: Students on the Private Plus and VIP tiers get a set of free 1:1
coaching calls as part of their package. They can be used ANY TIME - there is no
expiry (people were previously told 12 months, but they keep the allowance for as
long as they need). This is separate from bonus calls.

WALKTHROUGH VIDEO: https://www.loom.com/share/9d9aa53be0d648159fe25bbf809d268e

WHO GETS WHAT:
  - Private Plus: 1 x 30-minute coach call.
  - VIP: 2 x 30-minute calls with Tessa, 2 x 30-minute coach calls, and 1 x
    60-minute mock interview (5 calls in total).
  - Boost & Go: 1 x 60-minute mock interview.
  - Boost & Go Plus: 2 x 30-minute coach calls (same 30-min coach link) + 1 x
    60-minute mock interview. B&G (Plus) students are usually existing Academy
    members who upgrade - once tagged on the dashboard (their Boost & Go field),
    their call allowance shows automatically and their chat is created by the
    Boost & Go chat zap.

WHO IS ELIGIBLE / HOW IT'S IDENTIFIED: When a student buys Private Plus or VIP,
the Sales Zap tags them in ConvertKit (Kit) for the current cohort:
  - "[AYCI MON-YY] Cohort - Private Plus" / "... Private Plus (4-Pay)"
  - "[AYCI MON-YY] Cohort - VIP" / "... VIP (6-Pay)" / "... VIP (12-Pay)"
That tier flows through to the dashboard as the student's tier, which sets their
call allowance. The Sales Zap that applies these Kit tier tags:
https://zapier.com/editor/365773719/published

HOW THEY GET THE BOOKING LINKS: in the onboarding email via the
"[AYCI MON-YY] Onboarding (Megan)" Kit automation
(https://app.kit.com/automations/1982218/edit), and in an initial post from
Coralie in their private chat (same links).

THE BOOKING LINKS + COACHES:
  - Private Plus 30-min coach call (Becky / Charlotte / Anoop):
    https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min
  - VIP 2 x 30-min with Tessa: https://calendly.com/tessardavis/ayci-vip-30-min
  - VIP 2 x 30-min coach calls (Becky, Anoop, or Charlotte) - the SAME link as
    Private Plus: https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min
  - VIP 60-min mock interview (Becky / Charlotte / Anoop):
    https://calendly.com/d/cttc-mx5-gz6/ayci-1-1-60-min

KEEPING AVAILABILITY OPEN: these links stay live all year, so availability has to
be kept topped up - coach availability needs to be set up on Calendly each month,
keep it running consistently through the year, and do regular checks on each link
(Private Plus 30-min, VIP 60-min mock, VIP 2x30-min coach, VIP 2x30-min Tessa).

HOW BOOKINGS ARE TRACKED: when a student books any of these calls, the dashboard
logs the call against their record (which call, coach, date), shows allowance used
vs remaining, and posts to #fulfillment-team. Reschedules update the date
automatically. If a student doesn't show up, the coach opens that student's
Student Lookup card and marks that call a no-show. (Unlike bonus calls, there is
NO Kit tag applied on booking - private-tier reminders are manual via Coralie.)

LOGGING AN OFF-CALENDLY CALL + GRANTING EXTRA ALLOWANCE: on the Student Lookup
card (or Students DB > Edit) a team member can "Log a call" that wasn't booked through Calendly (pick the
type, coach, date, outcome - defaults to Attended; it counts as one of their
eligible calls), and can grant or remove EXTRA allowance above the tier default
using the + / - buttons next to a call type (e.g. give a VIP a 3rd coach call).
The extra allowance is stored per student and persists.

REMINDERS: Coralie tracks who has interviews coming up and checks in with
private-tier students to remind them how to book and what allowance is left.

DATA: on the 1st of each month the dashboard AUTOMATICALLY posts the previous
month's summary to the #private-tiers Slack channel - 1:1 calls held, broken down
by tier, call type and coach (plus no-shows / cancellations). No one compiles it
by hand. (Also tracked: how many private-tier students had interviews and how much
of their allowance they used.)

EACH COHORT: the dashboard needs no change - it reads the tier off each student and
matches the Calendly events by name, so the same booking links carry over. The
per-launch jobs are: confirm the Sales Zap is tagging the new cohort's tier tags,
update the cohort prefix in the onboarding email + Coralie's private-chat post, and
check coach availability is set on all the booking links.


# Private chat

WHAT IT IS: Every Private Plus, VIP and active Boost & Go student gets a private
group chat on Circle with the coaching team - where they ask questions, get video
feedback, and find the links they need.

WALKTHROUGH VIDEO: https://www.loom.com/share/f52b61461a2646179a3ce412ab62ea03

WHO'S IN THE CHAT: the student plus - the coaches Tessa & Becky, and AYCI team
members Arub & Coralie. (Oksana is no longer added to new chats; older chats keep
whoever was in them - you can't remove people from a Circle group DM.) The member
list is editable in Settings > Integrations > Private chat setup.

HOW A CHAT GETS CREATED (two paths): the Zapier zaps are the PRIMARY, reliable
creator; the dashboard "Create chat" button is a manual fallback (it can
occasionally fail on Circle's side, so it isn't yet the sole route).
  - Automatically (primary) via Zapier when the student joins the cohort - separate
    zaps per audience: VIP & Private Plus members
    (https://zapier.com/editor/356003238/published, plus the "In Between" join
    variant), Legacy Upgrades (https://zapier.com/editor/356048959/published),
    VIP & Private Plus standard join (https://zapier.com/editor/370426888/published),
    and Boost & Go - its OWN zap with 4 paths (B&G / B&G Plus x Presentation),
    https://zapier.com/editor/341446766/published.
  - Manually (fallback) via the dashboard "Create chat" button in Students DB (and
    the "Needs setup" list), for backlog or anyone the zaps missed. It adds the
    coaches + student, posts the welcome message, records the URL, checks first that
    no chat already exists (safe to press), and now shows the outcome - if it fails
    it tells you why rather than doing nothing.

BOOST & GO IS A SEPARATE TRACK: Boost & Go students are tagged in Kit by their own
Boost & Go Sales zap (https://zapier.com/editor/262763852/published) - NOT the
Private Plus / VIP Sales Zap - and their chat is created by the Boost & Go chat zap
above, not the VIP/Private Plus zaps.

THE WELCOME MESSAGE: posted from Coralie. Content is set on the dashboard in
Settings > Integrations > Private chat setup - a separate template per tier
(Private Plus / VIP / Boost & Go) with placeholders like {first_name} and
{video_allowance}, including the call booking link(s) and the video-answer link.
If a tier has no template set, the chat won't be created (so the wrong message
can't go out).

WHERE IT'S TRACKED: the chat URL is stored on the student's record as their
private chat link (Student Lookup + Students DB). Some older zap-created chats
never wrote their URL back; the dashboard can recover those by scanning Circle.

NEEDS SETUP: any private-tier / Boost & Go student WITHOUT a chat link shows in
Students DB > "Needs setup". From there, press "Create chat" to create it, or
paste an existing chat's URL into the record (Edit) by hand. A new such student
landing without a chat also fires a Slack heads-up in #fulfillment-team for Coralie.

IF THEIR CIRCLE DMs ARE OFF: Circle won't create a group chat for someone with DMs
switched off. The dashboard flags them "Awaiting DMs" (they stay in Needs setup).
There is NO automatic retry - once they turn DMs back on, press "Create chat" again.

DUAL EMAILS: chat creation matches the student to their Circle member by email. If
their Circle email differs from their purchase / Kajabi email, the match can fail -
keep their Circle email / "Other emails" up to date if a chat won't create for
someone who's clearly on Circle.

EACH COHORT (private chat): the three zaps must fire on the new cohort's tag each
launch, and Coralie's welcome-message links should be checked. The dashboard side
needs no change.


# Boost & Go

WHAT IT IS: Boost & Go is an add-on package in two levels - "Boost & Go" and
"Boost & Go Plus". It is ALWAYS an upgrade bought by existing Academy members -
never new subscribers. It is a SEPARATE track from VIP / Private Plus.

WALKTHROUGH VIDEO: https://www.loom.com/share/2ed5759fb425430cb51e798545d416d0

WHAT EACH LEVEL GETS:
  - Boost & Go: a private chat + 5 video answers + 1 x 60-minute mock interview.
  - Boost & Go Plus: a private chat + 10 video answers + 2 x 30-minute coach calls
    + 1 x 60-minute mock interview.
(Chat = the Private chat process; calls = the Private tier calls process.)

THE ONE FIELD THAT DRIVES EVERYTHING - "Boost & Go": each student record has a
Boost & Go field. When set, the dashboard treats them as a paying B&G customer and
gives them the chat, the video allowance, and (for Plus) the calls. If it's blank
they get nothing B&G.
  - Paying customer = the field contains "B&G" or "B&G Plus" (sometimes with
    "- Presentation"), or "Upgraded".
  - NOT a customer = sales-pipeline states "Offer Due" / "Offer Made" / "Declined"
    (leads, not buyers - the dashboard ignores them).

HOW THEY GET TAGGED: on a Kajabi purchase the Boost & Go Sales zap
(https://zapier.com/editor/262763852/published - 4 paths: B&G / B&G Plus x
Presentation) tags them in Kit and posts to Slack. The dashboard reads their
Boost & Go field; if it didn't get set automatically, set it by hand
(Students DB > Edit).

DUAL-EMAIL GOTCHA: if they bought B&G under a different email than their Academy /
Circle account, the automatic link can miss them (the Stripe backfill can't match)
- set their Boost & Go field by hand on their record; that's what makes them
eligible.

WHAT THE DASHBOARD DOES ONCE TAGGED: shows them in Students DB > "Needs setup"
until their chat exists (created by the Boost & Go chat zap
https://zapier.com/editor/341446766/published or the "Create chat" button);
expects a video allowance of 5 (B&G) or 10 (B&G Plus), flagging missing/mismatch;
and shows the call allowance on their record automatically (both levels: a 60-min
mock; B&G Plus also: 2 x 30-min coach calls).

COMMON CONFUSIONS: plain B&G is NOT B&G Plus (both get the 60-min mock, but only
Plus also gets the 2 coach calls);
their Tier field is usually still "Academy" (B&G is a separate add-on - look at the
Boost & Go field, not Tier); pipeline states (Offer Due/Made/Declined) are leads,
not customers; B&G is a separate track from VIP/Private Plus (different sales zap,
chat zap, Kit tagging).

EACH COHORT (Boost & Go): the Sales zap tags buyers on purchase and the chat zap
creates chats - both per launch. The dashboard needs no change (it reads the
Boost & Go field). Main per-launch job: make sure new B&G buyers have their
Boost & Go field set (watch the dual-email cases).


# Boss badge & testimonials

WHAT IT IS: when a student lands their substantive job we celebrate it (the Boss
Badge) and turn it into social proof - they share their win in the community and
record a testimonial with Tessa. The aim is that nothing slips through.
OWNER: Coralie.
WALKTHROUGH VIDEO: https://www.loom.com/share/6ea141a491544316a249d0d0b5445c0a

1. IT STARTS WHEN A STUDENT TELLS US THEY GOT THE JOB: students tell us in all
sorts of ways (success form, a DM to a coach, an email, a message to Coralie).
The tidy path is the substantive success form, but the rule that stops wins
leaking: COACHES, if a student tells you they got their substantive job, pass it
to Coralie straight away (coaches don't all have dashboard access, so Coralie is
the one person who records every win).

2. CORALIE RECORDS IT ON THE DASHBOARD: Coralie opens the student and clicks
"Mark as Boss" - the single source of truth. It sets the board state, fires the
webhook that applies the Boss Badge tag on Circle + the Kit tag + bonus-content
access, AND enrols them in the testimonial chase (step 4). The success form is
meant to do the same automatically. IMPORTANT: tagging the Boss badge directly
on Circle does NOT update Kit or start the chase - always use the dashboard
button (this is why some recent job-getters were mis-tagged in Kit).

3. WHAT THE BOARD TRACKS - TWO INDEPENDENT GOALS: the baseline is EVERY Boss
(everyone with the badge). For each we'd like two things to happen, and they are
INDEPENDENT, not a sequence - a Boss can record a testimonial without ever
posting a win, or post a win and never do a testimonial:
  - SHARED A WIN: auto-detected from a post in the Share Your Wins Circle space
    (https://ayci-academy.circle.so/c/share-your-wins/).
  - RECORDED A TESTIMONIAL: booked auto from the Testimonial Call Calendly event
    (https://calendly.com/tessardavis/testimonial); recorded when the booked
    call happens.
Each Boss is in one of four states: did BOTH (the goal), win only, testimonial
only, or neither.

4. THE TESTIMONIAL CHASE (dashboard-driven): when someone is marked a Boss, the
dashboard sends a first DM + 3 follow-ups over ~30 days (offsets 0/7/16/30 days)
from Coralie's Circle account. It chases the TESTIMONIAL only (not the win).
This REPLACES the old Monday "Student Wins Tracker" (board 5095636561) -> Zapier
chain, which broke ~16 Jun 2026 (nobody was added after that, so recent
job-getters weren't chased). The dashboard decides WHEN; a Zapier catch-hook
still does the Circle send (DM from Coralie's account, as before). Only Bosses
marked from now on are chased; the ~450 backfilled/historical Bosses are never
auto-chased (handled by hand). THREE WAYS A CHASE STOPS: (a) automatically - the
moment they book, the call is recorded, or they reply (or all 4 have gone); (b)
STOP - Coralie ends this run by hand (a future new-Boss mark could re-enrol
them); (c) OPT OUT - a permanent "never auto-chase this person" flag that also
blocks Start and survives re-marking, reversible via Opt back in. OFF until
enabled in Settings > Integrations > Testimonial chase.

5. CORALIE'S BOARD - WINS & TESTIMONIALS (/wins): the left-sidebar page is home
for this. Summary cards across ALL Bosses (Bosses / shared a win / recorded a
testimonial / did both / no win yet / no testimonial yet + channel-wide win
totals); filters for the two goals independently (To chase / No win shared / No
testimonial / Did both / Opted out / All Bosses) + search; per-Boss row with a
win tick, testimonial status, chase state (chasing N/4, opted out, stop reason),
and controls (Start chase / Stop, Opt out / Opt back in). "To chase" is the
short actionable list (recent or actively-chased Bosses still needing a
testimonial), not the whole history. The same summary also shows as a widget on
the process page.

STATUS - THE CHASE IS LIVE: the "Student Wins Tracking - First Message" zap is
confirmed live - trigger is the dashboard Catch Hook (Webhooks by Zapier) ->
Circle Find Member -> Paths split on message_number -> one Send Direct Message
per message (1-4), from Coralie's Circle. The chase is enabled in Settings >
Integrations > Testimonial chase, and the 3 old Monday-triggered follow-up zaps
are OFF (no double-chasing). The backfill has been run (Boss badges set from the
Circle tag, recorded testimonials imported). STILL TO DO: (1) archive the now-
dormant Monday Student Wins Tracker (5095636561); (2) finish the Boss-TAGGING
consolidation - two of three routes now done. DONE: the worker zap "8b - Boss
tagging" subscribes to the boss_badge column (any dashboard change to boss_badge,
e.g. the Mark as Boss button, applies Circle + Kit + space access); and the
manual-Circle-tag zap "AYCI Academy Boss Option A - manually tagged" was
repointed (Circle new tagged member -> filter tag=Boss -> Webhooks POST to
mark-boss-by-email; old Kit/Monday steps removed), verified live, which closes
the direct-Circle-tagging -> Kit leak. REMAINING: a zap for the substantive
success form -> POST mark-boss-by-email (to do once Coralie has seen the
process).

KEY LINKS: wins channel = Share Your Wins
(https://ayci-academy.circle.so/c/share-your-wins/); testimonial booking =
https://calendly.com/tessardavis/testimonial.


# Toolkit (Prep Tools access & eligibility)

WHAT IT IS: which students can access each Prep Tool. Access is driven by
membership TIER (read from their Circle tags at login) plus a few standalone
paid add-ons. Tiers lowest to highest: Academy, Private Plus, VIP. (Last
reviewed 29 June 2026.)

WHO GETS EACH TOOL:
- Timeline Prepper: Admin, Private Plus, VIP, active Boost Plus.
- Prep Hub (dashboard + coach bots): Admin, Private Plus, VIP.
- Question Bank, full library: Admin, VIP, an active 14-day QB trial, or active Boost / Boost Plus.
- Question Bank, bonus (30 sets): anyone with the "30 Recent Sets" Dashboard upsell, or on the legacy bonus-grant list.
- Pre-Interview Toolkit: Admin, or anyone with the Toolkit add-on (independent of tier).

HOW TIERS ARE DETERMINED: from Circle tags, checked at login - a VIP tag means
VIP, a Private Plus tag means Private Plus, no premium tag means Academy (base).
Academy members do NOT get Timeline or Prep Hub (those are Private Plus / VIP
only). A student's tier only refreshes when they log in, so after a Circle
upgrade they may need to log out and back in.

ADD-ONS (independent of tier):
- Boost & Go: time-limited subscription. Boost Plus unlocks Timeline + Question Bank; plain Boost unlocks Question Bank only. Both expire.
- Pre-Interview Toolkit: standalone paid add-on, stamped at sign-in.
- Question Bank bonus pack: the 30-set upsell; the full library still requires VIP.

NOTES: Admins bypass all access gates. The Prep Hub has an internal beta flag
that can lock it to admins only; it is currently OFF (open to Private Plus / VIP).

TROUBLESHOOTING ACCESS (most "I paid but the tool won't let me in" reports):
- Upgraded in Circle but the tool shows the old tier / blocks access: tier only
  refreshes at login - log out and back in (re-reads Circle tags).
- Timeline shows the wrong cohort's live sessions: still on the previous cohort
  tag and/or missing the new one - in Circle add the current cohort tag, remove
  the old, then regenerate the timeline (cohort tags are read live, no re-login).
- No cohort sessions show at all: missing a cohort tag, or the tools-app login
  email doesn't match their Circle email - confirm the tag and that the emails match.
- "Private Plus / VIP only" despite being a paying member: tier tag genuinely
  missing or not refreshed since upgrade - check the Circle tag, then re-login.
KEY PRINCIPLE: tier is cached and refreshes only on login; cohort tags are read
live every time a timeline is generated. A re-login fixes tier issues;
regenerating the timeline fixes cohort issues.
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
