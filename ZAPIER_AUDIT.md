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
| 1 | `[AYCI JUNE-26] - Signups to Monday Board (OD)` | **Kajabi: New Purchase** | 1. Zapier Tables: Find Records (cohort lookup table) <br> 2. Filter (continue only for AYCI JUNE-26 offers) <br> 3. Formatter: Cohort Start Date <br> 4. Formatter: Cohort End Date <br> 5. Paths split by tier: Academy / Academy Private Plus / Academy VIP / Legacy Upgrade to Private Plus / Legacy Upgrade to Academy <br> 6. **New tier paths**: Create Item → Delay → Add email to trigger Tally onboarding form <br> 7. **Legacy upgrade paths**: Get Items by Column Value → **Update Item** | **Migration:** dashboard endpoint `POST /api/students-db/intake-kajabi` that takes the Kajabi purchase payload, looks up academy_members by email (upsert), sets tier + cohort + dates, fires the Tally onboarding trigger downstream. |
| 2 | `[AYGI 2025] - Signups to Monday Board (OD/TRD)` | **Kajabi: New Purchase** | 1. Filter: continue only if offer is AYGI <br> 2. Split by tier (Gold / AYGI Pods / AYGI VIP / Legacy Upgrade to Pods / Legacy Upgrade to VIP) <br> 3. **For new tiers: Create Item on Academy Members** <br> 4. **For legacy upgrades: Find by email + Update Item** <br> 5. Add email to trigger Tally onboarding form | Same Kajabi-driven pattern as zap 1, just for AYGI programme. **Same migration plan**: the dashboard intake endpoint can branch on offer name (AYCI vs AYGI) and set tier accordingly. |
| 3 | `AYCI SEP 25 - Signups to Monday B...` | ❓ likely Kajabi (same family) | ❓ likely same pattern | Older cohort, still On — may be safe to turn off if no new SEP25 enrolments. |
| 4 | `[AYGI 2025] - Signups to Monday B...` (dupe?) | ❓ | ❓ | Possibly the row Tessa saw twice in the list. Same name as zap 2 — check if it's actually one zap or two. |
| 5 | `Onboarding Form Tally to Monday` | **Tally: New Submission** | 1. **monday.com: Create Item** on Academy Members | Two-step zap. Likely fires after the Kajabi zap above triggers the onboarding form (zap 1's last step). **Migration:** add this endpoint's payload handling to the same `/api/students-db/intake` endpoint — merge with the Kajabi intake on email. |
| 6 | `Onboarding Form (Higher Tiers) Tally to Monday` | **Tally: New Submission** | 1. **monday.com: Create Item** on Academy Members | Same 2-step pattern as zap 5. Higher-tier variant of the onboarding form (likely Private Plus / VIP). **Same migration plan**: merge into the dashboard intake endpoint. |
| 7 | `Non members Tally to Monday` | ❓ Tally (non-Academy signups?) | ❓ Create Monday row? | What board? |
| 8 | `Tally Form to Monday → Video sub...` | ❓ Tally video submission | ❓ Update Monday (private videos board?) | Probably Private Videos board, not Academy Members — verify. |
| 9 | `Grid Tally Form to Monday → Video...` | ❓ Tally (Grid product) | ❓ Update Monday | Likely different board (Grid). |
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
| 15 | `8g: 15 minute call booked - Charlotte` | ❓ Calendly | ❓ Update Monday | |
| 16 | `8g: 15 minute call booked - Tessa` | ❓ Calendly | ❓ Update Monday | |
| 17 | `AYCI 1:1 Call booking reminders - D...` | ❓ Calendly / Monday | ❓ Send reminder | Might not write to Monday. |
| 18 | `[AYCI JUNE-26] 1:1 Calls - Round Robin (Anoop)` | **Calendly: Invitee Created** | 1. monday: Get Items by Column Value (look up student) <br> 2. monday: Get Column Values <br> 3. AI by Zapier × 2 (decide call number?) <br> 4. Paths (Call 1 / Call 2 / Call 3 / Call 4 / Fallback) <br> 5. Each call path: **monday: Update Item** (mark which 1:1 call number this is) <br> 6. Fallback: Formatter Date/Time → Circle Find Member → Slack alert | Round-robin 1:1 call booking. Uses AI step to pick which of the 4 call slots gets marked. Three sibling zaps: **Anoop / Charlotte / Becky**. **Migrate:** same update-by-email endpoint — but the AI step is the interesting bit, it works out which call slot to fill. May want to replicate that as backend logic eventually. |
| 18b | `[AYCI JUNE-26] 1:1 Calls - Round Robin (Charlotte)` | Same as 18 | Same | Sibling of 18. |
| 18c | `[AYCI JUNE-26] 1:1 Calls - Round Robin (Becky)` | Same as 18 | Same | Sibling of 18. |
| 19 | `[TVA Test] VIP 1:1 Calls - Tessa - up...` | ❓ | ❓ | "TVA Test" — test zap, may be inactive. |
| 19b | `[AYCI JUNE-26] AYCI testimonial calls booked to Monday post-cohort metrics (OD)` (Has Draft) | **Calendly: AYCI Interview booked** | 1. monday: Find student in post-cohort... <br> 2. **monday: Update column 'Zap -...'** | 3-step zap. Testimonial call booking → flips a column in the post-cohort metrics view. Has unsaved draft. |
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
| 49 | `[AYCI JUNE-26] Mock interview - A...` | |
| 50 | `[AYCI JUNE-26] Mock interview - C...` | |
| 51 | `[AYCI JUNE-26] 1:1 Calls - Round Ro...` (x3) | |
| 52 | `[AYCI JUNE-26] AYCI testimonial cal...` | |
| 53 | `[AYCI] Private Chat for the Boost & Go` | 🔴 P1. Same pattern as zaps 46/47 (Private Chat). Trigger: monday Specific Column Value Changed → Filter → Circle Find Member → monday Get + Update Item → Paths (Boost & Go - No Presentation / B+G Plus - No Presentation / Boost & Go - Presentation / B+G Plus - Presentation) → each: Circle Tag, coach lookup table, Formatter, Start Group Chat, Filter, Slack, Send DM. v17 — heavy iteration. |
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
| 66 | `AYCI Academy Boss Option A - manually tagged` (Has Draft, v11, **ACTIVE**) | 🔴 P1. Circle New Tagged Member → Find Member → Filter → **Kit Add Tag** → **monday Get Items by Column Value** → Formatter Text + Utilities → Filter → **monday Update Item**. Same lookup+update pattern as zaps 39/40 — covered by `update-by-email` endpoint (task #31). Has unsaved draft. |
| 67 | `AYCI testimonial cal...` | |
| 68 | `Student Wins Tracking - First Mess...` | |
| 69 | `8c. Substantive success form - Add...` | |
| 70 | `8b. Substantive success form - tags...` | |
| 71 | `Badge Allocation` | |
| 72 | `2. When Cohort Tag added in Circle...` | Reads Circle → may write Monday |
| 73 | ~~`Send Circle group message with coach response`~~ ✅ **TURNED OFF 2026-06-02** | **Webhooks: Catch Hook** → monday Get Column Values → Formatter Text → Zapier Tables Get coach list → Formatter Format list → URL Shortener → **Circle Start Group Chat** → **monday: Update Item** → Filter (only if Gdrive file ID) → Google Drive Delete File. **Was the Private Videos zap** — read/wrote the Private Videos board (5083952249). Replaced by the dashboard's `/api/private-videos/send-response`. **First zap retired in this migration.** |
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

### 🟤 Likely-retire candidates (parallel to dashboard features)

| # | Zap name | Trigger | Action | Notes |
|---|---|---|---|---|
| 83 | `AYCI Support tickets - Tally to Monday - (Paris)` (v3, **ACTIVE**) | **Tally: New AYCI support ticket** | 1. monday: Support ticket added to Monday <br> 2. Circle: Find Member <br> 3. monday: Student circle profile url added <br> 4. Slack: Notify circle enquiries slack | **Verified safe to retire** — dashboard's Support Tickets reads directly from Tally (`backend/routes/tickets.py` `/tally/webhook`). Turning this zap off won't affect dashboard tickets. <br> **One thing to preserve first**: step 4 sends a Slack alert to the circle enquiries channel on new tickets. If you rely on that Slack ping, we should replicate it in the dashboard's `tally_webhook` handler before retiring the zap. |

---

## Next steps

Once Tessa has filled in the ❓ rows for at least the P0 section, I'll:
1. Build the dashboard receiving endpoints for each migrated zap (intake, tier update, etc.).
2. Walk through re-pointing each zap in Zapier (same pattern as the Private Videos webhook switch).
3. Run new + old in parallel for a few days so we have a safety net.
4. Cut over once we've confirmed the dashboard is receiving everything.
