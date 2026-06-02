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

## Constraint: Grid (AYGI) course runs from Jan 2027

Grid (AYGI) zaps can stay running for now — the next Grid cohort doesn't kick off until **Jan 2027**, so there's a ~7-month window to migrate them. Don't treat any Grid zap as an immediate-action item. Tag them P2 at most.

Grid zaps in this doc: 9 (Video submission), 25 (Request interview dates), 26 (Interview date Tally), 54 (AYGI Private Chat VIP), 55/56 (Shortlisted/Not), 57/62 (On Circle), 58 (Signups), 74 (Send Circle group message).

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
| 1 | `[AYCI JUNE-26] - Signups to Monday Board (OD)` | **Kajabi: New Purchase** | 1. Zapier Tables: Find Records (cohort lookup table) <br> 2. Filter (continue only for AYCI JUNE-26 offers) <br> 3. Formatter: Cohort Start Date <br> 4. Formatter: Cohort End Date <br> 5. Paths split by tier: Academy / Academy Private Plus / Academy VIP / Legacy Upgrade to Private Plus / Legacy Upgrade to Academy <br> 6. **New tier paths**: Create Item → Delay → Add email to trigger Tally onboarding form <br> 7. **Legacy upgrade paths**: Get Items by Column Value → **Update Item** | **Migration:** dashboard endpoint `POST /api/students-db/intake-kajabi` that takes the Kajabi purchase payload, looks up academy_members by email (upsert), sets tier + cohort + dates, fires the Tally onboarding trigger downstream. |
| 2 | `[AYGI 2025] - Signups to Monday Board (OD/TRD)` | **Kajabi: New Purchase** | 1. Filter: continue only if offer is AYGI <br> 2. Split by tier (Gold / AYGI Pods / AYGI VIP / Legacy Upgrade to Pods / Legacy Upgrade to VIP) <br> 3. **For new tiers: Create Item on Academy Members** <br> 4. **For legacy upgrades: Find by email + Update Item** <br> 5. Add email to trigger Tally onboarding form | Same Kajabi-driven pattern as zap 1, just for AYGI programme. **Same migration plan**: the dashboard intake endpoint can branch on offer name (AYCI vs AYGI) and set tier accordingly. |
| 3 | `AYCI SEP 25 - Signups to Monday Board (OD)` (v57) | **Kajabi: New Purchase** | Same shape as zap 1 — Zapier Tables (cohort), Filter, Formatters (Start/End Date), Paths split by tier (Academy / Academy Private Plus / Academy VIP / Legacy Upgrades) → Create Item / Update Item + Delay + Create Post in Circle | SEP-25 cohort signup zap. v57 — most-iterated zap in the doc. **Safe to turn off** if no new SEP-25 enrolments are happening (cohort already running). |
| 4 | `[AYGI 2025] - Signups to Monday Board (OD/TRD)` (v3) — confirmed same as zap 58 | (Re-confirmed in screenshots, not a duplicate.) | Same as 58. | Same as zap 58 / 2. Only one zap, not two. |
| 5 | `Onboarding Form Tally to Monday` | **Tally: New Submission** | 1. **monday.com: Create Item** on Academy Members | Two-step zap. Likely fires after the Kajabi zap above triggers the onboarding form (zap 1's last step). **Migration:** add this endpoint's payload handling to the same `/api/students-db/intake` endpoint — merge with the Kajabi intake on email. |
| 6 | `Onboarding Form (Higher Tiers) Tally to Monday` | **Tally: New Submission** | 1. **monday.com: Create Item** on Academy Members | Same 2-step pattern as zap 5. Higher-tier variant of the onboarding form (likely Private Plus / VIP). **Same migration plan**: merge into the dashboard intake endpoint. |
| 7 | `Non members Tally to Monday` (v1) | **Tally: New Submission** | 1. **monday.com: Create Item** | 2-step zap. Same shape as zaps 5 and 6 — Tally submission creates a Monday row. "Non members" suggests it's for people who aren't AYCI students yet (lead capture?). Need to know which Monday board — could be Academy Members or a separate Leads board. |
| 8 | ~~`Tally Form to Monday → Video submission`~~ ✅ **OFF** (confirmed 2026-06-02) | **Tally: New Submission** | Paths (MOV / Not MOV) → monday Create Item Link → CloudConvert / monday Create Item. | Was the Private Videos intake zap. Already replaced by the dashboard's `/api/private-videos/tally-webhook`. |
| 9 | `Grid Tally Form to Monday → Video submission` (v7) | **Tally: New Submission** | monday Create Item | 2-step zap. Grid (AYGI) variant of zap 8 — much simpler (no MOV path). Touches a different Monday board (Grid Private Videos). |
| 10 | `3. New Tally from submission → Update Monday Contact` (Has Draft, v19, **ACTIVE**) | **Tally: New Submission** | 1. AI by Zapier: Analyze and Return Data <br> 2. Paths (Contact ID Exists / No Contact ID) <br> 3. *Contact ID Exists*: monday Update Item → Create Subitem → Filter ×2 → Update Item → Get Column Values → Filter → Delay 1hr → Update Item <br> 4. *No Contact ID*: Look for existing contact → sub-Paths (Existing / New) → either Update Item or **Create Item** then Create Subitem + Update chain | **The big one.** Massive zap — Tally submission triggers a full upsert + subitem creation + delayed status update chain. AI step extracts data from the Tally answer. **Needs:** the `intake` + `update-by-email` endpoints plus a way to record subitems (likely as `dashboard_edited_fields`-style entries on the academy_members doc rather than a separate collection). |

### 🔴 P0 — Stripe / Sales → Monday writes

| # | Zap name | Trigger | Key actions | Notes |
|---|---|---|---|---|
| 11 | `Boost & Go Sales - Arub` (v28) | **Kajabi: New Purchase** | 1. Paths split by tier: Boost & Go No Presentation / B+G Plus No Presentation / Boost & Go Presentation / B+G Plus Presentation <br> 2. Each tier path: Kit Add Tag → Slack ×2 → **monday: Get Items by Column Value** → Paths (Contact Found vs Not Found) → either **monday: Update Item** OR Slack alert | Kajabi-triggered Boost & Go sales zap. Looks up student on Academy Members; updates if found, Slack-alerts if not. **Migrate:** `intake-kajabi` endpoint + `update-by-email` (tasks #31, #32). |
| 12 | `AYCI - Sales - Arub` | (folder, not a zap) | — | Turns out this is just the parent folder name for zap 11. Remove from list. |
| 13 | ~~`New Lead To Monday`~~ | **Out of scope** | — | Lives in Finchley Now folder. Trigger is Gmail (New Labeled Email), writes to the Finchley Now Monday board, not Academy Members. **Move to P3 — not part of this migration.** |

### 🟡 P1 — Interview / Calendly → Monday writes

| # | Zap name | Trigger | Key actions | Notes |
|---|---|---|---|---|
| 14 | `[AYCI JUNE-26] Mock interview - Becky` | **Calendly: VIP (Mock interview) calls** | 1. monday: Get Items by Column Value <br> 2. monday: read mock interview current status <br> 3. **monday: Update mock interview status** <br> 4. Filter (check if eligible) <br> 5. Formatter Date/Time <br> 6. Circle: Find Member <br> 7. Slack: Alert OD call limit reached | Mock interview booked in Calendly → updates `mock_interview_status` column on Academy Members. Three identical sibling zaps for **Becky / Anoop / Charlotte** — assumed Tessa version too. **Migrate:** same `update-by-email` endpoint (task #31). |
| 14b | `[AYCI JUNE-26] Mock interview - Anoop` | Same as 14 | Same structure | Sibling of 14. |
| 14c | `[AYCI JUNE-26] Mock interview - Charlotte` | Same as 14 | Same structure | Sibling of 14. |
| 15 | `8g: 15 minute call booked - Charlotte` | **Calendly: Invitee Created** | monday Get Items by Column Value → **monday Update Item** → Slack | 4-step zap. Same lookup+update + Slack alert pattern. Covered by `update-by-email`. |
| 16 | `8g: 15 minute call booked - Tessa` (Has Draft) | **Calendly: Invitee Created** | Same as 15 | Sibling of 15. |
| 17 | `AYCI 1:1 Call booking reminders - DM on Circle (Oksana)` (v3) | **Schedule by Zapier: weekly Monday** | Webhooks Pull monday contacts in active → Formatter Itemise item IDs → **Looping by Zapier** → monday Get call eligibility → Filter → monday Find interview date → Formatter Date format today + 14 days → Filter → Paths (Private Plus / VIP) → each path: monday Get Circle email → Circle Find Member → Circle Send DM | **Polling cron**. Runs weekly, fetches active PP/VIP students from Monday, pings those overdue for 1:1 call booking via Circle DM. **Migrate:** becomes a backend cron job using academy_members. 🟡 READ_MONDAY (doesn't write back). |
| 18 | `[AYCI JUNE-26] 1:1 Calls - Round Robin (Anoop)` | **Calendly: Invitee Created** | 1. monday: Get Items by Column Value (look up student) <br> 2. monday: Get Column Values <br> 3. AI by Zapier × 2 (decide call number?) <br> 4. Paths (Call 1 / Call 2 / Call 3 / Call 4 / Fallback) <br> 5. Each call path: **monday: Update Item** (mark which 1:1 call number this is) <br> 6. Fallback: Formatter Date/Time → Circle Find Member → Slack alert | Round-robin 1:1 call booking. Uses AI step to pick which of the 4 call slots gets marked. Three sibling zaps: **Anoop / Charlotte / Becky**. **Migrate:** same update-by-email endpoint — but the AI step is the interesting bit, it works out which call slot to fill. May want to replicate that as backend logic eventually. |
| 18b | `[AYCI JUNE-26] 1:1 Calls - Round Robin (Charlotte)` | Same as 18 | Same | Sibling of 18. |
| 18c | `[AYCI JUNE-26] 1:1 Calls - Round Robin (Becky)` | Same as 18 | Same | Sibling of 18. |
| 19 | `[TVA Test] VIP 1:1 Calls - Tessa - update Monday Contacts board` (Has Draft) | **Calendly: VIP calls booked Tessa** | Same Round-Robin shape as 18 (Becky/Anoop/Charlotte) — AI by Zapier steps + Paths for Call 1–4 + Fallback. | Tessa version of the Round-Robin zap family. Sibling of 18/18b/18c. |
| 19c | `Private Plus + VIP 1:1 Calls - Becky - update Monday Contacts board (Oksana)` | **Calendly: PP + VIP calls booked Becky** | Filter (VIP/PP only) → monday Find student → monday Get call bookings status → AI ×2 → Paths Call 1–4 + Fallback → each path Update Item; Fallback also Slacks | Slightly more complex variant of 18 — has an extra Filter for VIP/PP only. Same migration plan. |
| 19d | `Mock interview - Tessa - update Monday Contacts board (Oksana)` | **Calendly: VIP (Mock interview) calls** | Same as 14 (Becky/Anoop/Charlotte) — lookup + update mock_interview_status + Slack alert. | Tessa version of the Mock Interview family. Sibling of 14/14b/14c. |
| 19b | `[AYCI JUNE-26] AYCI testimonial calls booked to Monday post-cohort metrics (OD)` (Has Draft) | **Calendly: AYCI Interview booked** | 1. monday: Find student in post-cohort... <br> 2. **monday: Update column 'Zap -...'** | 3-step zap. Testimonial call booking → flips a column in the post-cohort metrics view. Has unsaved draft. |
| 20 | `New Interview Date` (v11) | **monday: New Item in Board** | Filter → Kit Find Subscriber → Paths (In CK already / Not in CK) → Paths (In Academy / Not In Academy) → **Google Calendar: Create Detailed Event** → Slack | Heavy zap — when a new interview row appears on Monday, creates the calendar event + Slack ping. Critical for Upcoming Interviews. 🟡 READ_MONDAY (no monday writeback in this zap). |
| 21 | `4. Send Interview date form followup via DM or email` (Has Draft, v16) | **Webhooks: Catch Hook** | monday Get Column Values → Formatter Name/Speciality Encode → Formatter Tally encoded link → Paths (Circle email exists / Email exists and No Circle email) → Circle Find Member, Days since last activity, Paths (less/more than 14 days) → Circle Send DM OR Gmail Send Email → **monday Update Item** | Big follow-up zap. Multi-channel reminder (Circle DM if recent, email if not). 🔴 WRITE_MONDAY. |
| 22 | `5. When interview date is updated in Google calendar - Update Monday` (Has Draft, v2) | **Google Calendar: New or Updated Event** | Filter → Formatter Get Pulse ID → Formatter Format Date → monday Get Column Values → Filter → **monday: Update Item** | Calendar-to-Monday sync. 🔴 WRITE_MONDAY. |
| 23 | `6. When Interview status changes to scheduled create / update Google Calendar event` (Has Draft, v7) | **Webhooks: Catch Hook** | Delay 1 min → monday Get Column Values → Formatters (Event start/end + reminder date) → Paths (Previously created meeting / New meeting) → Google Calendar Delete + Create / Create → **monday: Update Item** → Paths → **monday Update Item** | Reverse of zap 22. Both READS and WRITES Monday. The Monday update preserves the calendar event ID. |
| 24 | `8. Collect interview Feedback via DM or email` (Has Draft, v6) | **Webhooks: Catch Hook** | monday Get Column Values → Paths (Circle Email Empty / not) → Circle Find Member, Formatters, Paths (Member found / Not), Days since last activity, Paths (less/more than 14 days) → Circle Send DM OR Gmail Send Email | Multi-channel feedback collection. No monday writeback. 🟡 READ_MONDAY. |
| 25 | `Request Grid interview dates` | **monday: Specific Column Value Changed** | Filter → Circle Find Member → Circle Send Direct Message | Grid (AYGI) zap. Doesn't write back to Monday, just DMs the student via Circle when status changes. 🟡 READ_MONDAY. |
| 26 | `Interview date - New Grid Tally from submission → Update Monday Contact` (Has Draft) | **Tally: New Submission** | monday Find Items → Paths (Circle Email Exists / Does Not Exist) → if exists: **monday Update Item** + Google Calendar Create Event. If not: Slack alert. | Grid (AYGI) interview-date zap. Updates Monday + creates a calendar event for the interview. |

### 🟣 P2 — Monday-internal status flows

These trigger on a Monday event and write to a Monday column. Once Monday is retired, these need replicating as backend logic.

| # | Zap name | Trigger | Key actions | Notes |
|---|---|---|---|---|
| 27 | `Milestone 1 - Monday board status update` (Has Draft) | **Circle: New Tagged Member** | Find Member → Filter → monday Get Items by Column Value → **monday Update Item** | Marks Milestone 1 on Monday when a student is tagged in Circle. Same shape × 5 milestones. Covered by `update-by-email`. |
| 28 | `Milestone 2 - Monday board status update` (Has Draft) | Same as 27 | Same | Sibling of 27. |
| 29 | `Milestone 3 - Monday board status update` (Has Draft) | Same as 27 | Same | Sibling of 27. |
| 30 | `Milestone 4 - Monday board status update` (Has Draft) | Same as 27 | Same | Sibling of 27. |
| 31 | `Milestone 5 - Monday board status update` (Has Draft) | Same as 27 | Same | Sibling of 27. |
| 32 | `When Reminder date changes in Monday check validity and either push it to a future date if needed` | **monday: Specific Columns Values Changed** | Formatter (Today as YYYY-MM-DD) → Paths (Push Reminder Past Dates / Reminder OK) → each path **monday: Set triggers**. | Pure Monday-internal — adjusts a date column to a future date if it's been left in the past. Becomes a backend cron job when Monday's retired. |
| 33 | `0. When contact added to Monday, save First + Surname` (Has Draft, v2) | **monday: New Item in Board** | Formatter Get first name → Formatter Get last name → **monday Update Item** | Tiny zap — splits the contact's Display Name into First + Surname. Pure Monday-internal; becomes redundant when the dashboard stores first/surname separately. |
| 34 | `1.1. When Client email is added in the contacts board - Set unique link to report interview date by staff` (v2) | **monday: Specific Column Value Changed** (Client email) | Filter → monday Get Column Values → Formatter Name Encode + Speciality Encode + Tally encoded link → **monday Update Item** | Generates a unique Tally pre-fill link per student and stores it on Monday. |
| 35 | `1b. When button clicked in the contacts board - Set unique link to report interview date by staff` (v6) | **Webhooks: Catch Hook** (Monday button) | monday Get Column Values → Formatters (Name/Speciality/Tally encode) → **monday Update Item** → Paths (Circle & Main Emails same / not) → monday Update Item / Update Item + Slack | Manual-trigger variant of 34 — coach clicks a button on Monday to regenerate the link. |
| 36 | `7. Deep Dive access - From Monday` (Has Draft, v10) | **monday: Specific Column Value Changed** | Filter → Delay (queue) → Zapier Tables (already-run dedup) → Filter → Zapier Tables (prevent future runs) → **monday Get Column Values** → Circle Find Member → Paths (Not Previously Enrolled / Previously Enrolled) → Circle Add to Space + Tag + DM + **monday Update Item** | Substantial Monday→Circle access-granting zap. Uses Zapier Tables as a dedup store (interesting — the dashboard's equivalent would use Mongo). |
| 37 | `7b. Speciality Space access - From Monday` (Has Draft, v9) | **monday: Specific Column Value Changed** | Filter → Paths (Specialty Exists / Doesn't Exist) → Circle Find Member, Google Sheets Lookup, nested Paths (Qs exist / Don't exist), Path branches for Spaces (Always enroll / Space 2 / Space 3) → Circle Add Member to Space, **monday Update Item** | Complex Monday→Circle space-enrolment zap. Different specialties get assigned to different Circle spaces. Has writebacks. Heavy migration. |
| 38 | `9. Wins Updates` (v9) | **Circle: New Post** (2 min poll) | 1. Formatter Text <br> 2. Slack: Send Private Channel Message <br> 3. **monday: Get Items by Column Value** <br> 4. **monday: Update Item** <br> 5. **monday (3.6.0): Get Items by Column Value** <br> 6. **monday: Update Item** | Watches Circle for new "win" posts → Slack ping + updates TWO Monday rows (likely the student row AND a separate stats row). Two Monday lookups in sequence suggest cross-board updates. **Migrate:** `update-by-email` endpoint × 2 calls, plus a Slack helper. |

### 🔴 P1 — Cohort lifecycle zaps that READ + WRITE Monday (audited)

**Surprise finding:** these "cohort lifecycle" zaps aren't passive — most look up + update the Academy Members board. They're cohort-specific (`[AYCI JUNE-26]`) so they'll need rebuilding for SEP-26 anyway. Migration approach: build **one** dashboard endpoint `POST /api/students-db/lookup-and-update` that mirrors `Get Items by Column Value` + `Update Item`, then re-point each of these zaps at it.

| # | Zap name | Trigger | Key actions | Notes |
|---|---|---|---|---|
| 39 | `[AYCI JUNE-26] New Circle member (OD)` | **Circle: New Tagged Member** | 1. Circle Find Member <br> 2. Filter <br> 3. **monday: Get Items by Column Value** (does student exist on board?) <br> 4. Paths — *On Monday Board*: Kit Find Subscriber → Kit Add Tag → **monday Get + Update Item** → Slack. *Not On Monday Board*: Slack alert. | When a student joins Circle with the cohort tag, tags them in Kit and flips a status on Monday. **Migrate:** dashboard endpoint replacing the Monday lookup + update. |
| 40 | `[AYCI JUNE-26] Cohort - Legacy (OD)` | **Circle: New Tagged Member** | 1. Find Member, Filter ×2 <br> 2. Kit Find Subscriber <br> 3. Paths — *emails match*: Kit Add Tag → **monday Get + Update Item**. *don't match*: Slack alert. | Same as 39 but for legacy-cohort members. Same migration plan. |
| 41 | `[AYCI JUNE-26] Video Launch Last Day Upgrade Bonus (OD)` | **Kit: New Tag Subscriber** | 1. **monday: Get Items by Column Value** <br> 2. Paths — *A*: **monday Update Item**. *B*: Slack alert. | Kit tag fires → Monday status update. **Migrate:** point Kit webhook at dashboard `POST /api/students-db/update-by-email`. |
| 42 | `[AYCI JUNE-26] Video Launch Day 1 Upgrade Bonus (OD)` | **Kit: New Tag Subscriber** | Same as 41 — `Get Items by Column Value` → Paths → `Update Item` / Slack. | Same migration as 41. |
| 43 | `[AYCI JUNE-26] Access to Previous Cohort + Bonus Live Sessions (OD)` | **monday: Specific Column Value Changed** | Filter → Paths (Previous Cohort Only / Bonus Calls Only / Both) → each path: Circle Find Member → Add Member to Space → Send Direct Message → Slack. | 🟡 READ_MONDAY only — doesn't write back. **Migrate:** dashboard emits the same event on column change; rebuild as webhook listener. |
| 44 | `[AYCI JUNE-26] Live webinar bonus call (OD)` | **Kit: New Tag Subscriber** | 1. Delay <br> 2. **monday: Get Items by Column Value** <br> 3. Paths — *A*: **monday Update Item**. *B*: Slack. | Same Kit→Monday pattern as 41/42. Same migration. |
| 45 | `[AYCI JUNE-26] Previous Cohort Access` | **monday: Specific Column Value Changed** | Filter ×2 → Paths (Previous Cohort / Bonus Calls / Both) → each: Circle Find Member → Add Member to Space → Send Direct Message. | 🟡 READ_MONDAY only. Sibling of 43. Same migration. |
| 46 | `[AYCI JUNE-26] Private Chat for Legacy Upgrades (OD) - when they join Circle` (Has Draft) | **monday: Specific Column Value Changed** | Filter ×2 → Circle Find Member → **monday Get Column Values** → **monday Update Item** → Paths (Private Plus / VIP) → each: Circle Tag → Zapier Tables (coach list) → Formatter → Circle Start Group Chat → Filter → Slack → Circle Send DM. | Both READS and WRITES Monday. Spins up a group chat with the assigned coach. Has unsaved draft. |
| 47 | `[AYCI JUNE-26] Private Chat for the VIP and Private Plus members (OD) - when they join Circle` | **monday: Specific Column Value Changed** | Same as 46 but for VIP/PP (not legacy). Filter ×3 → Circle Find Member → monday Get Column Values → monday Update Item → Paths → Tag, coach lookup, group chat, DM, Slack. | Same pattern as 46. |
| 47b | (linked variant of 47) | Same | Same — duplicate / linked version with a separate editor URL. | **Check if both are active** — if so, deduplicate. |

### 🟢 Cohort lifecycle (still being audited)

Remaining cohort-rollout automations. Audit (zaps 39–47) revealed most DO read + write Monday, so expect the same here.

| # | Zap name | Notes |
|---|---|---|
| 48 | `[AYCI JUNE-26] Mock interview - B...` | Likely Calendly → Monday status |
| 49 | `[AYCI JUNE-26] Mock interview - Anoop` | Already audited as **row 14b** — sibling of zap 14 (Becky) and 14c (Charlotte). |
| 50 | `[AYCI JUNE-26] Mock interview - Charlotte` | Already audited as **row 14c** — sibling of 14. |
| 51 | `[AYCI JUNE-26] 1:1 Calls - Round Robin` (×3 coaches) | Already audited as **rows 18 / 18b / 18c** (Anoop / Charlotte / Becky). |
| 52 | `[AYCI JUNE-26] AYCI testimonial call` | Already audited as **row 19b** — Calendly → monday Find + Update post-cohort metrics. |
| 53 | `[AYCI] Private Chat for the Boost & Go` | 🔴 P1. Same pattern as zaps 46/47 (Private Chat). Trigger: monday Specific Column Value Changed → Filter → Circle Find Member → monday Get + Update Item → Paths (Boost & Go - No Presentation / B+G Plus - No Presentation / Boost & Go - Presentation / B+G Plus - Presentation) → each: Circle Tag, coach lookup table, Formatter, Start Group Chat, Filter, Slack, Send DM. v17 — heavy iteration. |
| 54 | `[AYGI 2025] Private Chat for the VIP members (OD/TRD) - when they join Circle` (Has Draft, v7) | **monday: Specific Column Value Changed** → Filter ×2 → Circle Find Member → monday Get Column Values + Update Item → Circle Tag → Zapier Tables (coach list) → Formatter → Circle Start Group Chat → Filter → Slack → Circle Send DM. AYGI variant of zaps 46/47. |
| 55 | `[AYGI 2025] Shortlisted` (v4) | **Kit: Subscriber Added to Tag** → monday Find Items → **monday Update Item** → Slack. Marks AYGI shortlist status on Monday. |
| 56 | `[AYGI 2025] Not Shortlisted` (v3) | **Kit: Subscriber Added to Tag** → monday Find Items → **monday Update Item** → Slack. Sibling of 55 for not-shortlisted candidates. |
| 57 | `[AYGI 26 - Oks...] [AYGI] On Circle (OD)` (Has Draft, v3) | **Circle: New Tagged Member** → Find Member → Filter → monday Get Items by Column Value → Paths (On Monday Board / Not) → On: monday Get + Update Item / Not: Slack alert. AYGI variant of zap 39. |
| 58 | `[AYGI 2025] Signups to Monday Board (OD/TRD)` (v3) | **Kajabi: New Purchase** → Filter (AYGI only) → Paths (Gold / AYGI Pods / AYGI VIP / Legacy Upgrade to Pods / Legacy Upgrade to VIP) → new tier: Create Item + Delay + Add email to trigger tally. Legacy: Get Items + Update Item. This is **zap 2 in this doc** — re-confirmed. Same migration as 1/2/3. |
| 59 | `[AYCI SEP-25] On Circle - not in spaces` (v2) | **monday: New Item in Board** → Circle Find Member → Filter → **monday Update Item**. SEP-25 cohort variant. |
| 60 | `New SEP-25 Circle member (OD)` (v32) | **Circle: New Tagged Member** → Find Member → Filter → monday Get Items by Column Value → Paths (On Monday Board / Not) → Kit Find Subscriber + Add Tag + monday Get + Update Item + Slack / Slack alert. SEP-25 sibling of zap 39. v32 = heavily iterated. |
| 61 | `AYCI SEP-25 Academy Mini-Webinar Registered` (v3) | **Kajabi: New Form Submission** → monday Get Items by Column Value → **monday Update Item** → Kit Find Subscriber → Kit Add Tag. SEP-25 webinar signup → Monday status update. |
| 62 | `[AYGI 2025] On Circle` (Has Draft, v3) | Duplicate-like sibling of 57. |
| 63 | `Legacy Members Cohort Upgrade` (v1) | **Webhooks: Catch Hook** → Filter → Zapier Tables Find Records → **monday Update Item**. Tiny 4-step zap, called by another zap when a legacy member upgrades. |
| 64 | `AYCI Waitlist Registrations - New Website` (v12) | **Kajabi: Waitlist Reg - new website** → Kit (Add to waitlist form) → Kit (waitlist - new website tag) → Kit (waitlist - all tag) → **monday: Create Item** → Google Sheets: Create row → Kit: Add Subscriber to Form. **Migrate:** add `intake` endpoint variant or branch on Kajabi offer to set `stage=waitlist` instead of `enrolled`. |
| 65 | `AYCI Waitlist Registrations - Website` (Has Draft, v25) | **Kajabi: Waitlist Reg - website** → Code (JS) → Kit (Add Tag / Remove Tag / Add to form / website tag / all tag) → **monday: Create Item** → Google Sheets (Modify Cohort For New + Create row) → Kit Add Tag → Paths (utm_source / no utm_source) → Kit add/remove tags. Older website waitlist zap with heavy tag-management logic. v25 — most-iterated zap so far. Same migration as 64. |
| 66 | `AYCI Academy Boss Option A - manually tagged` (Has Draft, v11, **ACTIVE**) | 🔴 P1. Circle New Tagged Member → Find Member → Filter → **Kit Add Tag** → **monday Get Items by Column Value** → Formatter Text + Utilities → Filter → **monday Update Item**. Same lookup+update pattern as zaps 39/40 — covered by `update-by-email` endpoint (task #31). Has unsaved draft. |
| 67 | `AYCI testimonial cal...` | Possibly duplicate of row 19b / row 52 — need a screenshot to confirm, OR confirm via Zapier search if there are two zaps with similar names. |
| 68 | `Student Wins Tracking - First Message (Oksana)` (v5) | **monday: New Item in Board** → Circle Find Member → Delay → monday (3.6.0) Get Column Values → Paths (Path A / Path B) → each path: Circle Send Direct Message → **monday Update Item**. Triggered when a new student is added; sends them a Circle DM after a delay and writes a tracking field back to Monday. READ+WRITE; covered by `update-by-email`. |
| 69 | `8c. Substantive success form - Add Boss Tag on Monday` (v5) | **monday: Specific Column Value Changed** → Filter → Delay After Queue → **monday: Get Items by Column Value** → Paths (A / B) → each path **monday: Update Item**. READ+WRITE Monday. Same pattern as the cohort lifecycle zaps — covered by `update-by-email` (task #31). |
| 70 | `8b. Substantive success form - tags Boss on Circle, CK and give bonus content access` (v7) | **monday: Specific Column Value Changed** → Delay → Circle Find Member → Circle Tag Member → Kit Add Tag to Subscriber → Circle Add Member to Space → Circle Send Direct Message. monday→Circle/Kit/Space. 🟡 READ_MONDAY (no monday writeback). |
| 71 | `Badge Allocation` (v3, "Private channel") | **Slack: New Message Posted to Private channel** → Filter → AI by Zapier: Get Milestone → Formatter: Get Contact Email → monday Get Items by Column Value → Paths (MS 1 / MS 2 / MS 3 / MS 4 / MS 5 / No Circle Email) → each MS path: **monday Update Item** → Slack → Circle Find Member → Circle Tag Member. **No Circle Email** path: Slack alert. **Heavy Slack→AI→Monday→Circle workflow.** Uses LLM to determine which milestone from a Slack message. |
| 72 | `2. When Cohort Tag added in Circle update contact with cohort dates` (Has Draft, v4) | **Circle: New Tagged Member** → Delay → Zapier Tables Find Records (cohort) → Filter → monday Get Items by Column Value → **monday Update Item** → Filter (If joined after cohort start date) → **monday Set in active Cohort to Start**. Sets the active cohort date when a student joins Circle. |
| 73 | ~~`Send Circle group message with coach response`~~ ✅ **TURNED OFF 2026-06-02** | **Webhooks: Catch Hook** → monday Get Column Values → Formatter Text → Zapier Tables Get coach list → Formatter Format list → URL Shortener → **Circle Start Group Chat** → **monday: Update Item** → Filter (only if Gdrive file ID) → Google Drive Delete File. **Was the Private Videos zap** — read/wrote the Private Videos board (5083952249). Replaced by the dashboard's `/api/private-videos/send-response`. **First zap retired in this migration.** |
| 74 | `Grid Send Circle group message with coach response` (Has Draft, v7) | Webhooks Catch Hook → monday Get Column Values → Formatter → Zapier Tables (coach list) → Formatter → URL Shortener → Formatter Extract URL → **Circle Start Group Chat** → **monday Update Item**. **Grid/AYGI variant of zap 73 (retired).** When dashboard handles the Grid coach-reply path, this can be retired too. |
| 75 | `Temp tag for Circle DM auto reply - interview week exclusion (Paris)` (v5) | **Google Calendar: New or updated interview date event** → Filter → Formatter (Get pulse ID) → monday Find Items → Formatter (Get circle email) → Circle Find Member → Circle Tag Member with interview week → **Delay 7 days** → Circle remove interview week tag. Adds a temporary Circle tag during interview week so a DM auto-reply (in zap X) excludes them. Reads monday but doesn't write. 🟡 READ_MONDAY. |
| 76 | ~~`When Cloudconvert process is finished upload to Gdrive and update Monday`~~ ✅ **OFF** (confirmed 2026-06-02) | **CloudConvert: Job Finished** → Filter → Formatter → Google Drive Upload + Share → **monday Update Item**. Was the post-transcode plumbing. Already replaced by `pv_cache.prepare()` (eager transcode) + Whisper transcription on Tally submission. |


### 🟤 P3 — Different products (Finchley Now / Paeds ST3)

Different brands / boards entirely. Out of scope for Academy Members retirement.

| # | Zap name | Product |
|---|---|---|
| 77 | `[Paeds ST3] Crash course - Purchased - not on Circle` | Paeds ST3 — monday New Item → 3-day Delay → check Circle status → Slack alert if not on Circle |
| 78 | `[Paeds ST3] Crash course - Update Kit/Monday - In PST3 circle space` | Paeds ST3 — Circle tag → Find member → monday Find Items → Paths (sign-up email matches / doesn't) → Kit/monday updates |
| 79 | `[Paeds ST3] Crash course - Sales to Monday board` | Paeds ST3 — Kajabi New Purchase → Slack → Kit → Circle Find Member → Paths (Exists / Not on Circle) → monday Create Item. Same shape as the AYCI Kajabi signup zaps but for Paeds ST3 board |
| 80 | `Content alert` (Has Draft, v2) | Finchley Now — **monday: Specific Column Value Changed** → Filter → Formatter Date/Time → Slack Send Channel Message. Out of scope. |
| 81 | `FN Internal Event` | Finchley Now |
| 82 | `Finchley Now Event - External` | Finchley Now |

### 🟤 Likely-retire candidates (parallel to dashboard features)

| # | Zap name | Trigger | Action | Notes |
|---|---|---|---|---|
| 83 | ~~`AYCI Support tickets - Tally to Monday - (Paris)`~~ ✅ **DELETED 2026-06-02** | **Tally: New AYCI support ticket** | 1. monday: Support ticket added to Monday <br> 2. Circle: Find Member <br> 3. monday: Student circle profile url added <br> 4. Slack: Notify circle enquiries slack | Deleted (was already off). Tickets flow into the dashboard's `/api/tickets/tally/webhook` only. Replacement Slack alert (`notify_new_tally_ticket`) was added in `tickets.py` and fires if `SLACK_CIRCLE_ENQUIRIES_WEBHOOK_URL` is set. **Second zap retired.** |

---

## Audit status (2026-06-02)

- **80** zaps audited initially.
- **8** retired during the audit:
  - ✅ `Send Circle group message with coach response` (zap 73 — off)
  - ✅ `AYCI Support tickets - Tally to Monday - (Paris)` (zap 83 — deleted)
  - ✅ 4 × SEP-25 cohort zaps (rows 3, 59, 60, 61 — deleted)
  - ✅ `Tally Form to Monday → Video submission` (zap 8 — off)
  - ✅ `When Cloudconvert process is finished` (zap 76 — off)
- **72** zaps currently active.
- **~10** Grid (AYGI) zaps deferred until Jan 2027.
- **~6** Paeds ST3 / Finchley Now zaps permanently out of scope.
- **~56** zaps in the actual AYCI migration target.
- **0** unaudited rows remaining — full audit complete.

## Primitive endpoints needed (covers ~95% of remaining AYCI zaps)

Tracked in `TaskList` as tasks #31, #32, #33:

1. **`POST /api/students-db/update-by-email`** (#31) — replaces every `Get Items by Column Value + Update Item` pair. Used by ~40 zaps.
2. **`POST /api/students-db/intake`** (#32) — replaces every `Create Item` for new students (Kajabi signup, Tally onboarding, waitlist). Used by ~8 zaps. Should branch on offer name (AYCI/AYGI) and stage (enrolled/waitlist).
3. **`Webhook emit-event on column change`** (#33) — when a dashboard column changes, fire an outbound webhook so downstream zaps (Circle DM, Slack alerts, Google Calendar) can listen via Webhooks by Zapier - Catch Hook. Used by ~12 zaps that have a Monday `Specific Column Value Changed` trigger.

## Migration runbook

For each zap to migrate:

1. Identify which primitive endpoint(s) it needs.
2. In Zapier: replace the Monday step(s) with a Webhooks by Zapier step pointing at the dashboard endpoint.
3. Leave the original Monday step in place for a week as a safety net.
4. Verify the dashboard is receiving correctly (check `db.academy_members.dashboard_edited_fields` audit trail).
5. Remove the Monday step.
6. After all zaps for a board are migrated → turn off the Monday→Mongo mirror → archive the Monday board.
