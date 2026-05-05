# AYCI Team Dashboard — PRD

## Original problem statement
Build a clean, modern team performance dashboard for AYCI Academy (a company helping doctors prepare for consultant interviews, ~10-person team, runs on EOS). Three views: Weekly Scorecard, Quarterly Rocks, Launch Dashboard. Plus Settings/Admin. JWT auth, admin + user roles. Notion-meets-financial-dashboard vibe, dark navy sidebar (#1A1F36) + teal (#0EA5E9).

### Add-on (April 2026): Unified Student Lookup Dashboard
A single-page view where the team searches a student by email and sees a unified profile pulled live, in parallel, from Monday.com (Academy Members board 1956295952), Circle, Stripe, ConvertKit, and Calendly. Fields: name, email, tier, cohorts, private chat link, interview history, past calls, activity, last-seen on Circle, (future) private Google Doc summary.

## Architecture
- **Backend**: FastAPI + MongoDB (motor), JWT (PyJWT) auth via httpOnly cookies, bcrypt password hashing, all routes prefixed `/api`. APScheduler weekly cron (Monday 06:00 Europe/London).
- **Frontend**: React 19 + React Router 7 + shadcn/ui + Tailwind + Recharts + Sonner. Manrope (display) + Inter (body) fonts. AuthContext with `withCredentials: true`.
- **Data model (MongoDB)**: `users`, `team_members`, `metrics`, `weekly_values`, `rocks`, `launches`, `launch_data`, `daily_registrations`, `circle_members_cache` (slim Circle member list, 24 h TTL).

## Implemented

### 2026-05-05 — Support Tickets header trim + historical cutoff
- **Date cutoff** (`SupportTickets.jsx`): tickets created before **5 May 2026** are now hidden by default to remove the historical Tally backlog noise. A small **+N older** link in the stats strip toggles them back on (state-only — no data deleted). Stat counters (Open / Overdue / Urgent / Mine) also respect the cutoff so they reflect the visible board.
- **Compact header** (`SupportTickets.jsx`): removed the "Customer Service" eyebrow + long SLA description. The four big stat cards became slim inline pills in a single horizontal strip. Toolbar margins tightened. Mobile reaches the first ticket card noticeably faster.

### 2026-05-05 — Ticket attachments (Gmail / Wati / Tally → MongoDB GridFS)
- **Storage** (`/app/backend/attachments.py`): files up to 10 MB stored in GridFS bucket `ticket_attachments`; bytes streamed back via `GET /api/tickets/{id}/attachments/{att_id}` with the right MIME so images render inline. GridFS files auto-GC'd on ticket delete.
- **Gmail**: `_download_gmail_attachments` pulls each attachment via `users.messages.attachments.get` and stores it. Both new tickets (description block) and replies (note-level `attachments`) get them.
- **Wati WhatsApp**: `_fetch_wati_media` calls `/api/v1/getMedia?fileName={mediaId}` and stores it. Captures captions in the body.
- **Tally**: `_fetch_tally_attachments` downloads any FILE_UPLOAD answer URLs and stores them. Captured for both poll-sync and webhook flows.
- **UI**: ticket detail shows image thumbnails (clickable to open full-size in a new tab) and download chips for non-image files. Each note shows its own compact attachments row. Kanban cards display a paperclip badge with attachment count.
- **Inbox auto-assignment** (`gmail_sync._resolve_assignee_for_inbox` + `settings_store.get_inbox_routing` + `routes/team` GET/PUT `/team/inbox-routing`): admin-editable mapping in **Settings → Team → Inbox auto-assignment**. New email tickets are auto-assigned at creation time. Default seed: `tessa,arub → Arub Yousuf` and `coralie,oksana → Coralie Fairon`. Verified live (real Tessa-inbox ticket auto-assigned to Arub).


### 2026-05-04 — Gmail two-way reply + per-user inboxes
- **Gmail two-way reply** (`gmail_sync.send_reply`, `routes/oauth_gmail.py POST /tickets/{id}/reply`): added `gmail.send` scope; reply goes from the original receiving inbox (email-source tickets, threading preserved via `In-Reply-To`/`References`/`threadId`) or — for Tally/Manual — from the current user's connected Gmail (or a fallback). First reply on a non-email ticket stamps `gmail_thread_id` so subsequent replies thread correctly.
- **Per-user Gmail** (`gmail_inboxes.user_id` + `ingest_inbound`): each team member connects their own Gmail via **Profile → My Gmail Inbox** (no longer admin-only). Each user sees only their own inbox; admin sees all in a collapsible section. Polling only runs on inboxes flagged `ingest_inbound=true` (typically a shared `support@` mailbox, not personal). Status badge shows "Send-only" vs "Ingest" + Healthy/Pending/Error.
- **Reply matrix per source**: WhatsApp → Wati API · Email/Tally/Manual (with student email) → Gmail (current user's inbox or original receiving inbox).


### 2026-05-04 — Universal student matching on Support Tickets + Wati live
- **Wati WhatsApp Business**: credentials wired (`WATI_BASE_URL=https://live-mt-server.wati.io/480152`, token + phone `+44 20 8058 5289`). API health verified — 39 approved templates flowing. Webhook URL given to user: `https://ayci-dashboard.preview.emergentagent.com/api/wati/webhook`.
- **Universal ticket → student linker** (`/app/backend/student_match.py`): every ticket now auto-matches to a Monday Academy Member record by email (fast indexed search) OR phone (digit-normalised scan of last 10 digits — handles UK local `07…` vs E.164 `447…` WhatsApp format). Match cached on the ticket under `student_match` + 24h TTL; force-refresh via `POST /api/tickets/{id}/match-student`. Ticket detail modal surfaces a **LINKED STUDENT RECORD** card with tier, cohort, Student Lookup link (fixed `?email=` query param), and Monday deep link.
- **Circle DMs — NOT available**: documented that Circle's REST API doesn't expose DM inbox/retrieval. Decision: once Gmail auto-pull is live, Circle DM email notifications will naturally flow into tickets.


### 2026-05-04 — Phase 2: Gmail + Wati WhatsApp inbox auto-pull (scaffolding)
- **Gmail multi-account OAuth** (`/app/backend/gmail_sync.py`, `routes/oauth_gmail.py`): admin connects multiple Gmail inboxes via popup OAuth → 15-min cron polls each inbox → inbound emails (excluding internal team domains) become Support Tickets. Replies on existing Gmail thread auto-append as notes. Attachment metadata captured (filename + size, no body download). Settings → Inboxes admin UI for connect/list/disconnect/manual-sync.
- **Wati WhatsApp Business** (`/app/backend/wati.py`, `routes/wati.py`): public webhook at `/api/wati/webhook` ingests Wati `messageReceived` events. Threading rule: ONE OPEN ticket per WhatsApp number — new messages append as notes, new tickets created when previous one closed/resolved. Two-way: ticket detail panel shows green WhatsApp reply box (free-text within 24h window) + template dropdown (sourced from `/api/wati/templates`) when out of window. Verified: dedup by message ID, append-on-same-student, idempotent webhook.
- **Tally webhook**: connected by user — new support form submissions appear in `/tickets` in real time.
- **Awaiting credentials**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `WATI_BASE_URL`, `WATI_ACCESS_TOKEN`. Endpoints + UI degrade gracefully when not configured (`status.configured=false`).


### 2026-05-04 — Support Tickets feature (Phase 1)
- **New board "Support Tickets"** (`/tickets`): customer service ticket system with full Kanban (Open / In Progress / Waiting on Student / Resolved / Closed) + Table view, search, filters (priority/category/assignee), "My tickets" toggle.
- **Sources**: Manual entry from the dashboard, **Tally form** (`D4BW1N` "AYCI Support Desk", 73 historical submissions auto-backfilled on startup), and Phase 2 inbox auto-pull (Gmail/Outlook). Tally is dual-fed: 15-min APScheduler poll + public webhook (`POST /api/tickets/tally/webhook`) for near-real-time delivery, both deduped by Tally `submissionId`.
- **Per-priority SLA**: Urgent=4h, High=24h, Medium=48h, Low=120h. Open/In-Progress/Waiting tickets older than the SLA flag as `overdue` (computed live, no DB writes).
- **Slack-on-Urgent**: when a ticket is created OR escalated to Urgent, posts a digest to `SLACK_WEBHOOK_URL`. Idempotent via `slack_urgent_sent` flag (resets on every escalation).
- **Notes thread** per ticket (team-internal). Auto-link from ticket detail to Student Lookup by email.
- **Weekly Scorecard widget** (`/app/frontend/src/components/SupportTicketsWidget.jsx`): compact card showing Open / Overdue / Resolved-this-week, links to `/tickets`.
- **Backend**: `/app/backend/tickets.py` (logic + Tally + Slack), `/app/backend/routes/tickets.py` (REST), `/app/backend/models.py` (Ticket models), `/app/backend/server.py` (initial backfill + 15-min sync cron).
- **Tests**: `/app/backend/tests/test_tickets.py` — 15/15 passing (CRUD, filters, search, notes, Tally sync idempotency, webhook accept/reject/dedup, permissions). Frontend Playwright run passed all flows.


### 2026-05-04 — Cohort pending list + Upcoming Interviews tier accuracy
- **Cohort "Still to join Circle"** (`/app/backend/cohort.py`): now excludes students whose Monday **"On Circle" status column** (`color_mkqxdbm8`) is manually set to `On Circle, in <cohort> spaces` (e.g. `"On Circle, in Apr '26 spaces"`). The team maintains this column by hand and it's the authoritative join signal — bridges email mismatches between Monday/ConvertKit and Circle (students frequently register on Circle with a different email). Chase-list count on April 26 cohort dropped 39 → 28; previously false-positive students (Veronica Chinchon, Sarah Somerville, Oliver Smith, Maleeha Rafiq, David Maxey, Anirudh Kumar, Adekunle Sobowale) correctly excluded. Lidia Trup remains excluded via existing Boss-badge rule.
- **Upcoming Interviews pane** (`/app/backend/upcoming_interviews.py`, `/app/backend/private_tier_utilisation.py`): **Silver** and **Gold** removed from `PRIVATE_PLUS_LABELS`. Those were legacy product names; today Silver/Gold students have no private allowances and should render in the Academy pane. `_ACADEMY_EQUIV = {"academy", "silver", "gold"}` is the new routing rule. Verified against Ibtisam Salim, Thomas Elliott, Martin Van Carlen, Claire Crichton-Iannone — all now correctly Academy.


### 2026-05-02 — Leaderboard tiebreaker + 30-min Slack reminders for Spotlight Coaching
- **Leaderboard scoring** (`/app/backend/leaderboard.py`): treats Circle `member_tags` as the badge ledger. Score = total tags − cohort tags − private-tier tags.
  - Cohort tags detected by regex (`/^[A-Za-z]+ '\d{2}$/`), `AYGI*`, `RFI-*`, "Legacy Cohort".
  - Private-tier tags = {VIP, Private Tier, Private Plus, Platinum, Gold, 1:1, Boost & Go}.
  - Only members carrying the active cohort tag (`Apr '26`) get a score; others render as no-leaderboard.
- **Spotlight prioritisation** now uses the leaderboard as the **secondary sort key** after "interview soon": within the same interview-day group, higher badge count wins. Visible in the UI as an amber "🏆 N" pill next to each student's name, and as the order of rows.
  - Live: Lorna Clemans (7 badges) jumps above mohamed shaisha (2) and Ala Haqiqi (1) within the 6 May interview group; Lucy Bemand-Qureshi (6 badges) leads the no-interview tail.
- **30-min Slack reminders** (`/app/backend/spotlight_slack.py`):
  - APScheduler cron runs every 5 minutes; for any spotlight-eligible Circle session whose `starts_at` falls in the [25, 35]-min window from now, it builds a prioritised digest and POSTs to the existing `SLACK_WEBHOOK_URL`.
  - Mongo collection `spotlight_reminders_sent` tracks `session_id → sent_at` for idempotency, so each session triggers exactly once even if the cron fires multiple times during the window.
  - Digest blocks: header (session name + start time + counts), top-8 prioritised students (interview date + days, badge count, late flag), "Open in Circle" link.
  - New admin-only routes: `POST /api/spotlight/slack/check-now` (run the cron logic on demand) and `POST /api/spotlight/slack/test?session_id=<id>` (force-send for one session, bypassing the time window).
- **Tests**: `/app/backend/tests/test_leaderboard.py` — 6 passing tests covering cohort/tier detection, basic scoring, list[dict] vs list[str] shapes, edge cases.

### 2026-05-02 — Spotlight Coaching board
- New top-level sidebar item **"Spotlight Coaching"** (✨ icon, teal hero gradient). Shows the next 4 upcoming Circle live sessions classified as **Curriculum Session** or **General/Bonus General Coaching**, each with the students who've submitted the spotlight Tally form for that session.
- **Per-session card** displays: session name + UK start time, submission deadline (calendar day before), "Open in Circle" deep link, totals (submissions, interview-soon), then a priority-ordered table of: Priority#, Student, Topic they'd like to work on, Interview date / days-until / type, Submitted-on. Top-most row card is highlighted ("Next up" pill, gradient header).
- **Priority sort**: students with an upcoming interview (any date ≥ today) rank above those without; within that group, soonest interview wins. Rows where the interview is ≤7 days away get a rose/red row tint and rose priority chip — making it impossible for the coach to miss who needs spotlight today.
- **Cross-reference**: spotlight Tally forms `mY8WPq` (curriculum) + `wgxO1l` (group coaching) don't capture email, so we match against the existing post-interview Tally form (`nGyGj2`) by **full name**, falling back to **first-word only** when the interview form's name field stores just a first name (e.g. "Rami"). Ambiguous first-word matches (multiple distinct names share a first word) are skipped.
- **Cycle scoping**: each upcoming session only shows submissions made *after the previous same-type session started* and *before the upcoming session starts* — so signups carry through the cycle without polluting future weeks.
- **"Late" / "Form not done"** badges: submissions made after the calendar-day-before deadline are flagged "Late"; students who claim an interview on the spotlight form but haven't submitted the interview tally form get a "Form not done" amber badge in the Interview column.
- **Dedup**: Circle returns one event row per host duplicate — we collapse `(name, starts_at)` pairs.
- **Caching**: 15-min Mongo cache for both Tally form pulls and Circle events list, sub-100 ms after warm.
- **Backend**: `/app/backend/spotlight.py` + `/app/backend/routes/spotlight.py` (`GET /api/spotlight/sessions?limit=4`). New board id `spotlight` added to `ALL_BOARDS`.
- **Frontend**: `/app/frontend/src/pages/SpotlightCoaching.jsx` + sidebar entry in `AppShell.jsx`.

### 2026-05-01 — Pulse Score (team-health composite) + Pending Circle Joins UI verified
- **Pulse Score**: new top-of-page card on the Weekly Scorecard. Single 0–100 score amalgamating four pillars (each scored /25):
  1. **Scorecard goals** — % of latest-week metrics on-track.
  2. **Quarterly rocks** — % of active-quarter rocks NOT off-track.
  3. **SLA breaches** — Circle posts >48 h unanswered (each docks 3 pts, floor 0).
  4. **At-risk students** — high-spend dormant students (each docks 1 pt, floor 0).
  Tier bands: ≥80 Healthy (emerald), 60-79 Watch (amber), <60 At risk (rose). Card shows a gradient ring with the score, the tier badge, "Week of YYYY-MM-DD", and 4 mini-pillar tiles each with score, mini progress bar, and human-readable label (e.g. "10 of 14 scorecard goals missed", "58 high-spend students dormant on Circle").
  - New backend module `/app/backend/pulse_score.py` + route `/api/pulse-score` (in `routes/pulse.py`). All inputs reuse existing caches (coach_activity, at_risk_cache) so the endpoint is sub-100ms after warm caches.
  - Frontend component `/app/frontend/src/components/PulseCard.jsx` with `data-testid` selectors (`pulse-card`, `pulse-tier`, `pulse-pillar-{key}`).
  - Tests: `/app/backend/tests/test_pulse_score.py` validates shape, score range, label values, and pillar-sum invariant.
- **Pending Circle Joins** (verified rendering): "Still to join Circle" 60-count banner on the Cohort Dashboard with VIP/Academy Private Plus/Academy/(unknown) tier chips, plus a chase-list table at the bottom (Name, Tier, Email, Has Circle account?). Sorted by tier severity. Live: 60 cohort students still missing the "Apr '26" tag.

### 2026-04-30 — Becky Platt linked + Slack SLA digest + CSV scorecard export
- **Becky Platt team_member**: idempotent migration `_ensure_becky_team_member()` runs on startup. Inserts a `team_members` row (`name="Becky Platt"`, `role_title="Coach"`) if missing, then links her existing user. Becky can now edit her own rocks. Verified: `team_member` row exists, user `team_member_id` populated.
- **Slack SLA digest**:
  - New `sla_notifications.py` module: posts a daily digest of >48 h unanswered Circle posts (Recorded Answer Review + Specific Interview Support spaces) to a single Slack incoming webhook.
  - New `POST /api/notifications/slack/test` (admin) for manual triggering. Falls through gracefully (no 500) when `SLACK_WEBHOOK_URL` env var is missing.
  - APScheduler cron: **daily 08:00 Europe/London** → `_daily_sla_digest()`.
  - **In-app bell** in the AppShell sidebar: "🔔 SLA breaches" with live count badge (red bubble for >0, "clear" pill for 0). Polls `/api/notifications/sla/count` every 5 min. Hidden for users without Coach Activity board access. Clicking jumps to the Coach Activity dashboard.
  - **Setup**: add `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...` to `/app/backend/.env` and `sudo supervisorctl restart backend`. Config is server-side env (never touched in this app's `.env` editing rules).
- **CSV scorecard export**:
  - `GET /api/scorecard/export.csv?scope=year|recent` (board-guarded). `scope=recent&weeks=8` returns just the last N weeks; `scope=year` returns every recorded week. Streamed `text/csv` with proper filename.
  - "📥 CSV ▾" button on the Weekly Scorecard with a dropdown menu: "Last 8 weeks · Current view" + "Full archive · All weeks of the year". Triggers a same-origin authenticated download via anchor click (uses the httpOnly access cookie).
- **Tests**: 8/8 pass in `test_iteration9.py` covering: Becky team_member exists + linked, SLA count endpoint, Slack test endpoint graceful fallback, SLA endpoint auth-required, CSV recent + year exports, invalid scope → 400.

### 2026-04-29 — Cohort Dashboard tweaks (round 2) + Locum/Substantive on PTU
- **Cohort total = new + legacy from ConvertKit** (421 = 173 new + 248 legacy). Two denominators are now exposed: `students` (= new+legacy, headline) and `monday_cohort_total` (the subset on Monday with full data, used for tier/milestone/speciality % so they sum to 100% within the visible Monday population).
- **On Circle / Intros denominators** = cohort total (421). Match logic now intersects `(new_emails ∪ legacy_emails)` against Circle membership tags / intro-space posters.
- **Tier split is now compact** — replaced 5 tall bars with a single horizontal stacked bar + chip legend (≈60% less vertical space). Tooltips still show count + %.
- **Upcoming Interviews → Private Tier Utilisation** rows now show a "LOCUM" / "SUBSTANTIVE" pill under each student name, sourced from Monday column `color_mkr7wahg` (Interview Type). Locum badge is amber, Substantive grey for instant scannability.

### 2026-04-29 — Cohort Dashboard fixes: new-signup denominator + specialty to bottom
- **Cohort total now = new signups in this launch** (ConvertKit `Cohort - New` tag ∩ Monday Cohort-Joined), not the raw Monday board headcount. All downstream stats (tier %, milestone %, Circle coverage, intros coverage) now use this denominator. Backend `cohort_summary()` filters per-item loops to new signups only; legacy students no longer skew tier / speciality / milestone counts.
- **Stat cards updated**: "Total (Kit)" → "Cohort total" (value = new-signup total, subtitle "New signups in this launch"). "New (Kit)" and "Legacy (Kit)" subtitles clarified to "X% of Kit". "On Circle" subtitle now says "% of cohort (tag …)".
- **On Circle denominator fixed** — was `monday_total` (170), now matches cohort total (169 new signups).
- **Speciality section moved to the bottom** of the dashboard, below the Tier/Milestones grid and the Circle-join/Intros grid. Full-width card.
- Live verified: Cohort total 169 · Academy 86.4%, VIP 7.1%, Academy Private Plus 5.9%, Upgrade VIP 0.6% (sum = 100%). On Circle 116 / 169 (68.6%). Intros 21 / 169 (12.4%).

### 2026-04-29 — Coach Activity space switch (apr-26) + admin-editable space config
- **Switched Recorded-Answer-Review tracking from `2513456` (`/c/recorded-answer-review-march/`) → `2529508` (`/c/recorded-answer-review-apr-26/`)** per team confirmation. Note: at switch time the old space had 14 posts since 4 Apr, the new space had 0 — Coach Activity will appear empty until students start posting in apr-26, which is the intended behaviour during the transition.
- **Made Circle space IDs admin-configurable** so future cohort transitions don't need a code change:
  - New `app_settings.coach_spaces` doc with: `recorded_answer_space_id`, `interview_support_space_id`, `recorded_answer_start`, `interview_support_start`. Defaults baked in for current apr-26 cohort.
  - `GET /api/settings/coach-spaces` (any auth) + `PUT /api/settings/coach-spaces` (admin-only). PUT busts the `coach_activity:summary` SWR cache so changes take effect on next dashboard load.
  - `coach_activity.fetch_coach_activity_summary(db)` now reads from settings (with constant fallback if DB is unavailable).
  - Settings → Cohort tab: new "Coach Activity — Circle spaces" panel with 4 inputs (2 space IDs + 2 start dates), Save button, helper text explaining how to find a space ID.

### 2026-04-29 — Admin → Users team_member linking UI
- **`/admin/users` response** now includes `team_members: [{id, name}]` for the dropdown.
- **`PATCH /admin/users/{id}`** accepts `team_member_id` (string to link, empty string/null to unlink). Validates target team_member exists → 400 on unknown ID.
- **Admin → Users UI**:
  - Each non-admin user row has a "Team member" dropdown listing all team_members + "— Not linked —".
  - Amber badge in panel title: "⚠ N not linked" (hides when 0).
  - Inline warning "Can't edit any rocks until linked" shown beside unlinked user dropdowns.
- **Tests**: 14/14 pass in `test_iteration8.py` (added 3 new: team_members exposed, admin can link/unlink, invalid ID rejected).

### 2026-04-29 — DnD metric reorder + per-user rock edit + quarter archiving
- **Metric drag-and-drop reorder** (Settings → Metrics): admins drag metric rows within each category using `@hello-pangea/dnd`. Optimistic UI + auto-rollback on error. New endpoint `PATCH /api/metrics/reorder` (admin-only) accepts `{"order": [{id, order}, ...]}` and bulk-updates the `order` field.
- **Per-user rock edit restriction**:
  - Added `team_member_id` field to `User` model. Idempotent startup migration `_autolink_users_to_team_members()` links users to team_members by name (exact, then substring fallback). 4 users auto-linked on first run: Arub, Oksana, Coralie, Anoop (→ "Anoop").
  - `/auth/me` and `/auth/refresh` now include `team_member_id`.
  - Rock `PATCH` + `DELETE` guards: admin always passes; non-admins must have `team_member_id == rock.owner_id`. Attempts to reassign `owner_id` or change `quarter` by non-admin are silently stripped.
  - Frontend: rock status pills are `disabled` + muted for rocks user can't edit; notes textarea locked; "Add notes" toggle becomes "No notes".
- **Quarter archiving**:
  - `app_settings._id="active_quarter"` stores the current active quarter (default = most-recent quarter).
  - `GET /api/rocks/quarters` now returns `{quarters[], active}`; admin-only `PUT /api/rocks/active-quarter` to change it.
  - Non-admins can't create or edit rocks outside the active quarter. Admin remains unrestricted.
  - UI: Settings → Rocks has an "Active quarter" selector panel. Quarterly Rocks page shows "Q2 2026 · Active" in the selector, and a read-only banner + lock badge appear when viewing an archived quarter.
- **Tests**: 11/11 pass in `/app/backend/tests/test_iteration8.py` covering all three features (reorder swap, non-admin 403, team_member_id auto-link, Arub-edits-own-rock success, Arub-edits-other-rock 403, owner_id strip, admin bypass, active-quarter GET/PUT, archived-quarter 403).

### 2026-04-29 — server.py route refactor (Phase 2) + /api/auth/refresh + Q8 confirmed
- **Phase 2 refactor complete**: extracted ~40 route handlers from `server.py` into `/app/backend/routes/` feature modules:
  - `routes/team.py`, `routes/rocks.py`, `routes/scorecard.py` (metrics + weekly values + auto-compute), `routes/sync.py`, `routes/students.py`, `routes/interviews.py`, `routes/coach.py`, `routes/cohorts.py`, `routes/launches.py` (CRUD + analytics + pace + comparisons + onboarding-gap + phase-breakdown).
  - Each module owns its own `APIRouter(prefix="/api")` and is mounted in `server.py` via `app.include_router(...)`.
  - **`server.py`: 2082 → 966 lines (-54%)**. Now retains only auth, admin/users, settings, scheduler, lifecycle, seeders/migrations, root.
  - Zero behaviour change. All 19 smoke-tested endpoints return 200; 24/24 latest pytest pass; lint clean. Every dashboard page loads with zero alerts.
- **`POST /api/auth/refresh`**: mints a fresh access_token + rotates refresh_token using the httpOnly refresh cookie. Returns the user payload (with admin board_access expanded) so the client stays in sync without a follow-up `/auth/me`. Validated: 200 with valid cookie, 401 without.
- **Q8 vs submission-date — confirmed resolved**: `compute_number_of_interviews` already uses Monday's `Interview Date` column (the actual interview date) — not Tally submission date. The new `compute_results_from_this_weeks_interviews` provides the cohort follow-through view (interview-date based). Together they cover both signals.

### 2026-04-29 — server.py foundation refactor + Settings cohort milestones tab + Results Received goal
- **Foundation refactor (Phase 1 of /backend/routes/ migration)** — extracted shared building blocks from `server.py` (2082 → 1761 lines, -321):
  - `/app/backend/db.py` — single `motor` client + `db` handle.
  - `/app/backend/auth_utils.py` — bcrypt + JWT helpers (`hash_password`, `verify_password`, `create_access_token`, `create_refresh_token`, `set_auth_cookies`, `decode_access_token`).
  - `/app/backend/deps.py` — FastAPI dependencies (`get_current_user`, `require_admin`, `require_board`) + board constants (`ALL_BOARDS`, `ADMIN_ONLY_BOARDS`, `user_has_board`).
  - `/app/backend/models.py` — all Pydantic models (auth, team, metrics, weekly values, rocks, launches, daily registrations).
  - `server.py` now imports from these. Zero behaviour change. 24/24 latest pytest pass; all key endpoints return 200; lint clean.
  - Phase 2 (route-by-route extraction into `/backend/routes/launches.py`, `/students.py`, `/interviews.py`, etc.) deferred — to be done with full regression testing per route group.
- **Settings → Cohort tab**: admin-editable 5 milestone tag names. New backend module `settings_store.py` (Mongo `app_settings._id=cohort_milestones`). Endpoints: `GET /api/settings/cohort-milestones` (any auth user) + `PUT /api/settings/cohort-milestones` (admin-only, validates exactly 5 non-empty strings). Frontend: new `<CohortMilestonesSection />` tab in Settings, reset-to-defaults button. `EngagementBar.jsx` now loads milestone names dynamically (cached in module memory; cache invalidated on save).
- **Results Received goal backfilled to 50%**: idempotent migration `_backfill_results_received_goal()` runs on startup. Sets goal only if currently `None` AND format is `percentage` (defensive — won't clobber an admin-set value).

### 2026-04-29 — New scorecard metric: Results From This Week's Interviews
- Added 7th auto-computed Weekly Scorecard metric: **"Results From This Week's Interviews"** (% of students whose Monday `Interview Date` is this week who have submitted a Tally result form *at any time*). Complements the existing `Results Received` (which is submission-date based).
- Backend: new `compute_results_from_this_weeks_interviews()` in `scorecard_auto.py`; reuses `tally_lookup.get_cached_submissions(db)` (24h TTL) so it's near-free to compute. Wired into `COMPUTE_MAP`.
- Idempotent migration `_ensure_results_from_this_weeks_metric()` runs on startup — inserts the metric (SOCIAL PROOF · Oksana · goal 80% · format percentage) only if it doesn't already exist.
- Live verified: w/c 21-Apr-2026 returns **57.1% (12/21)** — vs `Results Received` at 52.4% (11/21). Late reporters whose interview was last week but submitted this week now get counted.

### 2026-04-29 — Private Tier Utilisation + Cohort Engagement Bar + Tier mismatch fix
- **Private Tier Utilisation widget** on `/interviews` (top of page): flags Private Plus + VIP students with an upcoming interview in the next 7/14/30 days who haven't used enough of their video / call allowance. Compact table (student · tier · interview · videos used · calls used · action needed). Summary pills per tier. Collapsible "On track" section. Bound to existing Private window selector.
  - Backend: `GET /api/interviews/private-tier-utilisation?days={7|14|30}` (`require_board('interviews')`). Returns `{summary_by_tier, flagged[], on_track[], window_days, last_refreshed}`. SWR-cached 30 min via `_stale_while_revalidate`.
  - Logic: Private Plus on_track if `videos ≥ 50% allowance OR calls ≥ 1`. VIP on_track if `videos ≥ 33% allowance AND calls ≥ 2`. Allowances: PP 15 vids + 1 call; VIP 30 vids + 5 calls. Calls counted from Calendly events whose name matches "AYCI 1:1", "AYCI VIP", "AYCI Bonus Call", or "AYCI Mock" (org-wide, last 365 d, per-email).
  - 16/16 pytest pass. Live data: 12 Private Plus + 2 VIP students in 14-day window.
- **Cohort engagement progress bar** on Student Lookup: 5-step bar showing which Circle milestone tags the student has earned. Tags: USP Guru → Verified Examples Badge → Senior-Level Thinker → Job Mastermind → Authentic Self. Locked-icon fallback when student has no Circle account. Sits between Coach Summary and Quick Links.
- **Bug fix — Monday tier mismatch (Deepika Reddy)**: When a student's Circle/Stripe email differs from their Monday email (e.g. Circle: `deepika.t.reddy@gmail.com`, Monday: `dtreddy@doctors.org.uk`), the unified lookup now passes the candidate's name as a fallback hint. `monday_lookup` does email lookup first, then falls back to a name-column search if email returns nothing. Frontend pickSuggestion / runLookupForEmail now forwards the name. Verified live: Deepika Reddy → tier "Upgrade Private Plus" surfaces correctly.
- **Bug fix — wrong COL_TIER constant**: `private_tier_utilisation.py` and `scorecard_auto.py` were referencing the old `color_mkpkrnz0` Monday column ID. Updated to the current `dropdown_mkqxgqbq` (matches `cohort.py` and `upcoming_interviews.py`).
- **Bug fix — wrong COL_VIDEOS_SUBMITTED**: `private_tier_utilisation.py` had `numbers_mkqxbf38`; corrected to `numeric_mkxfq65c` (matches upcoming_interviews.py).

### 2026-04-27 — Mobile Quarterly Rocks + PWA installable
[older entries omitted for brevity — see git history]

## External integrations in use
| Platform   | Env var              | Purpose                                                 |
|------------|----------------------|---------------------------------------------------------|
| Transistor | TRANSISTOR_API_KEY   | Weekly podcast downloads                                |
| ConvertKit | CONVERTKIT_API_SECRET| Subscribers, tags, CTR, student lookup                  |
| Stripe     | STRIPE_API_KEY       | Revenue metrics, student payment history                |
| Circle     | CIRCLE_API_TOKEN     | Community members, activity, milestone tags            |
| Monday.com | MONDAY_API_TOKEN     | Academy Members board, student columns                 |
| Tally      | TALLY_API_KEY        | Form submissions (interviews, results)                 |
| Calendly   | CALENDLY_TOKEN       | Scheduled events, past calls per invitee, AYCI 1:1/VIP/Bonus/Mock private call counts |
| YouTube    | YOUTUBE_API_KEY      | Podcast playlist views                                  |
| Google Drive | GOOGLE_SERVICE_ACCOUNT_FILE | Private-tier doc summaries (Claude AI)        |
| Anthropic  | EMERGENT_LLM_KEY     | Claude Sonnet 4.5 doc summaries                        |

## Prioritised backlog
**P1**
- CSV scorecard export.
- Push notifications for SLA breaches.
- Add team_members for "Regression User" + "Test Coach" (or ignore — they're test accounts).
- Add a team_member for Becky Platt so her admin account can edit her rocks.

**P2**
- Push notifications for SLA breaches.
- "Sync preview" — show what would be pulled without writing.
- Per-user rock-edit restriction (currently any authenticated user can update any rock).
- CSV export of scorecard.
- Real-time updates via WebSocket for Monday live meetings.
- Email/Slack digest reminder before Monday meeting.
- Cosmetic: `<span>` inside `<option>` hydration warning in UpcomingInterviews.jsx Selector.
- Tighten CORS_ORIGINS.

## Next tasks
- Settings → Cohort Milestones tab (P1).
- `server.py` route-folder refactor (P1).


### 2026-04 — Mobile Quarterly Rocks + PWA installable (Apr 27)
- **Quarterly Rocks mobile-friendly**: each owner card is now collapsible on phones (tap header to toggle, chevron rotates, lg+ stays always-open). Owner header gained a 3-dot status summary (off-track / on-track / done counts) so coaches can see a member's whole quarter in one glance without expanding. Card padding tightened on `<sm` (`px-4 py-3` vs `px-5 py-4`). Status pills get a slightly larger tap target on mobile.
- **PWA installable**: new `/public/manifest.json` (standalone display, AYCI icon, navy theme, portrait-primary, 192×192 + 512×512 icons), `/public/sw.js` (no-op pass-through service worker that satisfies Chrome's installability criteria without caching stale dashboard data), Apple iOS meta tags (`apple-mobile-web-app-capable`, status bar style, AYCI title), and SW registration in `src/index.js`. Verified live: manifest serves 200, SW reaches `activated` state. Coaches can now "Add to Home Screen" on iOS or use Chrome's install prompt to launch the dashboard full-screen with the AYCI icon.


- New `<MobileScorecard />` component shown only on `<sm` (≤ 640 px) viewports; desktop table is hidden via `sm:hidden`/`hidden sm:block`. Cards group by category (Growth → Conversion → Revenue → Social Proof → Delivery) matching the desktop sort order.
- Each card: owner avatars · metric name + goal · this-week's value (colour-coded on-track / off-track) · sparkline of the visible weeks. Tap to expand → full week-by-week list with the same in-place edit (reuses `startEdit` / `commitEdit` / `onCellKey` so behaviour matches desktop exactly).
- Owner filter on mobile is a "Filter by owner" dropdown disclosure (option 4b — saves vertical space) instead of the wide chip row used on desktop.
- All editing capabilities preserved on mobile (option 2a). 20/20 metric cards verified rendering at 390 × 844 viewport; lint clean.

 + Coach name resolution + Mobile nav (Apr 27)
- **Webinar registrations** now use the canonical `[AYCI <CODE>] Webinar - Registered - All` tag for the headline `total` count instead of summing per-source tags. The per-source list still drives the breakdown chart but no longer inflates the total when subscribers are tagged on multiple source tags. APR-26: 1479 (was 1534).
- **Phase breakdown** rebuilt to assign each calendar day to **exactly one** phase (the latest phase whose start is on or before that day, capped by the final phase's end date). Eliminates the double-counting that occurred on shared boundary days like 20 Apr (which used to count toward both `early_access` and `flash_sale`).
- **Coach name resolution** for `/coach-activity`: real Circle accounts (e.g. "Anoopkishore Chidambaram") now resolve to their roster name via email match → exact lowercase → alias contains → SequenceMatcher ratio ≥ 0.82 with last-name token guard. Anoop now correctly shows 14 / 14 replies on Recorded Answer Review.
- **Recorded Answer Review** space ID switched from `2529508` (provisioned but empty) to `2513456` (where the cohort is actually posting — 14 active videos from 6 students).
- **Student Lookup autocomplete prefetch**: hovering a name suggestion for 200 ms warms the unified-lookup endpoint for that email, so the click is sub-100 ms. Session-deduped to avoid re-firing.
- **Mobile-friendly nav**: `<lg` viewports now show a sticky brand top-bar with a hamburger that opens a slide-in drawer (with backdrop). Drawer auto-closes on route change. Heroes and page padding scale down at `sm:` and below; the existing scorecard table already had horizontal scroll.


- New `/coach-activity` board (`coach_activity` permission key) for the coaching team. 30-min SWR cached. Sidebar entry with `MessageCircle` icon. Granted to all 5 provisioned team users + the test coach account.
- **Recorded Answer Review section** (Circle space `2529508`, since 4 Apr 2026): per-day post bar chart, replies-per-coach bar list, two flag panels — "Awaiting coach reply > 48 h" and "Posting > 3 / week".
- **Specific Interview Support section** (Circle space `2529509`, since 23 Apr 2026): same shape; Tessa is currently doing all 5 of 5 replies.
- **Private tier video submissions section** (Monday board `5083952249`): 4 KPI tiles — total submitted / replied / new / unassigned — plus assignments-per-coach via the Monday "Assigned to" people column. Resolves person IDs to names via a single `users(ids:[])` query.
- **Coach roster** (canonical names, lowercased lookup with whitespace-tolerant fallback): Zinnirah Zainodin, Anne Beh, Charlotte Wyeth, Anoop Chidambaram, Kat Priddis, Tessa Davis, Becky Platt.
- New backend module `/app/backend/coach_activity.py`. `analyse_circle_space(space_id, start_date, label)` paginates posts and fans out comment lookups concurrently (semaphore=8). Counts UNIQUE posts each coach has replied to, not raw comment count.
- Endpoint: `GET /api/coach-activity/summary?refresh=true` — returns `{coaches, recorded_answers, interview_support, private_videos}`. Each Circle section has `{label, space_id, window, total_posts, total_unique_authors, per_day, per_coach, unanswered, rate_limited, last_refreshed}`.

### 2026-04 — Self-serve change-password + brand heroes + past-coaches + hover prefetch (Apr 27)
- **Self-serve change password**: `POST /api/auth/change-password` (current + new). Min 8 chars, must differ. New `/profile` page with form + role/email summary card. New "My profile" button in sidebar. Tested: wrong/short/identical/valid all return correct status; old login fails after change. (12/12 backend pytest cases PASS.)
- **Reusable HeroBanner** (`/components/HeroBanner.jsx`) with three brand presets:
  - `launch` — navy → indigo, cyan accent (existing).
  - `cohort` — magenta → purple (`#7B1FA2 → #C2185B`), pink accent.
  - `at_risk` — amber → orange (`#B45309 → #F59E0B`), peach accent.
  All three pages refactored to use it; rotated AYCI watermark + radial glow consistent across boards.
- **Upcoming Interviews — past coaches per student**: each card now shows "SPOKE WITH · Tessa Davis · Becky Platt ×3" pills surfacing prior Calendly hosts. New `fetch_past_coaches_bulk(db, emails)` helper in `upcoming_interviews.py` — concurrent (semaphore=6) Calendly lookups with 24 h per-email cache (`cache.calendly_past_hosts:{email}`), bounded to 200 events / 365 days lookback per student. Cold call ~3 s for 27 students; warm <500 ms.
- **Hover prefetch**: new `<PrefetchNavLink>` wraps `NavLink`. Sidebar nav links debounce-fire (200 ms) the destination's primary GET on `mouseenter`/`focus`. Session-level dedupe so one hover per nav per session. Endpoints prefetched: `/launches`, `/interviews/upcoming`, `/students/at-risk`, `/cohorts/labels`, `/scorecard`. Result: clicked dashboards feel instant because the SWR cache is already warm.


- 5 real team members created via `/api/auth/register` as `user` role with explicit `board_access`:
  - **Full access (7 boards)**: Arub Yousuf, Oksana Demchenko.
  - **All except `launches`**: Coralie Fairon, Becky Platt, Anoop Chidambaram.
- Temporary password for all 5: `Welcome@AYCI2026`. Login verified for each (HTTP 200, board lists round-trip correctly via `/api/auth/me`). See `/app/memory/test_credentials.md`.

### 2026-02 — MVP + auto-sync
- JWT auth with bcrypt + httpOnly cookies (access_token 24 h + refresh_token 7 d).
- Admin auto-seeded on startup (`admin@ayci.com` / `Admin@2026`).
- 7 team members, 19 scorecard metrics, 17 Q2-2026 rocks, 3 launches seeded.
- Weekly Scorecard, Quarterly Rocks, Launch Dashboard, Settings (5 tabs).
- External-source connectors (connectors.py): Transistor.fm, ConvertKit v3, Circle, Monday.com (GraphQL), Stripe, YouTube v3, Tally, Calendly.
- APScheduler weekly cron 06:00 Europe/London writes last-Monday bucket.
- `/api/sync/discover` + `/api/sync/run` + Settings UI for per-metric source config.

### 2026-04 — Sparkline + Current-week fix (Apr 23)
- Favicon + page title → "AYCI Dashboard".
- `lastNWeekStarts()` now returns only *completed* weeks — the current in-progress Monday is hidden from the scorecard grid entirely.
- Sparkline slice realigned to `weeks.slice(0, 8)` so the trend endpoint is consistent with the leftmost grid column.
- Manual `/api/sync/run` now defaults to last Monday (matches scheduled cron).
- YouTube podcast-views connector switched from whole-channel uploads playlist to the podcast playlist `PL0bP7vpCkl7eFnlvRgsdJhWbT52tROqI-`.

### 2026-04 — Unified Student Lookup (Apr 23)
- New `/api/students/lookup?email=` route — fans out `asyncio.gather` across Monday, Circle, Stripe, ConvertKit, Calendly. Partial failures isolated per platform.
- `backend/student_lookup.py`: per-platform lookup helpers; Monday uses `items_page_by_column_values` server-side filter (with capped fallback scan).
- Circle member list (~3,832 records) cached in Mongo `circle_members_cache` — slimmed to ~200 B/record to stay under 16 MB doc limit; 24 h TTL; pre-warms in background on startup.
- `POST /api/students/circle-cache/refresh` for manual refresh.
- New frontend page `/students` with: search bar, identity header, 5 platform cards (primary/highlighted fields + "Show all fields" expander for Monday). Sidebar nav entry added.
- End-to-end tested with real student `andreea.gavrisan@gmail.com` — all 5 platforms return Found in ~1.3 s. Fake email returns all Not Found in ~1.4 s.

### 2026-04 — Cohort Dashboard + Google Drive doc summaries (Apr 24)
- `/api/cohorts/summary?cohort=April 26` — new endpoint. New/Legacy split now from ConvertKit tags (authoritative). Circle "Introduce Yourself" space post count cross-referenced by email. Cohort data from Monday board.
- New `/cohort` frontend page with tier split, milestone progress, top specialities, Circle join rate, Circle intros rate. Cohort dropdown selector.
- `/api/students/drive-summary?email=&name=` — Google Drive (service account) + Claude Sonnet 4.5 summarisation of private-tier docs. 24 h Mongo cache. Graceful handling of shortcut-target 404s with hint to share with service account.
- `PrivateDocCard` on Student Lookup — only renders for non-Academy (private-tier) students. On-demand "Load" button → AI summary + link to full doc.
- Google service account email for folder sharing: `ayci-drive-reader@ayci-dashboard.iam.gserviceaccount.com`
- Env vars added: `GOOGLE_SERVICE_ACCOUNT_FILE`, `GOOGLE_DRIVE_PRIVATE_TIER_FOLDER_ID`, `EMERGENT_LLM_KEY`.

### 2026-04 — Launch Dashboard hero + brand watermark (Apr 27)
- New full-width hero on `/launches`: brand navy → indigo gradient (`#182E87 → #4457B6`) with the giant rotated AYCI icon ghosted at ~7% opacity in the top-right corner and a soft cyan radial glow bottom-left.
- White "April 2026" headline + cyan "LAUNCH" eyebrow + launch picker dropdown on white card sit cleanly on the gradient.
- Lifts the dashboard from "themed correctly" to "feels like the AYCI marketing site".

### 2026-04 — Student Lookup coach revamp + blank-tier audit (Apr 27)
- **Cards removed**: ConvertKit, Monday Members, Stripe Payments — were redundant with the new coach-focused panels.
- **Calendly card rewrite**: now shows **Upcoming** + **Past** sections, each event displays the host's name (e.g. "with Tessa Davis"). Backend `calendly_lookup` now fetches both past and future events (status=active) and pulls host info from `event_memberships`.
- **NEW Signup history & cohorts card**: Stripe payment dates + amounts + descriptions (the dates the student signed up / upgraded), plus their Circle cohort tags.
  - Backend: `stripe_lookup` now also returns a flat `charges[]` list (id, created ISO, amount in pence, currency, description, receipt_url).
- **NEW Quick links bar**: chips linking to **Private chat** (Monday `text_mky9xzew`), **Google Doc** (resolved via fast `find_student_doc_link` — 24 h cache, no LLM call), and **Monday record**. Drive link added to `/api/students/lookup` payload as `drive: {found, web_view_link, name}`.
- **Tally Past Interviews** card unchanged (already shipped earlier).

### 2026-04 — Blank-tier audit (Apr 27)
- 2010 students on the AYCI Members Monday board; **221 (~11%) have a blank Tier dropdown**.
- Only **1 blank-tier student** has an upcoming interview in the next 30 days (Yealin Chung, 2026-04-29). After the earlier "blank → Academy" fallback fix she is correctly bucketed in Academy, so no other team-facing impact.

### 2026-04 — Tier blank → Academy fallback (Apr 27)
- **Bug fix on Upcoming Interviews bucketing**: students whose Monday Tier dropdown was blank were falling through to the Private list (e.g. Yealin Chung). The classifier `is_pure_academy` now treats an empty tier as plain Academy — matches the team's mental model where the dropdown is often unset for vanilla Academy students.
- After the fix: 19 Academy / 6 Private (was 18 / 7).

### 2026-04 — Per-user board access (Apr 27)
- **Granular board access per user**. Admins have everything; "user" role gets explicit access only to the boards an admin grants them.
- **Boards**: `weekly_scorecard`, `quarterly_rocks`, `launches`, `cohort`, `interviews`, `students`, `at_risk`. `settings` is admin-only and never grantable.
- **Backend**:
  - `User` schema gained `board_access: List[str]`.
  - New `require_board(name)` dependency factory + `user_has_board(user, board)` helper.
  - Sensitive endpoints (`/students/*`, `/students/at-risk`, `/cohorts/*`, `/interviews/upcoming`) now return **403** if the caller doesn't have the matching board.
  - New admin endpoints: `GET /api/admin/users`, `PATCH /api/admin/users/{id}`, `DELETE /api/admin/users/{id}`.
  - `/api/auth/register` (admin-only) now accepts `board_access` array.
  - `/api/auth/me` returns the user's effective board list (admins get the full list including `settings`).
  - Last-admin safety: backend rejects demoting/deleting the only remaining admin.
  - Migration: existing users backfilled with empty `board_access`.
- **Frontend**:
  - `AppShell` now filters sidebar nav entries by `userCanAccess(user, board)`.
  - New `BoardGuard` route wrapper in `App.js` shows a polite "Access not granted" page (`/pages/NotAuthorized.jsx`) with a fallback link to the user's first allowed board.
  - Settings → Users tab rebuilt as a full management screen: invite form (with role + board checkbox grid), existing users list with role selector, per-board toggle chips, delete button.
- **Test coach account** (`coach@ayci.com` / `Coach@2026`) seeded for permission testing — has Weekly Scorecard + Interviews + Students only; should see 403 on at-risk/cohorts.

### 2026-04 — Stale-while-revalidate caching (Apr 27)
- **All slow endpoints now cached in Mongo with stale-while-revalidate semantics**: if cache is fresh (<60 min) the response is sub-100 ms; if stale, the cached payload is returned immediately and a background task refreshes silently. Cold cache only hits the user once per launch.
- Endpoints affected:
  - `/api/launches/{id}/sales` — 12 s → **0.1 s**
  - `/api/launches/{id}/registrations` — 1.9 s → **0.1 s**
  - `/api/launches/{id}/comparison` — 50 s → **0.1 s** (warm)
  - `/api/launches/active/pace` — uses `cached_fetch_sales` under the hood
  - `/api/interviews/upcoming` — 3.6 s → **0.1 s**
- New helper `_stale_while_revalidate(db, key, ttl_min, fn)` in `launches.py` — re-usable for any future expensive endpoint.
- New `cached_fetch_sales` and `cached_fetch_registrations` keyed by `(start, end)` so all 5+ callers (sales endpoint, comparison, pace, phase-breakdown, year-overview) share the same cache.
- Pre-warm on startup: 15 s after boot, the active launch's sales + regs are computed and cached so the first dashboard visitor sees instant responses.
- Background refresh tasks deduped by cache key — multiple stale hits don't trigger duplicate Stripe scans.

### 2026-04 — Signups deduped per person (Apr 27)
- **Signups now count unique people, not charges**. Anyone who signed up + upgraded in the same launch window is now counted **once**, not twice.
- APR-26 numbers post-fix: **170 unique signups** = 162 new + 8 legacy (was 250 / 240 / 10 charge-based).
- Conversion rate jumps to ~78% (170 unique signups / 218 unique webinar regs) — was 56% under charge-based count.
- `by_tier.count` is now also unique customers per tier; raw charge count surfaced as `charges` for transparency.
- Phase-breakdown cache invalidated and will repopulate within 2-3 min on the next dashboard load.

### 2026-04 — Launch Dashboard 2.2: Boost-excluded sales + phase comparison (Apr 27)
- **Boost & Go excluded** from launch revenue / signups / by_tier breakdown — the team no longer counts it as a launch product.
- **AOV recalculated** as revenue per UNIQUE customer (was per-charge): £636 (was £437 in v2.1).
- **Signups split into new vs legacy**: backend now returns `new_signup_count` + `legacy_count` + `total_count`. KPI tile shows all three.
- **Sales breakdown by tier** now includes `pct_of_revenue` per tier; UI shows the % chip in each tier card under the chart.
- **Year Overview strip removed** from /launches.
- **Comparison auto-loads** on launch switch (no more "Compare to previous 2 launches" button).
- **Sales cumulative chart**: current launch line is now 4 px solid brand indigo with dots at each data point; previous launches are 1.5 px dashed grey/slate so the difference is unmistakable.
- **NEW Phase breakdown table**: side-by-side comparison of revenue + signups + webinar regs for each phase (in_between_start / early_access / flash_sale / webinar / open_cart / close_cart / in_between_end) across the current launch + previous 2.
  - Backend: `GET /api/launches/{id}/phase-breakdown` — cached 24h in `cache` collection. Pre-warmed on startup (60 s after boot) + daily APScheduler job at **05:25 London**.
  - Returns `computing: true` placeholder if cache is empty + triggers background warm; the response is sub-200 ms once cached.
- **Pace forecast** more prominent — sits directly under the KPI grid (was already there but the previous user could not see it; layout reorder makes it obvious).

### 2026-04 — Tally cache TTL bump + Kajabi dropped (Apr 27)
- Tally interview-form cache bumped from 30 min → **24 h** (interview submissions trickle in slowly; no need for sub-hour freshness).
- New daily APScheduler job `daily_tally_refresh` at 05:20 London — refreshes the Tally cache every morning before the team's first lookup.
- **Kajabi dropped from backlog**: Stripe is the source of truth for payments; trial-access bugs are rare and not worth a separate connector.

### 2026-04 — Coach view + Tally interview history (Apr 27)
- **Student Lookup → Coach view tile** (new): tier badge, calls remaining, videos remaining, mocks left, last call date. Pulled live from Monday allowance columns (`numeric_mkxfvz1k` total videos, `numeric_mkxfq65c` videos used, plus the 4 call / 3 mock / 6 bonus colour columns). Shown right under the identity header so coaches see what matters in one glance.
- **Tally interview history (form `nGyGj2`)**: new connector `tally_lookup.py` that pulls all submissions every 30 min into `cache` and serves single + bulk lookups in-memory. Auto-discovered question IDs: Email `A2XYDB`, Interview Type `BdRYD7`, Date `keP4W6`, Hospital `VPGQ4y`, Speciality `gqDzY1`, Outcome `G9W5N2`, Questions `qGLl7O`.
  - Returned per student: `{type: "Locum"|"Substantive", history_count, history: [...]}`.
- **Student Lookup**: new "Tally — Past interviews" card listing every prior submission (date, type badge, hospital, speciality, outcome).
- **Upcoming Interviews**: each student card now shows a **Locum / Substantive** badge + a "**N PRIOR**" history pill. Bulk Tally lookup so the page stays under 2 s.

### 2026-04 — Launch phases v2 (Apr 26)
- **All 4 launches now have the canonical AYCI phase structure**: NOV-25, FEB-26, APR-26, JUN-26 (newly added).
- Phases per launch (7): in_between_start → early_access → flash_sale → webinar → open_cart → close_cart → in_between_end. All start/end times use the team's agreed cut-offs (08:00 flash sale, 20:00 webinar, 12:00 cart close).
- `legacy_upgrades` field dropped; `early_signups` renamed to `early_access`; single `in_between` split into `in_between_start` (revenue tracking starts here, 20 days before webinar) and `in_between_end` (cart-close end → next launch).
- Idempotent migration `_migrate_launches_v2()` runs on every startup — preserves launch IDs so pace/year-overview caches keep working.
- Settings → Launches edit dialog now exposes 7 phase pickers in the new order.
- Launch Dashboard auto-selects the **active** launch (today inside start/end), not the latest by start_date.

### 2026-04 — Launch Dashboard 2.1 + brand polish (Apr 26)
- **Launch Dashboard rebuilt for the post-webinar revenue focus**:
  - Six KPI cards in priority order: Revenue, Signups, Webinar regs, Conversion, **EPL** (revenue / unique regs), **AOV** (revenue / signups).
  - Pace forecast now sits directly under the KPIs.
  - Phase timeline collapsed into a single horizontal pill row to save space.
  - Webinar registrations chart + UTM source breakdown moved to the bottom (lower priority once cart is open).
- **Backend `fetch_sales` rewritten**:
  - Each Stripe charge classified as `signup` (first-ever paid) or `upgrade` (existing customer + ≥ £90 or "upgrade" keyword); small recurring renewal charges from existing customers are now **excluded** from launch sales count and revenue.
  - Returns `by_tier` (Academy / Private Plus / VIP / Boost & Go / Private Plus upgrade / VIP upgrade / Other signup / Other upgrade). Still also returns `by_product` as a back-compat alias.
  - Customer prior-paid status checked in parallel via `asyncio.gather` to keep the endpoint fast.
- **Apr 26 launch numbers post-fix**: 236 signups+upgrades (was 239), £103,165 revenue (was £103,237), EPL £70/lead, AOV £437.
- **Brand polish**: AYCI icon now rendered in white in the sidebar + login (CSS `brightness(0) invert(1)` filter) so it shows up on the navy background.

### 2026-04 — Brand alignment (Apr 26)

### 2026-04 — Year overview + Pace sparkline (Apr 26)
- **Year overview strip** added at the top of `/launches`: horizontal timeline with month ticks, click-to-switch launch bars (active highlighted in teal, future in slate, past in grey), today marker. Powered by `/api/launches/year-overview`.
- **Mini forecast sparkline** added inline next to the £ forecast in `PaceTrackerWidget` (shown on Weekly Scorecard): faded grey curves for previous-launch cumulative sales overlaid with the current-launch amber curve, today dot, dashed projection line to forecast endpoint, and dashed best-target reference line.
- **Bug fix**: Cleared stale `pace_cache` entries that lacked the new `current_cumul` / `prev_cumul` series so the sparkline data is now populated.

### 2026-04 — Students at risk + cleanup (Apr 26)
- **`GET /api/students/at-risk`**: high-spend Stripe customers (lifetime ≥ £1,000 over last 365 days) who are dormant on Circle (>30 days since last_seen_at, never logged in, or no Circle account at all). Aggregates Stripe charges by customer, joins against the Circle members cache by email, classifies each high-spender into a `risk_status` bucket. Cached 24h in `at_risk_cache`. Daily APScheduler job at 05:15 London + on-startup background warm. `?refresh=true` triggers async re-scan (Stripe scan takes ~3-5 min).
- **`/at-risk` page**: 4 summary tiles, filter chips (all / dormant / never logged in / no account), search by name/email, sortable table (lifetime, last on Circle, name), avatars + risk badges, deep-link to Student Lookup via `/students?email=…`.
- **Weekly Scorecard widget**: tile next to Pace tracker showing total at risk, dormant vs no/never split, and top 3 high-spenders. Clicks through to the full `/at-risk` page.
- **Sidebar nav**: "Students at Risk" entry with AlertTriangle icon.
- **Student Lookup**: now reads `?email=` query param and auto-runs the lookup so deep-links from the at-risk page land on a populated profile.
- **Cleanup**: Recharts negative-width console warnings silenced (Sparkline now uses fixed dimensions instead of ResponsiveContainer). CORS tightened: dropped the `*` fallback so missing `CORS_ORIGINS` env var fails closed instead of allowing all origins.
- **Backend tests**: 19/19 pytest cases pass against preview URL (auth, schema, sort, threshold, regression on existing endpoints).

### 2026-04 — Launch Dashboard 2.0 + Misc fixes (Apr 26)
- **Launch model upgraded**: now has `code` (Kit tag prefix, e.g. APR-26) and `phases` (7 phases each with start/end datetimes: early_signups, flash_sale, webinar, open_cart, legacy_upgrades, close_cart, in_between). PATCH endpoint added.
- **Live registrations from Kit**: `/api/launches/{id}/registrations` discovers per-source tags `[AYCI <CODE>] Webinar - Registered - <SOURCE>` and aggregates daily counts + by-source totals.
- **Live sales from Stripe**: `/api/launches/{id}/sales` filters charges by launch window, classifies into product tiers (Academy / VIP / Private Plus / Boost & Go etc.), returns daily + by-product breakdown.
- **Comparison vs previous launches**: `/api/launches/{id}/comparison?n_previous=2` returns the same series for the 2 most recent prior launches, all aligned by `day_offset` for chart overlay.
- **Frontend rewrite**: Phase timeline header (current phase highlighted), 4 KPI cards (registrations / sales count / revenue with goal markers / conversion rate), webinar registrations line chart with previous-launch overlays, UTM source breakdown, sales chart with Good/Better/Best reference lines, sales-by-product bar chart. Manual sales editor removed.
- **Settings → Launches → Edit dialog**: code field + 7 phase pickers (datetime-local), all edits via PATCH.
- **Quick fixes**: Upcoming Interviews defaults to Private only with toggle to "All tiers". Cohort total = new+legacy from Kit. Circle bar gradient now uses inline linear-gradient (was broken Tailwind syntax). Student Lookup accepts name search with autocomplete dropdown (`/api/students/name-search`).

