# AYCI Team Processes

Plain-English documentation of how each Academy process works - what's automated,
where it lives, and what the team needs to do. One section per process.

**Status key:** ✅ Live · 🔨 To build · ❓ Needs confirming

> Sister docs: `ZAPIER_AUDIT.md` (the technical zap inventory + migration), `TEAM_SOP.md` / `SUPPORT_TEAM_SOP.md` (day-to-day SOPs).

---

## Processes

1. [Bonus calls](#1-bonus-calls) - *draft for review*
2. [Private Tier calls](#2-private-tier-calls) - *draft for review*
3. Reminder statuses - _to be documented_
4. Boss badge / Win shared - _to be documented_
5. Testimonial status - _to be documented_
6. Interview reminders - _to be documented_
7. Refund status - _to be documented_

---

# 1. Bonus calls

**What it is:** Some students get a free 30-minute 1:1 coaching ("bonus") call depending on
when they signed up. Booked via a round-robin Calendly event shared by the bonus-call coaches
(currently **Anoop & Charlotte**). They should use it before the next cohort starts.

**Booking link (June '26):** https://calendly.com/d/cytf-7q4-nzy/ayci-bonus-call-june-26 - a fresh
round-robin event is created each cohort, so **update this link each launch** (here + in the Kit
booking-link automation).

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

## Who gets what

- **Private Plus** - 1 x 30-minute coach call.
- **VIP** - 2 x 30-minute calls with Tessa, 2 x 30-minute coach calls, and 1 x 60-minute mock interview (5 calls total).

## Who's eligible & how it's identified

When a student buys Private Plus or VIP, the **Sales Zap** tags them on Circle for the current cohort:

- `[AYCI MON-YY] Cohort - Private Plus` / `... Private Plus (4-Pay)`
- `[AYCI MON-YY] Cohort - VIP` / `... VIP (6-Pay)` / `... VIP (12-Pay)`

That tier flows through to the dashboard as the student's **tier**, which sets their call allowance.
Sales Zap (applies the Circle tier tags): https://zapier.com/editor/00000000-0000-c000-8000-000365773719/published

## How they get the booking links

- the onboarding email via the `[AYCI MON-YY] Onboarding (Megan)` Kit automation: https://app.kit.com/automations/1982218/edit
- an initial post from **Coralie** in their private chat, with the same links.

## The booking links & coaches

**Private Plus** - 30-min coach call (Becky / Charlotte / Anoop):
- https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min

**VIP** - five calls across three links:
- 2 x 30-min **with Tessa**: https://calendly.com/tessardavis/ayci-vip-30-min
- 2 x 30-min **coach calls** (Becky) - same link as Private Plus: https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min
- 1 x 60-min **mock interview** (Becky / Charlotte / Anoop): https://calendly.com/d/cttc-mx5-gz6/ayci-1-1-60-min

## Keeping coaching availability open

These links stay live all year, so availability has to be kept topped up:

- set coach availability on Calendly **well ahead** of each launch;
- availability should run **consistently throughout the year**; and
- do **regular checks** on each link: Private Plus 30-min, VIP 60-min mock, VIP 2 x 30-min coach, VIP 2 x 30-min Tessa.

## How bookings are tracked ✅ LIVE

When a student books any of these calls, the dashboard automatically:

- logs the call against their record - which call it was, the coach, and the date;
- shows allowance used vs. remaining (e.g. a VIP who's booked 1 of 2 Tessa calls); and
- posts a heads-up in `#fulfillment-team`.

Reschedules update the date automatically. If a student doesn't show up, the coach opens that
student's **Student Lookup** card and marks that call a **no-show**.

## Reminders to book

**Coralie** tracks who has interviews coming up and checks in with private-tier students to make sure
they know how to book and to remind them of their remaining allowance.

## Tracking the data

- Monthly summary of completed 1:1 calls - by **tier**, **call type**, and **coach**.
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
| Webhook recognises the 3 private-tier events | 🔨 |
| Log booking (kind + coach + date) to `private_calls` | 🔨 |
| Allowance used/remaining on the student record | 🔨 |
| No-show / attended marking per call | 🔨 |
| Reschedule + cancellation capture | 🔨 |
| Backfill past private-tier bookings | 🔨 |
| Monthly summary by tier / call type / coach | 🔨 |
