# Monday Replacement Spec - Academy Members + Private Videos Boards

**Goal:** Replace the Monday boards we control with Mongo collections as the source of truth. Driver: speed / reliability - Monday API is slow and rate-limited.

**Scope (updated 2026-05-29):**
1. **Academy Members** (`1956295952`) - primary scope, multi-week project. See §§ 1-9 below.
2. **Private Videos** (`5083952249`) - *already mostly migrated*; only cleanup + cutover remains. See §10 below.
3. Other Monday boards (cohort, scorecard, internal team boards) **stay on Monday**.

**Status:** Phase 0 - audit + spec. **Nothing in this doc has been implemented.**

---

## 1. What's on the Monday board today

99 columns. Snapshot saved to `/tmp/monday_board_schema.json` (run the fetch in `audit/fetch_schema.sh` to refresh).

### Columns the dashboard codebase currently reads (~20)

| Purpose | Monday col id | Title | Type |
|---|---|---|---|
| Identity | `name` | Name | name |
| Identity | `text_mkrmj089` | First Name | text |
| Identity | `text_mkrm6m7v` | Surname | text |
| Contact | `email_mkqxv0j0` | Email | email |
| Contact | `email_mkqxyfhm` | Circle Email | email |
| Contact | `phone_mkqxcapx` | Phone | phone |
| Tier | `dropdown_mkqxgqbq` | Tier | dropdown |
| Cohort | `dropdown_mkqxhw8p` | Cohort Joined | dropdown |
| Interview | `date_mkr7rdv7` | Interview Date | date |
| Interview | `dropdown_mkqxk94m` | Speciality | dropdown |
| Interview | `text_mkrqzraa` | Which Hospital? | text |
| Interview | `color_mkr7wahg` | Interview Type | status |
| Allowance (calls) | `color_mkqxp9nt`/`mkqxxemb`/`mkqxvfa5`/`mkqxveyf` | Call 1 / 2 / 3 / 4 | status |
| Allowance (mocks) | `color_mkqxshf3`/`mkqxn5j4`/`mkr0wecr` | Mock Interview 1 / 2 / pre-April | status |
| Allowance (bonus) | `color_mkqx1y49`/`mkr0mq25`/`mkr0ef7c`/`mkrwvwe2`/`mkqxkp6d`/`mks248ex` | Bonus / Gold / Platinum / 15-min / Testimonial / Mini-webinar | status |
| Videos | `numeric_mkxfvz1k` / `numeric_mkxfq65c` | Private video allowance / Videos submitted | numbers |
| Misc | `text_mky9xzew` | Private Chat Link | text |

### Columns the codebase does NOT read but coaches use

The remaining ~80 columns. Examples (full list in the schema JSON):
- Status: On Circle, In Active Cohort, Status, Special Category, Interview Status, Interview Info answer, Interview Reminder Status, Boss Badge, Coaching Status, Refund, etc.
- Dates: Cohort Start/End, Next Call Date, Tier End Date, Date of success, Testimonial Requested / FU-1/2/3, Circle Join Next Reminder, etc.
- Milestone tracking: Intro Post, Milestone 1-5, Win Shared, Follow-up 1-4
- Free text: Notes, Past Interview Dates, Interview reschedule reason, Coaching Offer, Private Spaces, Google Meeting ID
- Links: Interview Tally Link, Google Folder Link, Tally Video Personal Link, Google Meeting Link
- Audit: Creation log, Last updated, Contact ID

**Implication:** The new Mongo schema needs to mirror **all 99 columns** to preserve coach workflows. We aren't dropping anything in the migration.

---

## 2. Read sites in the codebase (Phase 3 swap targets)

| File | What it reads | Notes |
|---|---|---|
| `student_lookup.py:424` | Single student by email | Used by Student Lookup page |
| `student_match.py:68,112` | Find/match by email | Used by Tally lookup |
| `student_prewarm.py:60` | Paginate private-tier students | Daily 05:30 cron |
| `student_edit.py` | Read before write (rename flow) | |
| `upcoming_interviews.py:144` | Students with upcoming interviews | Powers Upcoming Interviews page |
| `cohort.py:65,89,134,154` | Cohort-scoped reads | Powers cohort dashboards |
| `scorecard_auto.py:97,387` | Bulk scan for scorecard calcs | Weekly Monday cron |
| `private_tier_utilisation.py:118` | Private-tier capacity scan | |
| `onboarding_gap.py:229` | Onboarding state read | |
| `over_allowance_alerts.py:91` | Allowance vs used check | |

