# Zapier Audit — Path to Monday Retirement

**Status:** in progress · 2026-06-02
**Total active zaps:** 80
**Owner:** Tessa Davis

## Purpose

The dashboard's Academy Members Mongo mirror is keeping read-side
parity with Monday. The remaining blocker for retiring the Monday
board is **write-side** — automations (Zapier zaps) that write into
Monday on Stripe / Tally / Calendly / Monday events.

This document is the migration plan. For each zap we capture:
- **Trigger** — what fires it
- **Key actions** — what it does (esp. writes to Monday)
- **Category** — see legend below
- **Priority** — see legend below
- **Migration plan** — what we do about it

## Legend

**Category:**
- 🔴 **WRITE_MONDAY** — adds or modifies rows on the Academy Members board. Needs migration.
- 🟡 **READ_MONDAY** — triggers on Monday events; downstream consumer. Can stay or be replicated in code later.
- 🟢 **NO_MONDAY** — doesn't touch Monday. Leave alone.
- 🟣 **MONDAY_INTERNAL** — Monday-internal flow (status updates within a single Monday board). Can stay or replicate.
- 🟤 **DIFFERENT_BOARD** — touches a Monday board OTHER than Academy Members (e.g. Private Videos, Cohort, Sales). Out of immediate scope.
- ❓ **UNKNOWN** — need Tessa to verify.

**Priority:**
- **P0** — blocking retirement, migrate now
- **P1** — should migrate before turning Monday off
- **P2** — leave running, replicate when Monday actually retires
- **P3** — unrelated to Academy Members, leave alone

## How to use this

Open each `❓ UNKNOWN` zap in Zapier, look at its Trigger step + Action steps. Update the row:
- Replace ❓ with the right category emoji
- Fill in trigger + key actions in plain English
- Set the priority
- Add migration notes if you want

You can edit this file directly in any text editor and push the changes; or paste updates back to me in the next session.

---

## Zaps

### 🔴 P0 — Tally → Monday signup writes (migrate FIRST)

These create or update rows on the Academy Members board when a student fills a Tally form. Until they're migrated, every new enrolment ends up on Monday first.

