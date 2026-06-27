# AYCI Team Processes

Plain-English documentation of how each Academy process works - what's automated,
where it lives, and what the team needs to do. One section per process.

**Status key:** ✅ Live · 🔨 To build · ❓ Needs confirming

> Sister docs: `ZAPIER_AUDIT.md` (the technical zap inventory + migration), `TEAM_SOP.md` / `SUPPORT_TEAM_SOP.md` (day-to-day SOPs).

---

## Processes

1. [Bonus calls](#1-bonus-calls) - *draft for review*
2. [Private Tier calls](#2-private-tier-calls) - *draft for review*
3. [Private chat](#3-private-chat) - *draft for review*
4. [Boost & Go](#4-boost--go) - *draft for review*
5. Reminder statuses - _to be documented_
6. Boss badge / Win shared - _to be documented_
7. Testimonial status - _to be documented_
8. Interview reminders - _to be documented_
9. Refund status - _to be documented_

---

# 1. Bonus calls

**What it is:** Some students get a free 30-minute 1:1 coaching ("bonus") call depending on
when they signed up. Booked via a round-robin Calendly event shared by the bonus-call coaches
(currently **Anoop & Charlotte**). They should use it before the next cohort starts.

**Booking link (June '26):** https://calendly.com/d/cytf-7q4-nzy/ayci-bonus-call-june-26 - a fresh
round-robin event is created each cohort, so **update this link each launch** (here + in the Kit
booking-link automation).

**Walkthrough video:** https://www.loom.com/share/00eb3199d5b14c9abcc701edc101441b

## Who's eligible?

A student is eligible if they hold **any** of these ConvertKit tags (shown for the JUN-26 cohort;
the prefix changes each cohort):

| Eligibility tag | Who gets it | Applied by |
|---|---|---|
| `[AYCI JUN-26] Purchase - Live webinar` | Live-webinar signups (the majority) | **Kit/Kajabi at purchase** (not the dashboard) |
| `[AYCI JUN-26] Legacy Video Launch Day 1 Upgrade` | Legacy upgrades on Day 1 of launch | **Kit/Kajabi at purchase** |
| `[AYCI JUN-26] Legacy Video Launch Last Day Upgrade` | Legacy upgrades on the final day | **Kit/Kajabi at purchase** |
| `[AYCI JUN-26] Cart Close Signup` | New signups on cart-close day | **Kit/Kajabi at purchase** |
| `[AYCI JUN-26] Ad Hoc Bonus Call` | Ad-hoc allocations (Arub/Tessa, to encourage signup) | **The dashboard**, when a team member marks them eligible |

So eligibility comes from two places: **automatic** (the purchase tags, applied by the existing
signup automations) and **manual/ad-hoc** (a team member marks the student eligible in the dashboard,
which applies the `Ad Hoc Bonus Call` tag).

### Where the eligibility tags are applied

The four purchase tags are applied at purchase by **Zapier zaps** (Kajabi purchase → Kit tag) -
**do not delete these; the whole bonus-call flow depends on them.** The Ad Hoc tag is applied by the
dashboard, so it has no zap.

| Tag | Applied by | Link |
|---|---|---|
| `Purchase - Live webinar` | Zapier (Kajabi purchase) | https://zapier.com/editor/356253725/published |
| `Legacy Video Launch Day 1 Upgrade` + `… Last Day Upgrade` | Zapier zap "Legacy Video Launch Upgrade Bonus Kit Tags" | https://zapier.com/editor/365778218/published |
| `Cart Close Signup` | Zapier zap "Cart Close Bonus Call - Kit tag" | https://zapier.com/editor/365778815 |
| `Ad Hoc Bonus Call` | **The dashboard** (Mark eligible button) | _no zap_ |

## How a team member marks someone eligible (ad-hoc) 🔨

**Arub** is the person who marks ad-hoc students eligible. On the student's record there's a
**"Mark eligible for bonus call"** action. Clicking it tags the student in ConvertKit with
`Ad Hoc Bonus Call`. The Kit automation tied to that tag then emails them the booking link.
> ❓ **Confirm:** is there a Kit automation that sends the booking link when `Ad Hoc Bonus Call` is
> applied? Your doc lists send-automations for the other 4 tags but not Ad Hoc - if it doesn't exist,
> it needs creating in Kit (the dashboard applies the tag; Kit sends the email).

## How they get the booking link & reminders

- On becoming eligible, Kit sends **one email with the booking link** (a separate Kit automation per
  eligibility tag; the link is updated each launch).
- Everyone with `Purchase - Live webinar` also enters the **`Bonus Call Reminders (Megan)`** Kit
  sequence: **4 reminders** - 5 days after tagging, then +7, +7, +3 days.
- **They're removed from the reminders the moment they book** - because booking applies the
  `1:1 Call Booked` tag, which is the sequence's exclusion tag.

## What happens when a student books ✅ LIVE

The bonus-call Calendly event posts straight to the dashboard (no Zapier). The dashboard then:

1. **Tags them in ConvertKit** with `[AYCI <cohort>] 1:1 Call Booked` → stops the reminder emails.
   *(The cohort tag is found automatically - newest first - so it just works each cohort.)*
2. **Records the booking** on their student record: the coach, and 🔨 the **date** of the call.
3. **Posts to `#fulfillment-team`** in Slack: who booked, with which coach, and when.

> ✅ **Verified 2026-06-26** with a live test booking: the `1:1 Call Booked` tag was applied within
> seconds, and the Slack alert fired. Works for both Anoop and Charlotte from one connection.
> **Switched on via** Settings → Integrations → **Connect Calendly**.

## Booking under a different email (dual-email matching)

A student sometimes books under an email that isn't their main record email.

- The dashboard **auto-matches** across their **primary email, Circle email, and an "Other emails"
  field** on their record. Keeping *Other emails* up to date means most alternates just match. ✅
- If they book under a **brand-new** email we've never seen, the booking is flagged
  **"not found in dashboard"** (in the Slack alert). 🔨 An **Unmatched bonus-call bookings** list will
  let a team member **link the booking to the right student** in one click (which also saves that email
  to *Other emails* for next time).
- 🔨 **Duplicate-subscriber flag:** if the booking email and the student's known email are **both
  separate ConvertKit subscribers**, the dashboard flags a **"possible duplicate ConvertKit subscriber -
  consolidate in Kit"** warning. The team then merges them in Kit so the person has **one** clean
  subscriber and doesn't get spammed. *(The dashboard detects and tells you; it does not silently
  re-tag, which would just mask the duplicate.)*

## Tracking fulfilment

- **Booked:** logged automatically (coach + date). ✅ / 🔨(date)
- 🔨 **No-show:** if a student doesn't attend, the coach can mark **No-show** on the booking.
- 🔨 **Rescheduled:** if a student reschedules in Calendly, the dashboard records it automatically with
  the **old → new** dates (Calendly tells us about reschedules).
- **Where the team sees all this:** on the **student record** - the "Calendly Calls" card already lists
  the booking with its date and coach. No-show and reschedule will show there too, as the call's status.
  Status flow: Eligible → Booked → Attended / No-show / Rescheduled / Cancelled. (No separate Bonus Calls
  view - it lives on the record.)

## Each cohort - what changes, and what doesn't

**The team still sets up (in Kit / Calendly), each launch:**
- New cohort tags (`[AYCI <new cohort>] …`) and their send-automations, with the **new booking link**.
- A **new round-robin Calendly event** (so calls can't silently roll over). Confirm dates with Arub;
  set coach availability from Onboarding Week to the next Onboarding Week. Usually 50-70 calls/launch -
  if Anoop & Charlotte can't cover it, agree extra coaches with Tessa.

**The dashboard adapts automatically - no per-cohort change needed:**
- It finds the **current cohort's** tags by pattern (eligibility tags + `1:1 Call Booked`).
- It matches the Calendly event by the words **"bonus call"** in the event name.

## New-cohort setup (the per-launch plan)

The team sets up the Kit + Calendly side; the **dashboard needs no changes** (it finds the new cohort's
tags by suffix and matches the Calendly event by the words "bonus call").

1. **Kit tags [Arub]** - create the cohort's tags: `Purchase - Live webinar`, `Legacy Video Launch Day 1 Upgrade`, `Legacy Video Launch Last Day Upgrade`, `Cart Close Signup`, and `Ad Hoc Bonus Call`.
2. **Booking-link automation [Tessa/Megan]** - the Kit automation that emails the booking link, ideally **one** automation with all five tags as entry points. Update the booking link + the cohort name in the email.
3. **Reminders [Megan]** - ensure the "Bonus Call Reminders" sequence has **all five** tags as entry points (not just Live Webinar).
4. **Calendly [Arub/Megan]** - fresh round-robin "AYCI Bonus call - &lt;cohort&gt;" event with coach availability (Onboarding Week → before the next one); confirm coaches + dates with Arub. **Set the event's booking window so it only accepts bookings until the next cohort starts** (date-range / scheduling limit) - so calls can't roll over.
5. **Dashboard** - nothing to change. Keep Calendly connected (Settings → Integrations).
6. **End of cohort** - read the snapshot below on the Cohort Dashboard / Processes board; share with Tessa then coaches.

## End-of-cohort summary ✅

A live snapshot of **eligible / booked / attended / no-show / rescheduled** shows at the top of this
process and on the **Cohort Dashboard** (`/api/bonus-call/summary`). Share with Tessa, then the coaches.

## Open tasks & to-clarify

- **[Tessa / Arub - Kit]** Ad-hoc booking link: the dashboard tags ad-hoc students `Ad Hoc Bonus Call`, but no Kit automation yet emails them the booking link off that tag. Set one up (or add the tag to the consolidated automation below).
- **[Tessa - decision]** Consolidate the four booking-link Kit automations into **one** with all four purchase tags **+ the Ad Hoc tag** as entry points (one booking link + one email to maintain).
- **[Kit - fix]** The four booking-link emails currently show the **wrong cohort name** - fix before next send.
- **[Megan - Kit]** Booking reminders currently only include Live Webinar signups - add Legacy Day 1, Legacy Last Day, Cart Close, and Ad Hoc as entry points.
- **[Arub]** Add the `Ad Hoc Bonus Call` tag to the new-cohort Kit-tag checklist.
- **[Megan]** Agree a deadline for coach bonus-call availability ahead of each cohort, and a frequency for checking the booking calendar.

---

### Behind the scenes (for whoever maintains the dashboard)

- **Inbound:** `POST /api/calendly/webhook` (signed) → `calendly_webhook.handle_invitee_created`.
  Matches `scheduled_event.name` containing `"bonus call"`. Deduped by invitee URI.
- **Register / status:** `POST /api/admin/calendly/register-webhook`, `GET /api/admin/calendly/status`
  (the **Connect Calendly** card). Backfill: `POST /api/admin/calendly/backfill-bonus-tags` (**Tag past
  bookings** button).
- **Kit write:** `connectors.convertkit_add_tag_to_subscriber(email, tag_id)`. Cohort tags resolved by
  `connectors._resolve_ayci_cohort_tags(suffix)` (newest `[AYCI MON-YY] <suffix>` first).
- **Record field:** `bonus_call` on `academy_members` (pinned in `dashboard_edited_fields`).
  🔨 add `bonus_call_date`, `bonus_call_coach`, `bonus_call_status` (no-show etc.), reschedule history.
- **Match:** `email` / `circle_email` / `other_emails` combined-identity lookup.
- **Tag suffixes (stable across cohorts):** eligibility = `Purchase - Live webinar`,
  `Legacy Video Launch Day 1 Upgrade`, `Legacy Video Launch Last Day Upgrade`, `Cart Close Signup`,
  `Ad Hoc Bonus Call`; booked = `1:1 Call Booked`.

### Build status
| Piece | Status |
|---|---|
| Booking → `1:1 Call Booked` tag + Slack | ✅ Live (verified 2026-06-26) |
| Record coach on booking | ✅ Live |
| Connect Calendly + Backfill past bookings | ✅ Live |
| Auto-match across primary/Circle/Other emails | ✅ Live |
| Record booking **date** + coach | ✅ Live |
| Eligibility flag (4 purchase tags + ad-hoc) | ✅ Live |
| "Mark eligible (ad-hoc)" button (Lookup + Students DB) | ✅ Live |
| No-show / attended / done - settable by hand | ✅ Live |
| Reschedule + cancellation capture (old → new) | ✅ Live |
| Booking status/date/coach shown on the student record | ✅ Live |
| Unmatched bookings → Link to student | ✅ Live |
| Duplicate-ConvertKit-subscriber flag (in Slack alert) | ✅ Live |
| Match-all-emails in Student Lookup (the Henry case) | 🔨 |
| End-of-cohort summary | 🔨 |
| "Ask about the processes" Claude chat (needs API key) | 🔨 |

---

# 2. Private Tier calls

Students on the **Private Plus** and **VIP** tiers get a set of free 1:1 coaching calls as part of
their package. They can use them **any time** - there is no expiry (people were previously told 12
months, but they keep their allowance for as long as they need).

**Walkthrough video:** https://www.loom.com/share/9d9aa53be0d648159fe25bbf809d268e

## Who gets what

- **Private Plus** - 1 x 30-minute coach call.
- **VIP** - 2 x 30-minute calls with Tessa, 2 x 30-minute coach calls, and 1 x 60-minute mock interview (5 calls total).
- **Boost & Go Plus** - 2 x 30-minute coach calls (same 30-min coach link). Plain Boost & Go gets a chat but no calls.

**Boost & Go Plus students are usually existing Academy members** who upgrade. Once tagged **B&G Plus**
on the dashboard (their Boost & Go field), their call allowance shows automatically and their private
chat is created by the Boost & Go chat zap.

## Who's eligible & how it's identified

When a student buys Private Plus or VIP, the **Sales Zap** tags them in **ConvertKit** for the current cohort:

- `[AYCI MON-YY] Cohort - Private Plus` / `... Private Plus (4-Pay)`
- `[AYCI MON-YY] Cohort - VIP` / `... VIP (6-Pay)` / `... VIP (12-Pay)`

That tier flows through to the dashboard as the student's **tier**, which sets their call allowance.
Sales Zap (applies these Kit tier tags): https://zapier.com/editor/365773719/published

## How they get the booking links

- the onboarding email via the `[AYCI MON-YY] Onboarding (Megan)` Kit automation: https://app.kit.com/automations/1982218/edit
- an initial post from **Coralie** in their private chat, with the same links.

## The booking links & coaches

**Private Plus** - 30-min coach call (Becky / Charlotte / Anoop):
- https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min

**VIP** - five calls across three links:
- 2 x 30-min **with Tessa**: https://calendly.com/tessardavis/ayci-vip-30-min
- 2 x 30-min **coach calls** (Becky, Anoop, or Charlotte) - same link as Private Plus: https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min
- 1 x 60-min **mock interview** (Becky / Charlotte / Anoop): https://calendly.com/d/cttc-mx5-gz6/ayci-1-1-60-min

## Keeping coaching availability open

These links stay live all year, so availability has to be kept topped up:

- coach availability needs to be set up on Calendly **each month**;
- availability should run **consistently throughout the year**; and
- do **regular checks** on each link: Private Plus 30-min, VIP 60-min mock, VIP 2 x 30-min coach, VIP 2 x 30-min Tessa.

## How bookings are tracked ✅ LIVE

When a student books any of these calls, the dashboard automatically:

- logs the call against their record - which call it was, the coach, and the date;
- shows allowance used vs. remaining (e.g. a VIP who's booked 1 of 2 Tessa calls); and
- posts a heads-up in `#fulfillment-team`.

Reschedules update the date automatically. If a student doesn't show up, the coach opens that
student's **Student Lookup** card and marks that call a **no-show**.

On the Student Lookup card (or **Students DB → Edit**) the team can also **log a call that wasn't booked
through Calendly** ("Log a call" - counts as one of their eligible calls) and **grant extra allowance**
above the tier default with the **+ / -** buttons next to a call type (e.g. give a VIP a 3rd coach call).
The override is stored per student (`private_call_allowance`) and pinned against the sync.

## Reminders to book

**Coralie** tracks who has interviews coming up and checks in with private-tier students to make sure
they know how to book and to remind them of their remaining allowance.

## Tracking the data

On the **1st of each month** the dashboard automatically posts the previous month's summary to the
**#private-tiers** Slack channel - 1:1 calls held, broken down by **tier**, **call type** and **coach**
(plus no-shows / cancellations). No one compiles it by hand.

- **Monthly Slack summary (#private-tiers, automatic on the 1st):** 1:1 calls held, by tier, call type, coach.
- Summary of how many private-tier students had interviews, and how much of their allowance they used.

## Each cohort - what changes, and what doesn't

The dashboard needs **no change** per cohort - it reads each student's tier and matches the Calendly
events by name, so the same booking links carry over. Per-launch jobs: confirm the Sales Zap is tagging
the new cohort's tier tags, update the cohort prefix in the onboarding email + Coralie's private-chat
post, and check coach availability is set on all the booking links.

---

### Behind the scenes (for whoever maintains the dashboard)

- **Inbound:** `POST /api/calendly/webhook` (signed) → `calendly_webhook.handle_invitee_created`.
  Private-tier events are matched by `scheduled_event.name` and classified into three kinds:
  `coach_30` (`ayci-1-1-30-min`), `tessa_30` (`ayci-vip-30-min`), `mock_60` (`ayci-1-1-60-min`).
- **Record field:** `private_calls` array on `academy_members` (pinned in `dashboard_edited_fields`),
  each entry `{kind, coach, date, status, invitee_uri, event_name}`. Allowance derived from `tier`.
- **No Kit tag on booking** (private-tier reminders are manual, via Coralie) - unlike bonus calls.
- **Match:** `email` / `circle_email` / `other_emails` combined-identity lookup.

### Build status
| Piece | Status |
|---|---|
| Document the process (board + this file + Q&A) | ✅ Live |
| Webhook recognises the 3 private-tier events | ✅ Live |
| Log booking (kind + coach + date) to `private_calls` | ✅ Live |
| Allowance used/remaining on the student record | ✅ Live |
| No-show / attended marking per call | ✅ Live |
| Reschedule + cancellation capture | ✅ Live |
| Backfill past private-tier bookings | ✅ Live |
| Summary by tier / call type / coach | ✅ Live |

---

# 3. Private chat

Every **Private Plus**, **VIP** and active **Boost & Go** student gets a **private group chat on Circle**
with the coaching team - where they ask questions, get video feedback, and find the links they need.

## Who's in the chat

The student + the coaches: **Tessa, Arub, Coralie, Becky**. (Oksana is no longer added to new chats;
older chats keep whoever was in them - you can't remove people from a Circle group DM.) The coach list
is editable in **Settings → Integrations → Private chat setup**.

## How a chat gets created

Two paths. **The Zapier zaps are the primary, reliable creator**; the dashboard "Create chat" button is a
manual fallback (it can occasionally fail on Circle's side, so it's not yet the sole route).

- **Automatically (primary)** via Zapier when the student joins the cohort - the dependable path.
  Separate zaps cover the audiences:
  - VIP & Private Plus members (+ "In Between" join variant): https://zapier.com/editor/356003238/published
  - Legacy Upgrades: https://zapier.com/editor/356048959/published
  - VIP & Private Plus (standard join): https://zapier.com/editor/370426888/published
  - **Boost & Go** (its own zap - 4 paths: B&G / B&G Plus × Presentation): https://zapier.com/editor/341446766/published
- **Manually (fallback)** via the dashboard - the **"Create chat"** button in Students DB (and the "Needs
  setup" list), for backlog or anyone the zaps missed. It adds the coaches + student, posts the welcome
  message, records the URL, and checks first that no chat already exists (safe to press). It now shows the
  outcome - if it fails it tells you why (Circle DMs off, a Circle hiccup, etc.) rather than doing nothing.

**Boost & Go is a separate track:** B&G students are tagged in Kit by their own Boost & Go Sales zap
(https://zapier.com/editor/262763852/published) - not the Private Plus / VIP Sales Zap - and their chat
is created by the Boost & Go chat zap above, not the VIP/Private Plus zaps.

## The welcome message

Posted from **Coralie**. Content is set on the dashboard in **Settings → Integrations → Private chat
setup** - a separate template per tier (Private Plus / VIP / Boost & Go) with placeholders like
`{first_name}` and `{video_allowance}`, including the call booking link(s) and the video-answer link.
If a tier has no template set, the chat won't be created (so the wrong message can't go out).

## Where the chat is tracked

The chat URL is stored on the student's record as their **private chat link** (Student Lookup + Students
DB). Some older zap-created chats never wrote their URL back; the dashboard can recover those by scanning
Circle and recording the link.

## Needs setup

Any private-tier / Boost & Go student **without** a chat link shows in **Students DB → "Needs setup"**:
- press **"Create chat"** to create it; or
- paste an existing chat's URL into the record (Edit) by hand.

A new private-tier / Boost & Go student who lands without a chat also fires a **Slack heads-up in
#fulfillment-team for Coralie** (see Private Tier calls / the needs-setup alert).

## If their Circle DMs are off

Circle won't create a group chat for someone with DMs switched off. The dashboard flags them
`Awaiting DMs` (they stay in "Needs setup"). **No automatic retry** - once they turn DMs back on, press
**"Create chat"** again.

## Heads-up: dual emails

Chat creation matches the student to their Circle member by email. If their **Circle email differs from
their purchase / Kajabi email**, the match can fail - keep their **Circle email / "Other emails"** up to
date if a chat won't create for someone who's clearly on Circle.

## Each cohort

The three zaps must fire on the **new cohort's tag** each launch (and Coralie's welcome-message links
should be checked). The dashboard side needs no change.

### Behind the scenes (for whoever maintains the dashboard)

- **Create:** `POST /api/students-db/{id}/create-private-chat` → `private_chat_setup.create_for_student`
  (background). Adds coaches + student via the Circle Headless API, posts the welcome message, stores
  `private_chat_url` + `private_chat_circle_uuid` (pinned).
- **Config:** coach list + per-tier `welcome_templates` + sender live in `app_settings` id `private_chat`
  (Settings → Integrations → Private chat setup; `POST /api/students-db/private-chat/config`).
- **DMs-off:** Circle error is classified in `private_chat_setup.py`; sets `private_chat_status="Awaiting DMs"`.
- **Recover URLs:** `GET /api/students-db/private-chat/link-existing` scans Circle for chats with no URL recorded.
- **Needs-setup alert:** `routes/students_db.private_chat_setup_alerts` (15-min sweep) → #fulfillment-team.
- **Zaps 46/47/53** still create chats in parallel; candidates for retirement once dashboard auto-create
  (`PRIVATE_CHAT_AUTOCREATE_ENABLED`) is switched on and proven.

---

# 4. Boost & Go

**Boost & Go** is an add-on package in two levels: **Boost & Go** and **Boost & Go Plus**. Usually bought
by existing Academy members (an upgrade), plus new buyers. This is the single source of truth for what
each level gets and how the dashboard handles them.

## What each level gets

- **Boost & Go** - a private chat + **5 video answers**. **No 1:1 calls.**
- **Boost & Go Plus** - a private chat + **10 video answers** + **2 x 30-minute coach calls**.

(Chat → see #3 Private chat; calls → see #2 Private Tier calls.)

## The one field that drives everything: "Boost & Go"

Each record has a **Boost & Go** field. When set, the dashboard treats them as a paying B&G customer
(chat + video allowance + Plus calls). If blank, they get nothing B&G.

- **Paying customer** - the field contains `B&G` or `B&G Plus` (sometimes "- Presentation"), or `Upgraded`.
- **NOT a customer** - sales-pipeline states `Offer Due` / `Offer Made` / `Declined` (leads, not buyers - ignored).

## How they get tagged

- On a Kajabi purchase, the **Boost & Go Sales zap** (https://zapier.com/editor/262763852/published - 4 paths:
  B&G / B&G Plus × Presentation) tags them in **Kit** and posts to Slack.
- The dashboard reads their **Boost & Go field**. If it didn't get set automatically, set it by hand
  (Students DB → Edit).

**⚠️ Dual-email gotcha:** if they bought B&G under a different email than their Academy / Circle account,
the automatic link can miss them (Stripe backfill can't match) - set the **Boost & Go field by hand** on
their record. That's what makes them eligible.

## What the dashboard does once they're tagged

- **Private chat** - they show in Students DB → "Needs setup" until their chat exists; created by the
  Boost & Go chat zap (https://zapier.com/editor/341446766/published) or the "Create chat" button.
- **Video allowance** - expected **5** (B&G) / **10** (B&G Plus); "Needs setup" flags missing/mismatch.
- **Calls (Plus only)** - 2 x 30-min coach calls show on their record automatically; plain B&G shows none.

## Common confusions

- **Plain B&G ≠ B&G Plus** - only Plus gets the 2 coach calls.
- **Their Tier is usually still "Academy"** - B&G is a separate add-on; look at the Boost & Go field, not Tier.
- **Pipeline states aren't customers** - Offer Due/Made/Declined = a lead, gets nothing.
- **Separate track from VIP/Private Plus** - different sales zap, chat zap, and Kit tagging.

## Each cohort

The Sales zap tags buyers on purchase; the chat zap creates chats - both per launch. The dashboard reads
the Boost & Go field and applies the right video + (Plus) call allowance automatically. Main per-launch
job: make sure new B&G buyers have their **Boost & Go field set** (watch the dual-email cases).