**No `at_risk.py` read found** - it uses `circle_members_cache` only. Confirm during Phase 3.

## 3. Write sites in the codebase (Phase 4 swap targets)

| File | What it writes | Trigger |
|---|---|---|
| `student_edit.py:60` | Renames item (`change_simple_column_value` on `name` col) | PATCH /api/students/lookup/{item_id} (header pencil edit) |

That's the **only** write in the codebase against board 1956295952. `private_videos.py` writes to board `5083952249` - out of scope.

## 4. External write paths (NOT in this codebase)

Confirmed with Tessa on 2026-05-28: all of the following hit Monday today and will need a replacement target.

1. **Tally form submissions.** Connected to Monday via Tally's built-in integration (or Zapier - to confirm). Creates / updates rows when a student signs up or completes a session.
2. **Stripe webhooks.** Update tier / subscription status on Monday via Zapier or Monday automation. To confirm exact flow.
3. **Monday automations.** In-Monday formulas, status transitions (e.g. set Status when a date passes). Need to inventory these on the Monday admin UI side.
4. **Manual coach edits.** Coaches log into Monday and edit columns (tier, notes, milestone status, etc.).

**Pre-implementation TODO:** Tessa to give me a quick tour of how the team uses Monday day-to-day (which columns they edit most, which views they sort by, which automations they rely on). This is the highest-risk unknown - anything we miss here becomes a coach complaint after cutover.

---

## 5. Proposed Mongo schema

Collection: `students`. One document per student. `_id` = stable internal UUID; `monday_item_id` kept as back-reference during transition.

```js
{
  _id: "<uuid>",
  monday_item_id: "1234567890",          // back-ref during transition; null post-cutover
  monday_synced_at: ISODate("..."),       // last time we mirrored from Monday (Phase 1-3 only)

  // Identity
  name: "Henry Wilson",
  first_name: "Henry",
  surname: "Wilson",

  // Contact
  email: "henry@example.com",             // PRIMARY KEY for lookups. Unique index.
  circle_email: "henryw@example.com",
  phone: "+44...",

  // Tier / cohort
  tier: "Platinum",                        // free-text dropdown label
  cohort_joined: "February 26",
  cohort_start_date: ISODate("..."),
  cohort_end_date: ISODate("..."),
  tier_end_date: ISODate("..."),
  in_active_cohort: true,
  on_circle_status: "On Circle, in Feb '26 spaces",

  // Interview
  interview_date: ISODate("..."),
  interview_type: "Substantive",
  speciality: "Emergency Medicine",
  hospital: "...",
  past_interview_dates: "...",             // free text
  interview_status: "...",
  interview_info_answer: "...",
  interview_reminder_status: "...",
  next_reminder_date: ISODate("..."),

  // Allowances - track BOTH the per-slot status AND a derived count
  // (matches `upcoming_interviews.CALL_COLS/MOCK_COLS/BONUS_COLS`)
  calls: [
    { slot: 1, status: "Eligible",  coach: null },
    { slot: 2, status: "Booked",    coach: "Becky" },
    { slot: 3, status: "Eligible",  coach: null },
    { slot: 4, status: "Eligible",  coach: null },
  ],
  mocks: [
    { slot: 1, status: "...", coach: "..." },
    { slot: 2, status: "...", coach: "..." },
    { slot: "pre_april", status: "...", coach: "..." },
  ],
  bonus_calls: [
    { type: "bonus",       status: "Eligible", coach: null },
    { type: "gold",        status: "..." },
    { type: "platinum",    status: "..." },
    { type: "15_minute",   status: "..." },
    { type: "testimonial", status: "..." },
    { type: "mini_webinar",status: "..." },
  ],

  // Videos
  video_allowance: 20,
  videos_submitted: 4,
  private_video_tally_link: "https://...",

  // Milestones (boolean-ish)
  intro_post: true,
  milestones: { m1: true, m2: true, m3: false, m4: false, m5: false },
  win_shared: false,

  // Testimonials
  testimonial_call: "Pending",
  testimonial_requested: ISODate("..."),
  testimonial_fu_1: ISODate("..."),
  testimonial_fu_2: ISODate("..."),
  testimonial_fu_3: ISODate("..."),

  // Follow-ups
  follow_ups: { fu1: "...", fu2: "...", fu3: "...", fu4: "...", reply: "..." },

  // Free text
  notes: "...",
  private_spaces: "...",
  coaching_offer: "...",
  archive_interview_info: "...",
  google_meeting_id: "...",
  google_meeting_link: "...",
  google_folder_link: "...",
  display_name: "...",                      // Zapier helper

  // Status flags coaches use
  special_category: "Long-Term Member",
  status: "Working on it",
  coaching_status: "...",
  boss_badge: "...",
  email_match: "Yes",
  account_match: "...",
  triggers: "...",
  trigger_previous_cohort_access: "...",
  boost_and_go: "...",
  refund: "...",
  deep_dive: "...",
  speciality_spaces: "...",
  circle_join_follow_up: "...",
  circle_join_next_reminder: ISODate("..."),
  reminder_delivery_method: "...",
  autoreply_dm_trd: "...",
  feedback_request_count: 0,
  new_cohort_upgrade_deadline: ISODate("..."),

  // Mini-webinar registrations
  july_25_minwebinar_registered: false,
  sep_25_minwebinar_registered: false,
  ama_sessions_access: [...],
  private_spaces_created: [...],

  // Misc
  legacy: "...",
  date_of_success: ISODate("..."),
  contact_id: "...",

  // Audit
  created_at: ISODate("..."),
  updated_at: ISODate("..."),
  updated_by: "tessa@medicalinterviewprep.com",
  history: [                                // audit log
    { at: ISODate("..."), by: "...", field: "tier", from: "Gold", to: "Platinum" },
  ],
}
```