| # | Zap name | Trigger | Key actions | Notes |
|---|---|---|---|---|
| 1 | `[AYCI JUNE-26] - Signups to Monday Board (OD)` | **Kajabi: New Purchase** | 1. Lookup cohort start/end dates (Zapier Tables) <br> 2. Split by tier (Academy / Academy Private Plus / Academy VIP / Legacy Upgrade to Private Plus / Legacy Upgrade to Academy) <br> 3. **For new tiers: Create Item on Academy Members** <br> 4. **For legacy upgrades: Find by email + Update Item** <br> 5. Add email to trigger Tally onboarding form | **Migration:** dashboard endpoint `POST /api/students-db/intake-kajabi` that takes the Kajabi purchase payload, looks up academy_members by email (upsert), sets tier + cohort + dates, fires the Tally onboarding trigger downstream. |
| 2 | `[AYGI 2025] - Signups to Monday Board (OD/TRD)` | **Kajabi: New Purchase** | 1. Filter: continue only if offer is AYGI <br> 2. Split by tier (Gold / AYGI Pods / AYGI VIP / Legacy Upgrade to Pods / Legacy Upgrade to VIP) <br> 3. **For new tiers: Create Item on Academy Members** <br> 4. **For legacy upgrades: Find by email + Update Item** <br> 5. Add email to trigger Tally onboarding form | Same Kajabi-driven pattern as zap 1, just for AYGI programme. **Same migration plan**: the dashboard intake endpoint can branch on offer name (AYCI vs AYGI) and set tier accordingly. |
| 3 | `AYCI SEP 25 - Signups to Monday B...` | ❓ likely Kajabi (same family) | ❓ likely same pattern | Older cohort, still On — may be safe to turn off if no new SEP25 enrolments. |
| 4 | `[AYGI 2025] - Signups to Monday B...` (dupe?) | ❓ | ❓ | Possibly the row Tessa saw twice in the list. Same name as zap 2 — check if it's actually one zap or two. |
| 5 | `Onboarding Form Tally to Monday` | **Tally: New Submission** | 1. **monday.com: Create Item** on Academy Members | Two-step zap. Likely fires after the Kajabi zap above triggers the onboarding form (zap 1's last step). **Migration:** add this endpoint's payload handling to the same `/api/students-db/intake` endpoint — merge with the Kajabi intake on email. |
| 6 | `Onboarding Form (Higher Tiers) Tally to Monday` | **Tally: New Submission** | 1. **monday.com: Create Item** on Academy Members | Same 2-step pattern as zap 5. Higher-tier variant of the onboarding form (likely Private Plus / VIP). **Same migration plan**: merge into the dashboard intake endpoint. |
| 7 | `Non members Tally to Monday` | ❓ Tally (non-Academy signups?) | ❓ Create Monday row? | What board? |
| 8 | `Tally Form to Monday → Video sub...` | ❓ Tally video submission | ❓ Update Monday (private videos board?) | Probably Private Videos board, not Academy Members — verify. |
| 9 | `Grid Tally Form to Monday → Video...` | ❓ Tally (Grid product) | ❓ Update Monday | Likely different board (Grid). |
| 10 | `3. New Tally from submission → Up...` | ❓ | ❓ | "3." prefix suggests it's step 3 in a sequence. |

### 🔴 P0 — Stripe / Sales → Monday writes

| # | Zap name | Trigger | Key actions | Notes |
|---|---|---|---|---|
| 11 | `Boost & Go Sales - Arub` | ❓ Stripe purchase? | ❓ Update tier / create row | "Boost & Go" is a product tier. |
| 12 | `AYCI - Sales - Arub` | ❓ | ❓ | Implied by location "AYCI - Sales - Arub". |
| 13 | ~~`New Lead To Monday`~~ | **Out of scope** | — | Lives in Finchley Now folder. Trigger is Gmail (New Labeled Email), writes to the Finchley Now Monday board, not Academy Members. **Move to P3 — not part of this migration.** |

### 🟡 P1 — Interview / Calendly → Monday writes

| # | Zap name | Trigger | Key actions | Notes |
|---|---|---|---|---|
| 14 | `Mock interview - Tessa - update Monday` | ❓ Calendly booking? | ❓ Mark Mock Interview status on Monday | Other coach variants (Becky / Anoop / Charlotte) likely exist too. |
| 15 | `8g: 15 minute call booked - Charlotte` | ❓ Calendly | ❓ Update Monday | |
| 16 | `8g: 15 minute call booked - Tessa` | ❓ Calendly | ❓ Update Monday | |
| 17 | `AYCI 1:1 Call booking reminders - D...` | ❓ Calendly / Monday | ❓ Send reminder | Might not write to Monday. |
| 18 | `Private Plus + VIP 1:1 Calls - Becky...` | ❓ Calendly | ❓ Update Monday status | |
| 19 | `[TVA Test] VIP 1:1 Calls - Tessa - up...` | ❓ | ❓ | "TVA Test" — test zap, may be inactive. |
| 20 | `New Interview Date` | ❓ Calendly | ❓ Set Interview Date on Monday | Critical for Upcoming Interviews. |
| 21 | `4. Send Interview date form follow...` | ❓ | ❓ | |
| 22 | `5. When interview date is updated in...` | ❓ Monday | ❓ Trigger followup | 🟡 READ_MONDAY. |
| 23 | `6. When Interview status changes to...` | ❓ Monday | ❓ Followup | 🟡 READ_MONDAY. |
| 24 | `8. Collect interview Feedback via D...` | ❓ | ❓ | |
| 25 | `Request Grid interview dates` | ❓ | ❓ | Grid product. |
| 26 | `Interview date - New Grid Tally fro...` | ❓ Grid Tally | ❓ Set interview date | Grid product. |

### 🟣 P2 — Monday-internal status flows

These trigger on a Monday event and write to a Monday column. Once Monday is retired, these need replicating as backend logic.

| # | Zap name | Trigger | Key actions | Notes |
|---|---|---|---|---|
| 27 | `Milestone 1 - Monday board status u...` | ❓ Monday status | ❓ | |
| 28 | `Milestone 2 - Monday board status ...` | ❓ Monday status | ❓ | |
| 29 | `Milestone 3 - Monday board status ...` | ❓ Monday status | ❓ | |
| 30 | `Milestone 4 - Monday board status ...` | ❓ Monday status | ❓ | |
| 31 | `Milestone 5 - Monday board status ...` | ❓ Monday status | ❓ | |
| 32 | `When Reminder date changes in Mo...` | ❓ Monday date change | ❓ | |
| 33 | `0. When contact added to Monday, ...` | ❓ Monday item created | ❓ | Probably triggers downstream onboarding. |
| 34 | `1.1. When Client email is added in t...` | ❓ Monday email column updated | ❓ | |
| 35 | `1b. When button clicked in the cont...` | ❓ Monday button | ❓ | |
| 36 | `7. Deep Dive access - From Monday` | ❓ Monday | ❓ Grant access | |
| 37 | `7b. Speciality Space access - From...` | ❓ Monday | ❓ Grant access | |
| 38 | `9. Wins Updates` | ❓ Monday | ❓ Update something | |

### 🟢 Cohort lifecycle (probably no Academy Members writes)

These are cohort-rollout automations that DON'T necessarily touch the Academy Members board. Most likely Circle / Slack / email sends triggered by date.

| # | Zap name | Notes |
|---|---|---|
| 39 | `[AYCI JUNE-26] New Circle member...` | Likely Circle webhook → onboarding |
| 40 | `[AYCI JUNE-26] Cohort - Legacy (OD)` | |
| 41 | `[AYCI JUNE-26] Video Launch Last...` | |
| 42 | `[AYCI JUNE-26] Video Launch Day 1...` | |
| 43 | `[AYCI JUNE-26] Access to Previous...` | |
| 44 | `[AYCI JUNE-26] Live webinar bonus...` | |
| 45 | `[AYCI JUNE-26] Previous Cohort Ac...` | |
| 46 | `[AYCI JUNE-26] Private Chat for Leg...` | |
| 47 | `[AYCI JUNE-26] Private Chat for the...` (x2) | |
| 48 | `[AYCI JUNE-26] Mock interview - B...` | |
| 49 | `[AYCI JUNE-26] Mock interview - A...` | |
| 50 | `[AYCI JUNE-26] Mock interview - C...` | |
| 51 | `[AYCI JUNE-26] 1:1 Calls - Round Ro...` (x3) | |
| 52 | `[AYCI JUNE-26] AYCI testimonial cal...` | |
| 53 | `[AYCI] Private Chat for the Boost & Go` | |
| 54 | `[AYGI 2025] Private Chat for the VIP...` | |
| 55 | `[AYGI 2025] Shortlisted` | |
| 56 | `[AYGI 2025] Not Shortlisted` | |
| 57 | `[AYGI 2025] Private Chat for the VIP...` | |
| 58 | `[AYGI] On Circle (OD)` | |
| 59 | `[AYCI SEP-25] On Circle - not in spa...` | |
| 60 | `New SEP-25 Circle member (OD)` | |
| 61 | `AYCI SEP-25 Academy Mini-Webina...` | |
| 62 | `[AYGI 2025] On Circle` | |
| 63 | `Legacy Members Cohort Upgrade` | |
| 64 | `AYCI Waitlist Registrations - New W...` | |
| 65 | `AYCI Waitlist Registrations - Website` | |
| 66 | `AYCI Academy Boss Option A - man...` | |
| 67 | `AYCI testimonial cal...` | |
| 68 | `Student Wins Tracking - First Mess...` | |
| 69 | `8c. Substantive success form - Add...` | |
| 70 | `8b. Substantive success form - tags...` | |
| 71 | `Badge Allocation` | |
| 72 | `2. When Cohort Tag added in Circle...` | Reads Circle → may write Monday |
| 73 | `Send Circle group message with co...` | Probably Private Videos zap (already migrated) |
| 74 | `Grid Send Circle group message wit...` | Grid version of above |
| 75 | `Temp tag for Circle DM auto reply -...` | |
| 76 | `When Cloudconvert process is finis...` | Video processing |

### 🟤 P3 — Different products (Finchley Now / Paeds ST3)

Different brands / boards entirely. Out of scope for Academy Members retirement.

| # | Zap name | Product |
|---|---|---|
| 77 | `[Paeds ST3] Crash course - Purchas...` | Paeds ST3 |
| 78 | `[Paeds ST3] Crash course - Update...` | Paeds ST3 |
| 79 | `[Paeds ST3] Crash course - Sales to...` | Paeds ST3 |
| 80 | `Content alert` | Finchley Now |
| 81 | `FN Internal Event` | Finchley Now |
| 82 | `Finchley Now Event - External` | Finchley Now |

---

## Next steps

Once Tessa has filled in the ❓ rows for at least the P0 section, I'll:
1. Build the dashboard receiving endpoints for each migrated zap (intake, tier update, etc.).
2. Walk through re-pointing each zap in Zapier (same pattern as the Private Videos webhook switch).
3. Run new + old in parallel for a few days so we have a safety net.
4. Cut over once we've confirmed the dashboard is receiving everything.
