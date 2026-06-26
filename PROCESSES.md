# AYCI Team Processes

Plain-English documentation of how each Academy process works - what's automated,
where it lives, and what the team needs to do. One section per process.

**Status key:** ✅ Live · 🔨 To build · ❓ Needs confirming

> Sister docs: `ZAPIER_AUDIT.md` (the technical zap inventory + migration), `TEAM_SOP.md` / `SUPPORT_TEAM_SOP.md` (day-to-day SOPs).

---

## Processes

1. [Bonus calls](#1-bonus-calls) - *draft for review*
2. 1:1 call allowances - _to be documented_
3. Mock interview allowances - _to be documented_
4. Reminder statuses - _to be documented_
5. Boss badge / Win shared - _to be documented_
6. Testimonial status - _to be documented_
7. Interview reminders - _to be documented_
8. Refund status - _to be documented_

---

# 1. Bonus calls

**What it is:** Some students get a free 30-minute 1:1 coaching ("bonus") call depending on
when they signed up. Booked via a round-robin Calendly event shared by the bonus-call coaches
(currently **Anoop & Charlotte**). They should use it before the next cohort starts.

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

## How a team member marks someone eligible (ad-hoc) 🔨

On the student's record there's a **"Mark eligible for bonus call"** action. Clicking it tags the
student in ConvertKit with `Ad Hoc Bonus Call`. The Kit automation tied to that tag then emails them
the booking link.
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

## End-of-cohort summary 🔨

A summary of: eligible, booked, no-showed, rescheduled, and rolled-over - shared with Tessa, then with
the coaches. *(A simple cohort summary/report will produce these numbers.)*

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
| Record booking **date** | 🔨 |
| Eligibility flag (read 4 purchase tags + ad-hoc) | 🔨 |
| "Mark eligible (ad-hoc)" button → `Ad Hoc Bonus Call` tag | 🔨 |
| No-show tracking | 🔨 |
| Reschedule capture (old → new) | 🔨 |
| Unmatched bookings → Link to student | 🔨 |
| Duplicate-ConvertKit-subscriber flag | 🔨 |
| No-show / reschedule shown on the student record | 🔨 |
| End-of-cohort summary | 🔨 |
