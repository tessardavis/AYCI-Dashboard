# AYCI Academy Team Dashboard — PRD

## Original Problem Statement
Robust customer service support ticket system integrating Tally forms, Gmail, Wati (WhatsApp), Monday.com, Calendly, and Circle.so. Replaces Monday.com Private Tier Video Submissions with a native UI. Adds Slack notifications, Drive document summaries, Calendly booking allowance alerts, AI-generated call briefings, and an AI auto-responder for Circle community DMs.

## Tech Stack
- React 18 + Vite + Tailwind + shadcn/ui
- FastAPI + Motor (async MongoDB)
- APScheduler for cron jobs (Europe/London tz)
- Claude Sonnet 4.5 via Emergent LLM Key for AI features
- Integrations: Stripe, ConvertKit, Gmail OAuth, Wati, Calendly, Monday.com, Slack, Circle.so (Admin + Headless APIs), Zapier

## Implemented Features (latest first)

### 2026-05-17 — Circle DM follow-ups: forwarded + visible badge on the ticket card
- **Forwarding** (see 2026-05-17 entry below): escalated threads now forward subsequent student messages to the linked support ticket as internal notes.
- **NEW — on-card unread badge**: tickets accumulating new Circle DM forwards now show a violet `💬 N new` badge alongside the existing "New" badge on the Kanban card, plus a violet ring around the whole card so the team can spot fresh activity from across the room. Hover-tooltip: "N new Circle DM replies — last X min ago".
- **Backend changes**:
  - `_forward_new_msgs_to_ticket()` now stamps `last_circle_activity_at` and `$inc`s `unread_circle_count` on the ticket
  - `GET /api/tickets/{ticket_id}` clears the badge atomically (`unread_circle_count → 0`, stamps `circle_activity_acknowledged_at` + `_by`) when any coach opens the ticket detail. Global ack — the first responder owns it, matches how the team works.
- **Regression test** extended: pins both `unread_circle_count` and `last_circle_activity_at` get set on forward.
- **Files**: `backend/circle_dm_poll.py::_forward_new_msgs_to_ticket`, `backend/routes/tickets.py::get_ticket`, `frontend/src/pages/SupportTickets.jsx` (KanbanCard badge + ring).