**Indexes:**
- `email` (unique, sparse)
- `monday_item_id` (unique, sparse, transition only)
- `tier` (filter on Students page)
- `cohort_joined` (filter)
- `interview_date` (Upcoming Interviews page)
- `updated_at -1` (sort)

**Audit trail:** Mongo gives us nothing for free - Monday has a built-in activity log per row. We need to write our own `history[]` (or a separate `students_history` collection) on every PATCH. Spec: every column change captures `{at, by, field, from, to}`.

---

## 6. Phased plan (concrete)

### Phase 0 - Audit + spec ✓ (this doc)

### Phase 1 - Foundation (3-5 days)
1. Define the schema above as a Pydantic model (`backend/models_students.py`).
2. Build CRUD endpoints under `/api/students-db/...`:
   - `GET /api/students-db` - list, with filter/sort/search/pagination.
   - `GET /api/students-db/{id}` - single student.
   - `POST /api/students-db` - create.
   - `PATCH /api/students-db/{id}` - update, writes to `history[]`.
   - `DELETE /api/students-db/{id}` - soft archive.
3. **One-time migration script** (`backend/migrate_monday_to_mongo.py`). Pulls every row from Monday, maps columns to schema, upserts into Mongo by `monday_item_id`. Idempotent so we can run it repeatedly during transition.
4. **Dual-write helper** (`backend/students_dualwrite.py`). When we PATCH a student, we update Mongo AND attempt the Monday update. If Monday fails we log and continue (Mongo is canonical).
5. CI / dev: write a re-runnable seed of 5 fake students so we can develop the UI against real shape.

### Phase 2 - Students CRUD UI (1-2 weeks)
6. New frontend page `/students` (sidebar entry next to Student Lookup):
   - Table with virtualised rows (~3.5K). Columns visible by default: Name, Email, Tier, Cohort, Interview Date, Status. Show-hide other columns via a column-picker.
   - Filter bar (tier dropdown, cohort dropdown, status, date range).
   - Search by name (reuse the in-memory name index) or email.
   - Inline edit OR row-detail drawer (TBD - ask Tessa which she prefers).
   - "Add student" button.
   - Bulk-select + bulk-edit (e.g. set tier on 20 rows).
7. Recreate any specific Monday views coaches use today (e.g. "this week's interviews", "private tier needing follow-up"). Identify in Phase 0.5 with Tessa.