### 2026-05-17 — Escalated Circle DM follow-ups now forwarded to the linked ticket
- **Bug** (reported by Tessa, hit Sehr Khan's thread): once a Circle DM bot escalated a thread (sent holding handoff, opened a ticket), any subsequent student replies were silently dropped. The bot's `_process_thread()` just returned `skipped` for any thread in `escalated` state, so the team only ever saw the original message in the ticket.
- **Fix** (`backend/circle_dm_poll.py::_process_thread`): for threads in `escalated` state with a linked `escalated_ticket_id`, the bot now:
  - Fetches messages newer than `last_seen_message_id`
  - Pushes each STUDENT-sent message into `tickets.notes[]` as an internal-author note (`author_id: "_circle_dm"`), preserving `circle_message_id` for idempotency
  - Re-opens the ticket if it was previously marked resolved/closed
  - Bumps `last_seen_message_id` so we don't re-import on the next poll
  - De-duplicates by `circle_message_id` so a double-poll race never double-appends
- Only **student** messages are forwarded — admin replies stay in Circle (the team uses the ticket as the canonical thread; team-to-team chat in Circle would cause confusing loops).
- `human_takeover` and `tag_excluded` states still skip entirely (intentional — coach is actively handling / student is tagged out).
- New `poll_summary.escalated_forwarded` counter so we can see at a glance how often this is firing.
- **Regression test**: `tests/test_circle_dm_first_sight.py::_scenario_escalated_thread_forwards_followup_to_ticket` covers the forward path (asserts note inserted with right fields, ticket re-opened, last_seen advanced) AND the idempotency guard (second run doesn't double-append).
- **Files**: `backend/circle_dm_poll.py` (forward helper + state-router branch), `backend/tests/test_circle_dm_first_sight.py` (new scenario).


### 2026-05-15 (evening 7) — Coach Activity: daily bars now show counts clearly
- **Counts above every bar**: the Recorded Answer Review and Specific Interview Support charts now render the daily count above each bar (was tooltip-only — required hovering). Days with 0 show a dim "0" so you can see the rhythm at a glance.
- **Weekday labels added** (Mon-Sun) beneath each day-of-month, with weekends visually faded (60% opacity teal bar + muted labels) so the eye automatically separates work-days from weekend bumps.
- **Footer rollup**: "Total X · Avg/active-day Y.Y · Peak Z" plus an inline legend "Weekends shown faded". Average is over active days (excludes zeros so a long quiet stretch doesn't distort the headline).
- **Layout robustness**: count labels reserve the top 18% of the bar height so the tallest bar's number never pushes off-screen; bar minimum height bumped to 4px so even a count of 1 is visible.
- **File**: `frontend/src/pages/CoachActivity.jsx::DailyBars`.


### 2026-05-15 (evening 6) — Eve check-ins: 30-day sparkline + trend delta on each card
- **Inline SVG sparkline** beneath each tier-split card showing the daily pre-interview-only avg score over the last 30 days. Day-by-day with null gaps (days with no replies) rendered as visual jumps. Subtle dashed reference line at 7/10. Endpoint dot highlights the most recent reading.
- **Trend pill** in the card header: compares the avg of the recent 15 days vs the prior 15 days. Shows `▲ +X.X` (emerald) for improvement >0.1, `▼ -X.X` (rose) for decline, `→` (slate) for flat. Hover-tooltip explains the methodology.
- **Robust to sparse data**: when fewer than 2 days have replies, shows an unobtrusive "Not enough data for 30-day trend yet" placeholder instead of breaking.
- **Y-axis fixed at 1-10** (full score range) so both Premium and Academy cards stay visually comparable — a 3-point drop looks like a 3-point drop everywhere.
- **No backend changes** — same `/api/interview-eve/records` endpoint, fetch bumped from limit=20 to 300 to cover the 30-day window.
- **File**: `frontend/src/pages/UpcomingInterviews.jsx` (`Sparkline` component + `buildDailySeries` helper + `GroupStatsCard` extended).


### 2026-05-15 (evening 5) — Eve check-ins: tier-split rollup (Private + B&G vs Academy)
- **Two side-by-side rollup cards** on the eve check-ins widget — a violet "Private + Boost & Go" card and a teal "Academy" card. Each shows Sent / Replied / Pending / Low ≤5 / Avg (pre-interview, with "inc post" sub-label when relevant) for its own group.
- **Group classification**: uses the existing `is_private_tier` flag set at eve-DM send time. Premium = Private Plus + VIP + Boost & Go. Academy = Academy + legacy Silver/Gold.
- **Tier badge on every row** (both replied and pending) — violet for Premium, teal for Academy — so the team can instantly tell who's in which group when scanning the unified list below.
- **File**: `frontend/src/pages/UpcomingInterviews.jsx` (extracted `GroupStatsCard` + `MiniStat` helpers, refactored stats computation into a reusable `computeStats(rows)` function so the same logic produces both group rollups + the overall view).


### 2026-05-15 (evening 4) — Eve check-ins: show replied entries + pre/post-interview split
- **Before**: the widget only listed pending replies. Replied check-ins were invisible — the team couldn't see who scored what, nor verify the average.
- **Now**:
  - **Replies section** lists every replied check-in with the score (color-coded: ≤5 rose, 6-7 amber, ≥8 emerald) plus a **PRE** or **POST-INTERVIEW** badge.
  - **Pre/post classification**: a reply is "post-interview" if `score_received_at` UK date > `interview_date` — at that point the student already knows the outcome and the score is potentially skewed.
  - **Average is computed pre-interview only** (clean signal). When any post-interview replies exist, the avg tile relabels to "AVG · PRE-INTERVIEW" and shows a sub-label "Inc. post: X.X/10". An amber banner explains why those replies are excluded.
  - **Manual-set badge** appears on rows where a coach hand-entered the score (visibility into who/when).
- **No backend changes needed** — the records endpoint already returns `score_received_at` + `interview_date`.
- **File**: `frontend/src/pages/UpcomingInterviews.jsx` (`EveCheckInsWidget` + `Stat` extended with optional `sublabel`).


### 2026-05-15 (evening 3) — Log extra call: corrected to count events, not minutes
**Important correction** based on team feedback: tier allowances are described as *call events*, not *minutes*. VIP = 4×30-min + 1×60-min mock = **5 calls** (the 60-min mock is one event). Private Plus = 1 call. Bonus calls = 1 each. So my initial "60 min = 2 slots" logic was wrong.
- Each manual call now adds **1** to the count, regardless of duration. The duration is kept on the record for the audit trail / team awareness, but doesn't multiply.
- Verified live on preview: a 60-min manual entry on Amal Hashi now adds +1 to `calendly_calls_used` (4 → 4 became 4 → 4… i.e. 3 → 4, over_by 1 → 2), not +2.
- Dialog copy updated to explain the call-event model clearly.
- **Confirmed bonus calls ARE counted**: in `over_allowance_alerts.py::_fetch_all_private_students`, `monday_total_allowance = calls.total + mocks.total + bonus.total`. Students eligible for bonus calls have their bonus column added to the total allowance, and any bonus call they actually book through Calendly is included in the Calendly count (since Calendly counts every event).
- Regression test updated to pin "each manual entry adds exactly 1, regardless of duration" (3 entries of 30/60/90 min → 3 credits, not 6).
- Files: `backend/private_tier_utilisation.py`, `backend/over_allowance_alerts.py`, `frontend/src/pages/UpcomingInterviews.jsx`, `backend/tests/test_manual_call_credits.py`.


### 2026-05-15 (evening 2) — Log extra call: off-Calendly bookings counted towards student allowance
- **Use case**: William Twiggs got an extra 1-hour call (~30 min over his allowance) that wasn't booked through Calendly. The team needs to record this so it counts towards his overall call usage.
- **"Log extra call"** button on Upcoming Interviews → Private Tier Utilisation header. Opens a dialog with: student select (pulled from the widget's own private-tier list), duration toggle (30/45/60/90 min), coach pre-filled to logged-in user, datetime picker (defaults to now), notes. After save, the utilisation widget auto-refreshes.
- **Credits formula**: each manual call contributes `ceil(duration_min / 30)` to the student's call count — 30 min = 1 slot, 60 min = 2, 90 min = 3. Matches how the team thinks about Calendly slots.
- **Folded into BOTH widgets**: `_fetch_private_call_counts` (utilisation widget) and `find_over_allowance_students` (over-allowance widget) both query `db.manual_calls` and add the credits. Verified end-to-end: bumping a real student (Amal Hashi) by a 60-min entry took her `over_by` from 1 → 3 (+2 credits) and reverted on delete.
- **Bug fix**: `today_calls.add_manual_call` was returning the dict mutated by `insert_one` (with `_id: ObjectId` added), causing FastAPI to throw a 500 on success. Fixed by inserting a `dict(row)` copy.
- **Frontend**: reuses the existing `POST /api/today-calls/manual` + `DELETE /api/today-calls/manual/{id}` endpoints (no new routes needed) — visible to anyone with `coach_activity` board access.
- **Regression tests** at `backend/tests/test_manual_call_credits.py` pin the duration→credits conversion (7 edge cases) AND the email-scoping rule (untracked emails must NOT be folded in).
- **Files:** `backend/private_tier_utilisation.py`, `backend/over_allowance_alerts.py` (fold-in helpers), `backend/today_calls.py` (ObjectId fix), `backend/tests/test_manual_call_credits.py` (NEW), `frontend/src/pages/UpcomingInterviews.jsx` (button + `LogExtraCallDialog`).


### 2026-05-15 (evening) — Eve check-ins self-service widget on Upcoming Interviews
- **`<EveCheckInsWidget />`** on `/interviews` page (visible to anyone with `coach_activity` board OR admin). The team can now:
  - See **5-tile rollup** for the last 7 days: Sent / Replied / Pending / Low ≤5 / Avg score
  - Click **"Recover missed scores"** to run the backfill in one click. Shows a clear ✅ recovered / ⚠️ still-pending breakdown inline.
  - For every pending student: type a 1-10 score into the inline input + click Save (or press Enter) to record manually via the existing set-score endpoint. Useful when a student replied with words instead of a number.
  - "Hide details" collapse toggle for when the widget gets noisy.
- **Backend access relaxed** for the three eve-DM routes from `require_admin` → `require_board("coach_activity")`: `GET /records`, `POST /backfill-scores`, `POST /records/{id}/set-score`. All 5 current team accounts (Coralie, Oksana, Arub, Becky, Anoop) have `coach_activity`, so they can all self-serve. `/run-now` and `/preview` stay admin-only (more powerful — actually sends DMs).
- **Tested** as both admin and Test Coach (non-admin) — widget renders and is fully functional for both. Audit trail `score_set_manually_by` captures who set each manual score.
- **Team composition** (per user input 2026-05-15):
  - Team members: Coralie, Oksana, Arub
  - Senior coaches: Becky, Anoop
  - Other coaches (need accounts created): Charlotte, Zinnirah, Anne, Kat
- **Files:** `frontend/src/pages/UpcomingInterviews.jsx` (new `EveCheckInsWidget` + `Stat` components, `useAuth` + `coach_activity` gate), `backend/routes/interview_eve.py` (relaxed access on read+backfill+set-score routes), `memory/test_credentials.md` (Test Coach now has coach_activity).


### 2026-05-15 (afternoon) — Eve-DM score capture ordering fix + backfill v3 + Unicode digits + manual-set + team glossary

**Production deploy 1** — ordering fix (`_process_thread` now runs score capture before lookback guard) + initial backfill. Recovered:
- ✅ Michael Carling — 7/10

**Production deploy 2** — backfill v2 (first-score-wins, scans oldest→newest from `sent_at`). Recovered:
- ✅ Mohammed Elsabbagh — 8/10

**Production deploy 3** — backfill v3 (per_page 20→60, surfaces `all_student_msgs_after_send` for visibility) + manual-set endpoint + Unicode-digit support. Recovered:
- ✅ Henry Walton — 9/10 (set manually — student replied with `⁹` Unicode superscript that the regex didn't match; now permanently fixed)

**Permanent fix for Unicode digits**: `parse_score()` now NFKC-normalises the input before regex matching, so superscripts (⁹, ¹⁰), keycap emoji (9️⃣), and full-width digits (９) all collapse to ASCII before matching. Regression tests at `backend/tests/test_parse_score.py` (5 tests) pin every case.

**Confirmed non-responders** (no student reply at all, no recovery possible): Matt Gray, Afifa Saulat, Trishala Raj, Shailaja Anipindi.

**Special case**: Jemma Boyle sent a substantive Speciality Doctor interview-date question instead of a score — needs Coralie's reply, not bot recovery.

**Team glossary on Settings → Bot**: collapsible help panel explaining every state + button.

- **Files:** `backend/circle_dm_poll.py` (ordering), `backend/interview_eve_dm.py` (NFKC parse_score), `backend/routes/interview_eve.py` (backfill v3 + set-score endpoint), `backend/tests/test_circle_dm_first_sight.py`, `backend/tests/test_parse_score.py` (NEW), `frontend/src/pages/Settings.jsx` (glossary).


### 2026-05-15 — Circle DM Bot: first-sight smart reply + per-thread diagnostic suite + Trust & re-arm
- **First-sight smart reply** (`backend/circle_dm_poll.py::_process_thread`): when the bot first sees a thread, it now distinguishes backlog from a real new conversation. If the inline `last_message` is a **student** message **less than 10 min old**, it minimally-seeds state and falls through to the normal reply path (instead of swallowing the first message). Anything older or admin-sent still seeds silently — backlog protection preserved. Fixes the "I sent a test DM and got nothing" UX.
- **`GET /api/circle/bot/thread-trace`** — read-only, non-mutating simulation of `_process_thread()` with step-by-step trace + a clear `WOULD …` conclusion. Lookup by `thread_uuid` or `student_search`. No Circle POSTs, no LLM calls, no state writes.
- **Lookback-guard breadcrumb**: when `_process_thread()` flips a thread to `human_takeover`, it persists `human_takeover_trigger: {message_id, sender_id, body (full), body_snippet, created_at, cutoff_iso_used, reset_at_at_time, sent_ids_count, sent_bodies_count}` on the thread doc.
- **`POST /api/circle/bot/trust-takeover/{uuid}`** + **"Trust & re-arm" button** on `human_takeover` thread rows: one-click recovery for cross-environment races. Appends the breadcrumbed trigger body to `sent_bodies` and id to `sent_message_ids`, then re-arms. The next poll's lookback guard recognises the message and won't re-trigger takeover. Rejects threads without a recorded trigger (older takeovers — use plain Re-arm).
- **Inline takeover-trigger display**: each `human_takeover` row now shows `Triggered by msg #<id> (<body snippet>)` so coaches can decide between Trust vs Re-arm before clicking.
- **Settings → Bot → "Diagnose a thread"** inline panel: paste name/UUID → see conclusion + full JSON trace. Admin-only.
- **Regression tests** at `backend/tests/test_circle_dm_first_sight.py` pin all three first-sight scenarios + the trust-takeover flow (including the "already active" and "no state doc" guard paths). Passing.
- **Production diagnosis** (2026-05-15): "Test - Coralie" threads — Tessa correctly escalated (playbook_miss), Oksana was seeded-only (now solved by smart-reply), Coralie was in `human_takeover` (cause now traceable via breadcrumb). Boss-tag scoping confirmed correct (only Tessa).
- **Files:** `backend/circle_dm_poll.py` (smart-reply + trace + breadcrumb + `trust_takeover_trigger`), `backend/routes/circle.py` (trace + trust routes), `frontend/src/pages/Settings.jsx` (Diagnose panel + Trust button + inline trigger display), `backend/tests/test_circle_dm_first_sight.py` (NEW).


### 2026-05-13 — Warmer, more human auto-replies (no AI disclosure, signed by coach first name)
- **User feedback:** "Our auto-replies feel a bit robotic — they mention 'this is an auto-response from Coralie Fairon's account' and sign off as 'AYCI Team'. Should feel warm, friendly, signed by the coach, and never call out the automation."
- **Rewrote every customer-facing template** so the student never sees the word "auto-response" and the message reads like the coach wrote it themselves:
  - **Circle DM holding handoff** (bot can't answer, escalates to ticket): _"Hi Ben, thanks so much for getting in touch! 🙏 I've got your message and the team will be in touch within 24 hours. In the meantime, feel free to share any extra context that might help us help you faster. Speak soon, Coralie x"_
  - **AI fallback holding** (when Claude is down): _"Hi Ben, thanks so much for getting in touch! 🙏 I've got your message and I'll come back to you within 24 hours. If it's really urgent, drop us a line at support@medicalinterviewprep.com and we'll jump on it sooner. Speak soon, Coralie x"_
  - **Interview-eve check-in DM**: _"Hi Ben! 💪 Hope you're feeling good about tomorrow's interview. Quick check-in — on a scale of 1 to 10, how supported do you feel heading in? Just pop a number back and if anything's not quite right we'll be in touch tonight to help. You've got this! Coralie x"_
  - **Eve score ack**: _"Thanks Ben! Got you down as 9/10 — sending you all the best vibes for tomorrow. You've got this 💪 Coralie x"_
- **Updated the Claude system prompt** for AI-generated playbook answers so the bot writes _as the coach_ — never refers to itself as automated, opens warmly ("thanks for reaching out!", "great question!"), uses the student's first name, ends with a supportive line ("Hope that helps!" / "Let me know if you need anything else!" / "Speak soon!"), and signs off as `{coach_first} x` on its own line.
- **Removed `_ai_disclosure` helper** entirely — was only used by the escalation handoff. Also removed `Best, AYCI Team` sign-off (was used everywhere).
- **Files:** `backend/circle_dm_poll.py` (`_holding_handoff` rewrite + eve ack rewrite), `backend/circle_dm_bot.py` (system-prompt rewrite + `_holding_reply` rewrite), `backend/interview_eve_dm.py` (`_build_dm_body` rewrite), `backend/routes/circle.py` (fail-open reply text).
- **Note:** Changes apply to NEW messages going forward. Anything already in students' Circle inboxes keeps the old wording.


### 2026-05-13 — Student Lookup: editable name, 30-min cache, 5:30 UK pre-warm, hover-prefetch + eve-DM endpoint fix
- **Editable student name** — pencil affordance on the Student Lookup header. Clicking opens an inline input that PATCHes `/api/students/lookup/{monday_item_id}` to rename the Monday Academy Members item. On save: cache is busted, Circle members cache is updated in-place so name-search picks up the new spelling immediately, and the header optimistically reflects the change. Falls back to read-only when there's no Monday item id. Endpoint validates 2-80 char name.
- **30-min unified-lookup cache** — wraps the existing `GET /api/students/lookup` fan-out (Monday + Circle + Stripe + ConvertKit + Calendly + Tally + Drive). 2nd/3rd opens of the same student within 30 min return in ~250ms instead of ~2-8s (**~8× speed-up** measured on Ben Silver: 2047ms → 242ms). Pass `refresh=true` to bypass. Response includes `_cached: true` + `_cached_at` so the UI can show a fresh-vs-cached indicator if we ever want one.
- **5:30 UK daily pre-warm cron** for ALL private-tier students (every non-Academy tier — Academy Private Plus, Upgrade Private Plus, VIP, Platinum, Boost & Go, 1:1, etc., NOT scoped to upcoming-interview only because the team runs private group coaching sessions on these students). Throttled at 6 students/batch with a 1s pause between batches so the warm-up doesn't trip Stripe/ConvertKit rate limits. By the time the team logs in at 9am UK, every private-tier student opens in <300ms cold-of-day.
- **Hover-prefetch on the Upcoming Interviews board** — hovering any row for >200ms fires the unified-lookup API in the background. By the time the coach clicks through, the response is hot. Module-scoped dedupe so a session of hovering doesn't repeatedly hit the API. Also added a small Search icon next to each student name that links to `/students?email=…`.
- **Header name priority changed** — Monday is now the source of truth (was: Circle first, which truncated to first name only because Circle stores "Ben" not "Ben Silver"). The name-edit affordance only mattered once this priority change lands; together they fix the original "Ben doesn't have his surname" report.
- **APScheduler misfire grace** = 3600s added to both the `interview_eve_dms` (19:00 Mon-Fri UK) and new `prewarm_private_lookups` (05:30 UK) cron jobs. Previously, a backend reload near the trigger window silently skipped that day's run; now any miss within 1h gets caught up on next scheduler start.
- **Eve-DM Circle endpoint fixed** — `_ensure_dm_chat_room` was POSTing to `/chat_rooms` (returns 404). Correct Headless API endpoint is `POST /messages` with body `{chat_room: {kind: "direct", community_member_ids: [<id>]}}`. Fired run-now to backfill tonight's missed 7pm cron: 5/5 DMs successfully delivered to tomorrow's Academy/Silver students.
- **Files:** `backend/server.py` (misfire grace + new cron), `backend/routes/students.py` (cache + edit endpoint), `backend/student_edit.py` (NEW), `backend/student_prewarm.py` (NEW), `backend/interview_eve_dm.py` (Circle endpoint fix), `frontend/src/pages/StudentLookup.jsx` (pencil editor + Monday-first name), `frontend/src/pages/UpcomingInterviews.jsx` (hover-prefetch hook + lookup link icons).


### 2026-05-13 — Enhancement: Student context stripe on the Kanban/table ticket card
- **Why:** Coaches scanning the support-tickets board had no way to tell which tickets were from high-touch Private-tier students with imminent interviews vs. passive Academy members — they had to click each ticket to find out.
- **What:** Added a tiny one-line `<StudentMatchStripe>` rendered under the student name on every Kanban card and Table row. Shows pills for:
  - **Tier** — shortened ("Private+" instead of "Academy Private Plus"), violet to make it pop.
  - **Cohort joined** — slate, neutral context.
  - **Interview date** — calendar pill colour-coded by proximity: rose (≤7d / today), amber (≤21d), emerald (>21d), slate (past). Includes both nice date ("27 May") and relative suffix ("in 14d"). Hidden when no interview date is set.
- **Backend:** `student_match._build_match` now also captures `interview_date` from the Monday Academy Members board (column `date_mkr7rdv7`). Cache invalidation logic treats matches missing the new `interview_date` key as stale so existing tickets pick it up on next open without waiting 24h.
- **One-shot backfill** run in this session: 14 already-matched tickets refreshed with `interview_date`; 34 of 59 previously-unmatched tickets newly linked via the name fallback. 47 stripes now render on Coralie's Kanban view at first paint.
- **Files:** `backend/student_match.py`, `frontend/src/pages/SupportTickets.jsx`.


### 2026-05-13 — Bugfix: Student lookup now works on Circle DM tickets (Coralie)
- **Bug:** Coralie reported "student lookup in the ticket isn't working." Repro'd: Circle DM tickets land with `student_name` only (no `student_email` or `phone`), so `student_match.match_student` had nothing to match on and returned `{matched: False}`. Result: the ticket detail panel showed no "Linked student record" card and no "Student Lookup" link — Coralie couldn't jump from a Circle DM ticket to the unified Student Lookup view.
- **Fix (backend):** `student_match.match_student` now takes an optional `name`. When email/phone fail, it resolves `name → email` via the cached Circle members list (`student_lookup.name_search`, only honours matches ≥ 80) then runs the existing Monday email search. Returned match carries `matched_via: "name"` for observability. `ensure_ticket_student_match` no longer honours the 24h cache for previously-unmatched tickets, so existing Circle DM tickets auto-rematch on next open.
- **Fix (frontend):** `SupportTickets.jsx` ticket detail now renders a fallback "open Student Lookup" link (using `?name=…`) whenever the ticket has a `student_name` but no matched email, so Coralie always has a path off the ticket. `StudentLookup.jsx` honours the new `?name=` query param by pre-filling the search input — the existing debounced name-search picks up suggestions instantly.
- **Verified:** Logged in as Coralie, called `POST /api/tickets/{id}/match-student` on an unmatched Circle DM ticket → now returns `matched: true` with email/tier/cohort + `matched_via: "name"`. Email-based matches unchanged. Frontend `/students?name=Nalaayeni%20Kanesan` pre-fills the box and surfaces the right candidate.
- **Files:** `backend/student_match.py`, `frontend/src/pages/SupportTickets.jsx`, `frontend/src/pages/StudentLookup.jsx`.


### 2026-05-13 — Bugfix: Circle ticket reply now posts as the right coach
- **Bug:** "Circle rejected the message — see backend logs" when Coralie tried to reply from the Tickets board to any Circle DM ticket that originated from Oksana/Becky/Coralie/Anoop (not Tessa). The endpoint hard-coded `admin_email = cfg.coach_emails[0]` (always Tessa). Circle's Headless API rejects POSTs when the posting admin isn't a participant in that 1:1 DM thread.
- **Fix:** Reply endpoint now looks up `circle_dm_threads.coach_admin_email` (or `ticket.circle_dm_meta.coach_admin_email` as fallback) to identify which coach owns the thread, and posts as that coach's token. Error message now also includes the email it tried to post as.
- **Polling bot** now writes `coach_admin_email` onto every ticket's `circle_dm_meta` (both escalation + AI-resolve paths), so the fallback works for future tickets even if the thread state doc is dropped.
- **Backfilled** existing Circle DM tickets with the correct `coach_admin_email` derived from their `thread_uuid` → state lookup (preview database only — production needs a redeploy + an admin to trigger a one-shot backfill, OR the bug is implicitly fixed as new tickets carry the field).
- **Files:** `backend/routes/circle.py` (lookup thread coach), `backend/circle_dm_poll.py` (set coach_admin_email on ticket meta in both paths).

### 2026-05-13 — Interview-eve: private-tier separation + averages
- **Backend `/api/interview-eve/summary` extended** to return three stat groups (overall, private tier, academy tier) each with: sent, replied, pending, low_score, avg_score. Also returns `private_tier_rows` — the last 50 scored private-tier check-ins for the widget's drill-down list.
- **Widget shows two stat blocks** (All students + Private tier) each with an "Avg N/10" pill in the top-right (colour-coded: red ≤5, amber 6-7, green 8-10). Private-tier scored students list shown below the stat blocks for quick scanning by Coralie / private-tier coach.
- **Files changed:** `backend/routes/interview_eve.py`, `frontend/src/components/InterviewEveWidget.jsx`.

### 2026-05-13 — Interview-Eve check-in DMs + UI surfacing
- **New scheduled job** at **19:00 UK Mon–Fri**: pulls all students whose interview is tomorrow (from the Monday Academy Members board via `upcoming_interviews.fetch_upcoming_interviews`), looks them up in the Circle members cache by email, ensures a 1:1 DM chat room exists between Coralie and the student, and sends the message:
  > *Hi {first}, this is an auto-response from Coralie's account. How supported do you feel heading into your interview tomorrow? Reply with a number from 1-10 and we'll be in touch if you need anything. Good luck — you've got this. 💪*
- **Score capture via existing polling bot**: when the student replies, `circle_dm_poll` calls `interview_eve_dm.maybe_record_score` which extracts a 1-10 number (lenient parser — single-digit numbers in short messages, or digits next to "/10", "rate", "score" in longer messages), saves it on `interview_eve_dms`, and sends an acknowledgement reply ("Thanks {first}, got it — recorded as N/10. Best of luck tomorrow!").
- **Low-score (≤5) Slack alert**: routed by tier — `SLACK_PRIVATE_TIER_WEBHOOK_URL` for private-tier students (Plus / VIP / 1:1 / Boost & Go), `SLACK_COACH_CHAT_WEBHOOK_URL` for Academy / Silver / Gold. Falls back to `SLACK_WEBHOOK_URL` if neither is set.
- **Idempotent**: re-running the job won't double-send (keyed on `interview_eve_dms.id = "eve:{date}:{email}"`).
- **UI surfacing (NEW today)**:
  - **Upcoming Interviews board** — each student row + private card now shows an `EveScoreChip` once a DM has been sent: grey "pending" if no reply yet, then red/amber/green pill with the score `N/10` once the student replies. Backend enriches each student in the interviews payload with `eve_score: {score, score_received_at, sent_at}`.
  - **Coach Activity board** — new `InterviewEveWidget` card with 4 headline counters (Sent, Replied, Pending, Low score ≤5) for the past 7 days, plus a focus list of today's & tomorrow's interview check-ins each with a score pill. Refresh button.
- **Routes:** `GET /api/interview-eve/preview` (dry-run — who would we DM?), `POST /api/interview-eve/run-now` (force a run), `GET /api/interview-eve/records` (all recent DMs + scores), `GET /api/interview-eve/summary` (counts + today/tomorrow focus for the widget — guarded by `require_board("coach_activity")` so coaches see it).
- **Files:** `backend/interview_eve_dm.py` (NEW), `backend/routes/interview_eve.py` (NEW), `backend/routes/interviews.py` (enrich each student with `eve_score`), `backend/circle_dm_poll.py` (calls `maybe_record_score` before AI triage), `backend/server.py` (new scheduler job + router include), `frontend/src/pages/UpcomingInterviews.jsx` (new `EveScoreChip` component, used in academy + private rows), `frontend/src/components/InterviewEveWidget.jsx` (NEW), `frontend/src/pages/CoachActivity.jsx` (mount the widget).
- **New collection:** `interview_eve_dms` `{id, student_email, student_name, interview_date, tier, is_private_tier, circle_member_id, thread_uuid, coach_admin_email, sent_at, sent_body, score, score_received_at, score_raw_text}`.
- **Status:** Wired end-to-end; preview endpoint shows 5 students queued for tomorrow's interview (2026-05-14). UI surfaces ready. Pending user-provided Slack webhook URLs for tier-routed low-score alerts (currently falls back to `SLACK_WEBHOOK_URL`).

### 2026-05-12 — Per-coach scoped tag exclusion + Coralie bot access
- **Tessa-only tag exclusion (default):** New config field `tag_exclusion_coach_emails` (defaults to `[tessa@medicalinterviewprep.com]`). The excluded_member_tags list only applies to coaches in this list — other coaches auto-reply to everyone regardless of tags. Editable via `PUT /api/circle/bot/config` + a new editor in Settings → Bot. Implemented by passing `excluded_tags_lower` set to `_poll_one_coach` only when the coach is in the scope list.
- **New `bot` board permission** added to `ALL_BOARDS`. All Circle bot endpoints (`/circle/bot/*`, `/circle/coach-playbook` GET/PUT, `/circle/dm-events`) switched from `require_admin` → `require_board("bot")`. Admins still pass (role-bypass in `user_has_board`).
- **Settings page** now accessible to users with `bot` OR `settings` board (was admin-only). Non-admins see only the Bot tab; admin sees all 9 tabs. Default tab = `bot` for non-admins. `BoardGuard` extended to accept a list of acceptable boards (any-match grants access). `userCanAccess` extended likewise.
- **Coralie** (`coralie@medicalinterviewprep.com`) granted the `bot` board so she can now see Settings → Bot, edit the Coach Playbook, view bot status, handle playbook suggestions, and toggle the bot — without admin access to other settings.
- **Files:** `backend/deps.py` (+`bot` board), `backend/routes/circle.py` (auth guards), `backend/circle_dm_poll.py` (`tag_exclusion_coach_emails` config field + scoped exclusion), `frontend/src/App.js` (`BoardGuard` array support), `frontend/src/components/AppShell.jsx` (`userCanAccess` array support, `/settings` accessible via `bot`), `frontend/src/pages/Settings.jsx` (tab visibility + new editor), `frontend/src/pages/Settings.jsx` (CoachPlaybookSection `tag_exclusion_coach_emails` editor).

### 2026-05-12 — 5-coach rollout: Tessa + Coralie + Oksana + Becky + Anoop
- **Bot now watches 5 admin inboxes:** `tessa@medicalinterviewprep.com`, `coralie.fairon@yahoo.co.uk`, `oksana.demchenko.2000@ukr.net`, `becky.platt2@nhs.net`, `anoop.chidam@gmail.com`. Each got an authorised Headless API token via the existing `CIRCLE_HEADLESS_TOKEN` exchange. All 5 token caches succeeded; 0 errors on first poll.
- **Initial seed:** ~1,341 DM threads recorded across the 5 coaches (state=active, last_seen=latest_message_id) so the bot doesn't auto-reply to historical backlog. Future polls only act on truly-new student messages.
- **Performance fixes for multi-coach:**
  - Parallelised coach loop with `asyncio.gather` — 5 coaches now run concurrently. Wall time dropped from >60s (sequential) to ~17s.
  - Capped chat-rooms pagination at 2 pages × 100 records per coach (= top 200 recently-active chat rooms). Stale rooms beyond that rarely get new student messages.
- **Webhook deprecated:** The Circle workflow "Coralie DM AI reply (Support desk)" webhook should now be **disabled** in Circle. Polling does the same job and doesn't have the one-shot-per-member limitation.

### 2026-05-12 — Tag-based exclusion (mirrors Circle workflow audience filter)
- **New behaviour:** When a Circle DM arrives from a member who has any tag in the configured `excluded_member_tags` list, the bot stays completely silent — no reply, no ticket, no Slack. Thread state recorded as `tag_excluded`. Mirrors the user's existing Circle workflow audience filter (which excludes audiences tagged "Circle Member", "Autoreply hold", "Interview week", "AYGI 25/26").
- **Member tag lookup**: extended `circle_api.fetch_member` to also return `tags` (from `member_tags[].name`). Added `fetch_member_cached(db, member_id)` with a 6-hour `circle_members_cache` cache so we don't slam the Admin API every poll cycle.
- **Bot config**: new field `excluded_member_tags` (defaults to the 4 tags from the user's Circle workflow screenshot). Editable via `PUT /api/circle/bot/config` and surfaced in Settings → Bot with chip display + comma-separated editor. Case-insensitive matching.
- **UI**: New "Excluded member tags" section below the polling status, with chips for each excluded tag and Edit/Save inline. Watched-threads list now shows `tag_excluded` pink pill state + matched tags. New `tag_excluded` counter in the last-poll summary grid. Tag-excluded threads can be re-armed (drop the state doc) just like escalated/human_takeover.

### 2026-05-12 — Circle DM Bot: playbook suggestions, coach config UI, starter playbook
- **Self-improving playbook (`/bot/playbook-suggestions`)**: Whenever the bot escalates a Circle DM with reason=`playbook_miss`, the student's question surfaces in **Settings → Bot → Playbook suggestions** with their name, timestamp, and a textarea to write the answer. Clicking "Add to playbook" appends `- **{question}** {answer}` to the coach playbook and marks the ticket `suggestion_status: added`. Clicking "Dismiss" stores `suggestion_status: dismissed`. Two endpoints: `GET /api/circle/bot/playbook-suggestions`, `POST /api/circle/bot/playbook-suggestions/{ticket_id}/handle`.
- **Per-coach config UI**: New "Edit coaches" button in **Settings → Bot → Polling status** lets the admin update `coach_emails` (comma-separated). Backed by existing `PUT /api/circle/bot/config`. Lays groundwork for extending the bot to Coralie + other coaches.
- **`original_message` added to `circle_dm_meta`**: tickets created by the bot now store the raw student question, which the suggestion view uses verbatim (so we don't have to parse subjects).
- **Starter playbook draft**: `/app/memory/draft_coach_playbook.md` — generated by clustering 40+ existing tickets into the top recurring FAQ themes (live recordings, video uploads, VIP access, cohort timing, mock matching, refunds=escalate, tech issues). 30+ entries with `[PLACEHOLDER: ...]` answers for the AYCI team to fill in and paste into Settings → Bot.
- **Files:** `backend/routes/circle.py` (+2 endpoints), `backend/circle_dm_bot.py` (saves `original_message`), `frontend/src/pages/Settings.jsx` (new Playbook Suggestions section + Edit coaches editor).

### 2026-05-12 — Circle DM Bot v2 (polling-based) + Coach reply path
- **What changed:** Replaced Circle Workflow webhook approach with continuous polling. Circle workflows only fire once per member, which made testing impossible and meant the bot could never respond to follow-ups from the same student. Polling solves both. Also wired up a coach-reply path so Coralie/team can respond to Circle DM tickets from the dashboard and have those replies post back into Circle as Tessa.
- **Loop:** every 1 minute, for each enabled coach admin (currently just Tessa), fetch all chat rooms via `GET /api/headless/v1/messages` (NOT `/chat_threads` — that one silently omits fresh DMs), filter to `chat_room_kind=direct`, then per-thread fast-path skip when `last_message.id <= last_seen_message_id`. Otherwise: detect human takeover, escalation phrase, sensitive keyword, AI-resolve via playbook, or escalate.
- **Reply post format:** Circle's chat API rejects plain-text body with `Missing parameter: rich_text_body`. We now build a minimal tiptap doc shape (`{type: "doc", content: [{type: "paragraph", content: [{type: "text", text: ...}]}]}`) and include it as `rich_text_body`. Also accepts HTTP 202 (queued for async dispatch) as success — Circle's chat POST returns 202, not 200/201.
- **Bot dedupes its own replies via `sent_bodies`:** Circle's 202 response doesn't include a message id, so we can't add it to `sent_message_ids`. Instead the bot remembers the last ~20 reply bodies it has posted and treats any admin-authored message with a matching body as its own (not a human takeover).
- **Coach reply path (new):** `POST /api/circle/tickets/{ticket_id}/reply` — for tickets with `source=circle_dm`, fetches the ticket's `circle_dm_meta.thread_uuid`, posts the coach's reply into the Circle DM thread (as the configured coach admin), records it on the ticket's notes timeline as `_circle_dm_outbound`, and marks the thread `human_takeover` so the bot backs off. New `CircleReplyPanel` component in `SupportTickets.jsx` renders only for `source=circle_dm` tickets.
- **Reply format:** Always prefixed with `"Hi {first}, this is an auto-response from {coach}'s account."` per user request.
- **Hard cap:** 8 AI replies per thread per day to prevent runaway loops.
- **Settings UI (Settings → Bot):** live polling status, watched-threads table with state pills (active/escalated/human_takeover), per-thread Re-arm button, pause/resume toggle, manual "Poll now" button, diagnostic endpoint for verifying Tessa's DM inbox view. Coach playbook editor moved into same tab.
- **Files:** `backend/circle_dm_poll.py` (NEW), `backend/circle_api.py` (added `list_dm_threads` using `/messages` endpoint, `list_thread_messages_for_admin`, `post_dm_message` with tiptap rich_text_body, `get_cached_admin_member_id`), `backend/routes/circle.py` (added `/bot/status`, `/bot/config`, `/bot/poll-now`, `/bot/reset-thread/{uuid}`, `/bot/diagnose`, `/tickets/{ticket_id}/reply`), `backend/server.py` (added `_circle_dm_poll` scheduler job, every 1 min), `frontend/src/pages/Settings.jsx` (dynamic bot dashboard), `frontend/src/pages/SupportTickets.jsx` (new `CircleReplyPanel`).
- **New collection:** `circle_dm_threads` `{id, thread_uuid, coach_admin_email, student_member_id, student_name, state, last_seen_message_id, sent_message_ids, sent_bodies, ai_reply_count_today, ai_reply_count_date, escalated_ticket_id, escalation_reason, last_reply_text, last_reply_at, first_seen_at, last_activity_at, human_takeover_at, human_takeover_by}`
- **New config doc:** `app_settings { id:"circle_dm_bot_config", enabled, coach_emails, last_poll_at, last_poll_summary }`
- **Status:** End-to-end verified — bot polls, posts replies in correct rich_text_body format, escalates correctly when playbook misses, coach reply path posts to Circle as Tessa and disables the bot on that thread. Default playbook is intentionally short — user is expected to extend it with their actual FAQs (or leave them to escalate).

### Earlier in this fork
- Timeline Tooltip for Past Coaches UI (`pages/UpcomingInterviews.jsx`)
- Scorecard waitlist fixes (ConvertKit burst-filtering + dynamic tag resolution)
- Wati 24h window expiration bug fix
- Over-allowance Calendly booking alerts + Acknowledge feature
- Private Video Submissions data-source transparency (Tally vs Monday)
- Circle DM Bot v1 foundation (Headless API token exchange, webhook endpoint, Settings Bot tab)

## Pending Tasks

### P1 — Upcoming
(none currently — Slack digests removed at user's request 2026-05-14)

### P2 — Future
- Enriched Linked Student card in ticket UI (interview date, at-risk, Pulse signal)
- Pulse Score history + per-pillar drill-through
- Settings UI for TEAM_ACCOUNT_EMAILS / Spotlight cutoff / routing rules
- WhatsApp template-message starter kit
- Refactor `SupportTickets.jsx` (>2000 lines) and `PrivateVideos.jsx` (>800 lines)
- Multi-coach expansion of Circle DM Bot (Coralie + others) — config UI already supports this

## Key Endpoints
- `GET /api/circle/bot/status` — polling state + watched threads
- `PUT /api/circle/bot/config` — toggle enabled / update coach_emails
- `POST /api/circle/bot/poll-now` — force single poll cycle
- `POST /api/circle/bot/reset-thread/{uuid}` — re-arm an escalated/human_takeover thread
- `POST /api/circle/dm-webhook` — kept as legacy webhook receiver
- `GET/PUT /api/circle/coach-playbook` — bot's knowledge base

## Credentials (test)
- `admin@ayci.com` / `Admin@2026`