### Phase 3 - Re-point reads (3-5 days)
8. Update each read site listed in §2 to query Mongo first, with Monday as fallback for 1-2 days (canary). Sites:
   - `student_lookup.monday_lookup` → read from Mongo by email.
   - `upcoming_interviews` → query `students` where `interview_date >= today`.
   - `student_match`, `student_prewarm`, `cohort.py`, `scorecard_auto.py`, `private_tier_utilisation.py`, `onboarding_gap.py`, `over_allowance_alerts.py` → all switch.
9. Run a daily reconciliation cron during the transition: pull all rows from Monday, diff against Mongo, alert Slack on any drift.

### Phase 4 - Re-point writes (3-5 days)
10. **Replace the Tally→Monday integration.** Either:
    - Configure Tally webhook to hit a new `POST /api/tally/student-intake` endpoint that writes to Mongo (preferred), OR
    - Keep Tally→Monday in place and have a 5-min cron pull new Monday rows into Mongo (until we cut over Tally).
11. **Re-point Stripe webhooks** - wherever Stripe currently updates Monday (Zapier?), update Mongo instead. Need to identify each automation.
12. **`student_edit.py`** - switch the write target to Mongo. Drop the Monday mutation.
13. **Stop dual-writing.** Mongo is canonical.

### Phase 5 - Cutover (1 day)
14. Disable Monday automations that touch this board.
15. Read-only the board in Monday (don't delete - keep as archival reference).
16. Remove the dual-write fallback code.
17. Remove the Monday item_id back-reference from new records.

---

## 7. Open questions for Tessa

1. **Day-to-day coach workflow.** Which columns do you and the team actually edit on Monday in a typical week? Which views/filters do you use? This is the biggest derisk.
2. **Stripe → Monday today** - is that via Zapier or a Monday automation or something else? Need to know what to repoint.
3. **Monday automations** - do you have a list, or should I open the board admin and audit them?
4. **Tally** - is the Tally → Monday connection a native Tally integration or via Zapier?
5. **Editing UX preference** - inline edit on the table, or a row-detail drawer? Or both (drawer for full edit, inline for common fields)?
6. **Permissions** - should non-admin coaches see all columns or a curated subset? Edit-only or admin-only for certain columns (e.g. tier)?
7. **Audit retention** - keep edit history forever, or 90 days? Show on the student card?
8. **Cutover style** - hard cutover (one weekend), or parallel run for 1-2 weeks where both systems are live?

---

## 8. Risk register

| Risk | Mitigation |
|---|---|
| Coaches use a Monday column we didn't migrate | Mirror **all** 99 columns. Confirm with the team in Phase 0.5 walkthrough. |
| Tally → Monday integration breaks during cutover | Run Tally → Monday AND Tally → Mongo in parallel for 1-2 weeks. |
| Stripe webhook update path is undocumented | Audit the Zapier zaps / Monday automations before Phase 4. |
| Mongo gets a write before Monday-side automation can fire | Document all Monday automations. Rebuild them as backend cron / event handlers before cutting Monday off. |
| Some unknown reader/writer of the Monday board is missed | Set Monday board API to read-only after Phase 4; watch for errors for 48h. |
| Coaches resist losing kanban / calendar views | Build a basic calendar view + filter views in Phase 2 (deferred-OK if they're not actually used). |

---

## 9. Next concrete step

**Before any code is written:** Tessa walks me through the team's Monday workflow (15-30 min - could be a Loom or a screen-share, or just a Q&A in this chat). Outcome:
- Confirmed list of Monday automations.
- List of "must-have" views / filters coaches use.
- Decisions on the open questions in §7.

Once that's done, Phase 1 work can start.

---

## 10. Private Videos board (`5083952249`) - code-ready, team not migrated

**Correction (2026-05-29):** I initially called this "almost done" based on the code state. Tessa clarified the team is still working on Monday for Private Videos - Tally → Monday only, the dashboard's webhook isn't wired, and coaches haven't switched. So this is a real migration, not just code cleanup. The good news: the dashboard's *page* is already feature-complete, so the work is mainly cutover + change-management, not UI build.

### Code state today

- `backend/private_videos_store.py` - Mongo-backed CRUD on `db.private_video_submissions`. Used by every route handler.
- `backend/routes/private_videos.py` - wired to `private_videos_store`. All read/write endpoints use Mongo.
- `frontend/src/pages/PrivateVideos.jsx` - feature-complete UI: search, status + assignee filters, stat pills, inline assignee dropdown, inline reply link edit, edit modal (status / assignee / replied / reply link), "Send to Circle" reply flow, video player, Circle DM jump, per-row Tally / Monday source badge, "Sync from Monday" button.
- `pv_store.ingest_tally_submission` accepts a Tally webhook and writes to Mongo (idempotent on `tally_submission_id`). **Currently NOT wired in Tally** - the form still POSTs to Monday.
- `backend/private_videos.py` - legacy Monday-direct module. **Zero callers.** Dead code, safe to delete after cutover.
- `pv_store.sync_from_monday` + `migrate_from_monday` exist only as admin endpoints. **No cron behind them.** These will be the bridge during transition.

### Team state today

- Tally → Monday only (native Tally-Monday integration or Zapier).
- Coaches log into the Monday board to edit Status, Assignee, Replied, Reply link.
- The dashboard Private Videos page exists but isn't part of anyone's daily workflow yet.

### Cutover plan

| Step | What | Owner | Effort |
|---|---|---|---|
| PV-A | Sit down with one coach for 10 min and walk through the dashboard's Private Videos page. List anything they think is missing or worse than Monday (column they need, action they can't take, etc.). | Tessa | 15 min + Loom share |
| PV-B | Close any real gaps PV-A surfaces. Most likely a small UI tweak or two; if it's a bigger gap, decide whether to defer it. | Me | depends on gap |
| PV-C | Run `POST /api/private-videos/migrate-from-monday` to backfill Mongo with every existing Monday row. Verify counts match. | Me + Tessa to verify | 30 min |
| PV-D | Set up a 5-min cron running `sync_from_monday(preserve_team_edits=True)` so coach edits on Monday flow into Mongo during the transition. (Right now this only runs on a manual button.) | Me | 1 h |
| PV-E | Re-point Tally form `0Qr5py` webhook from Monday → `https://ayci-dashboard.onrender.com/api/private-videos/tally-webhook`. From this moment new submissions land in Mongo as the primary record; the Monday-side row is whatever Tally's old integration still creates (parallel). | Tessa (Tally admin) | 5 min |
| PV-F | Announce to the team: "from now on edit on the dashboard, not Monday." Run for 1-2 weeks. Watch the per-row data-source badge to confirm new rows are Tally-ingested. | Tessa | 0 |
| PV-G | Turn off the Tally → Monday integration entirely. Stop the sync_from_monday cron. Archive the Monday board (read-only, don't delete). | Tessa + me | 30 min |
| PV-H | Delete `backend/private_videos.py` + the admin sync endpoints + the "Sync from Monday" button. Update docstrings. | Me | 30 min |

### Open questions for Tessa on Private Videos

1. **Coach demo.** Want me to set up a Loom-style walkthrough script of the dashboard's Private Videos page that you can send to one coach for feedback (PV-A)? Or you'll show them yourself?
2. **Cron cadence.** During the transition, how often should we pull edits from Monday? Every 5 min feels right but it depends on how active the editing is. Could also be 15 min or hourly.
3. **Migration test run.** Want to dry-run PV-C against a staging DB first, or go straight against prod and roll back if needed? (Migration is idempotent and only writes - no destructive ops - so prod-direct is reasonable.)
4. **Tally webhook URL.** I should confirm whether Tally should POST to Vercel (which rewrites to Render) or direct to Render (`https://ayci-dashboard.onrender.com/api/private-videos/tally-webhook`). I'll check the existing routes when we get to PV-E.

### Priority decision

The Private Videos cutover is small enough to do **alongside** the Academy Members audit/spec without conflict (different collections, different routes, different team workflow). It could also serve as a useful "first cutover" to derisk the bigger one - same pattern (re-point Tally, mirror Monday, swap reads, train team, archive board) at a smaller scale.

**Recommendation:** do PV-A this week (15 min with one coach), then schedule the rest while the Academy Members workflow walkthrough is being planned.

