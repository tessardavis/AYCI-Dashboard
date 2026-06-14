# Dashboard — migration status & to-dos

_Portable companion to `ZAPIER_AUDIT.md` (which has the per-zap detail). Last updated 2026-06-14._

## Recent changes — 2026-06-14 session

All committed + pushed to `main` (Render/Vercel auto-deploy). Two workstreams:

**Private-chat migration (Route 2) — Phase 0 shipped.** See `PRIVATE_CHAT_MIGRATION.md`.
- Settings → Integrations **"Private chat setup"** card: editable coach config
  (Tessa/Arub/Coralie/Becky — all 4 Circle emails verified; **Coralie = sender**,
  she's a Circle admin so her session mints), **per-tier welcome templates**
  (PP ✅ · VIP ✅ · B&G Plus ✅ · **plain B&G ⏳ still to paste**), dry-run preview,
  per-student **Create chat**, and a **"no group chat" backlog audit** (unions all
  coaches' chats so historical Oksana-created chats are detected → never duplicates).
- **"Awaiting DMs" status** (`private_chat_status`): the private-chat zap's DMs-off
  branch POSTs it via `update-by-email`; surfaces the student in Needs setup with an
  orange badge. Circle exposes no DM-off flag, so this push-from-zap is how we catch it.
- **Reply routing is safe across the Oksana→Coralie sender switch:** existing chats
  are never recreated (dedup guard checks ALL coaches), and video replies route to the
  student's stored `private_chat_url` (the original Oksana chat) — no new threads.
- **Open:** paste the plain **Boost & Go** template; **test the "Awaiting DMs" zap step**
  (POST `update-by-email`, expect 200 `"updated"`); Coralie connect Circle in **Zapier**
  (separate from the dashboard, which already works via the parent token).

**SLA digest** now fires only inside the cohort `[start, end]` window (was ignoring the
start date). June '26 dates set (22 Jun–26 Jul) → quiet until 22 Jun. ✅

**Boost & Go reconciliation (NEW).** `boost_and_go` is only a mirror of Monday's
"Boost + Go" column, so B&G buyers whose Monday column never flipped off "Offer Due/Made"
were invisible as B&G. `bg_audit.py` cross-references **Stripe** purchases against the flag:
`GET /api/admin/boost-and-go/audit` (background-cached; matches charges via regex
`boost & go`, excludes Turbo/Prep "Booster" false-positives; echoes matched descriptions +
products for confidence) and `GET /api/admin/boost-and-go/backfill[?apply=true]` (dry-run by
default; sets B&G / B&G Plus from what they bought, pinned). **2026-06-14: 85 B&G buyers
found, 60 already flagged, 21 unflagged → backfilled; 4 buyers have no dashboard row
(dual-email / never synced — TODO chase).** Upstream gap remains: the **Kajabi→Monday
purchase zap doesn't flip the column on purchase** — fix that so new buyers don't get stuck
(re-run the audit anytime to catch stragglers).

**Interview-date reschedules → dashboard (Tally-authoritative) — Part 1 shipped & verified.**
See `~/.claude/plans/fluffy-discovering-cake.md`.
- `interview_date_reconcile.py`: adopts each student's **most-recently-submitted** Tally
  date into the mirror's `interview_date` (pinned in `dashboard_edited_fields`). Scheduled
  05:30 + 18:45 weekdays; admin **"Reconcile dates from Tally"** button on Upcoming
  Interviews + `POST /api/admin/interview-date/reconcile`. Single `bulk_write` (avoids the
  Vercel proxy timeout). **Verified 2026-06-14: 31 changed on first run, 0 on re-run.**
- Student Lookup now prefers the latest Tally date over the stale Monday column.
- **Calendar auto-heal (Part 2/3) — DONE & verified 2026-06-14.** `google_calendar.py`
  keeps one event per student at the authoritative date, matched by event
  `location == "ID: <monday_id>"`. AYCI Interviews
  (`30f44afccaaec2ee9395b97820982164b701a5ff5a508c2ab808090c2873f609@group.calendar.google.com`)
  is shared with the service account `ayci-drive-reader@ayci-dashboard.iam.gserviceaccount.com`
  ("Make changes to events"); `GOOGLE_INTERVIEWS_CALENDAR_ID` set on Render. **Gotcha that
  blocked it:** the **Calendar API had to be enabled** in the `ayci-dashboard` GCP project
  (#346018364416) — Drive was on, Calendar wasn't. Self-test (create+delete) passes;
  Nalaayeni's stale `2026-06-11` event deleted, only `2026-07-09` remains. Admin helpers:
  `GET /admin/google-calendar/config` (service-account email + status) and `/selftest`.

## Recent changes — 2026-06-10 session

Work done this session (all committed + pushed to `main`; Render/Vercel auto-deploy):

- **Zapier error triage (all 3 cleared):** WATI webinar 400 → the phone formatter was outputting a leading `+`; added a Formatter Replace so WATI gets `447…` (no `+`). 1:1-reminders "Not authenticated" → the Monday API token in the Webhooks step was dead (Oksana's); swapped for a stable token. 7b Speciality filter → Tessa published.
- **Circle DM bot — Ben's double-message fixed:** interview-eve threads are now **score-capture only** (`circle_dm_poll.py`) — they never fall through to the generic auto-responder, so no second DM after the support-score prompt. Eve link retires once the interview day passes.
- **Interview-eve DM — Kathryn Wilson excluded** (`interview_eve_dm.py`): `EVE_DM_EXCLUDE_NAMES`/`EVE_DM_EXCLUDE_EMAILS` (+ `INTERVIEW_EVE_EXCLUDE_EMAILS` env), seeded with `kath_wilson@icloud.com`.
- **Refunds board (NEW, Monday never did this):** `backend/routes/refunds.py`, board permission `refunds`, page `/refunds`. Stripe-sourced via `POST /api/refunds/ingest` (Zapier "New Refund" → secret `ZAPIER_WEBHOOK_SECRET`), matched to a student by email (tier/cohort snapshot). Editable reason category / notes / status; admins + any refunds-board user (incl. Coralie) can delete. **One-click `POST /api/refunds/backfill-from-stripe`** (admin) already pulled **111 historical refunds (£30,658.52)** using the restricted `STRIPE_API_KEY`. Students(DB) rows show a **Refunded badge + filter**.
  - **Open:** publish the "Refund tracking from Stripe" zap (go-forward); give Coralie the `refunds` board (Settings → Users); delete the £0.01 test row.
- **Circle DM auto-responder HARD-DISABLED** (`server.py`): per Tessa it must not send AI replies from her inbox **or any coach's**. Polling job is forced off regardless of the DB toggle; re-enable only by setting `CIRCLE_BOT_ENABLED=true` on Render. **Team roles clarified:** coaches = Anoop/Becky/Kat/Zinnirah/Anne/Charlotte; **Coralie = customer support, NOT a coach**. Undecided: whether to keep silent triage (DMs → Coralie tickets, no replies sent) or kill it entirely; and whether the night-before score DM should still send as Coralie.

> ⚠️ The per-machine **Claude memory** (`~/.claude/projects/.../memory/`) does **not** travel with the repo. This doc is the portable record — read it first on a new device. `git pull` brings all code + this file.

## Where we are

The dashboard is a **mirror of the Monday "Academy Members" board** (15-min sync). Retiring Monday means removing every dependency — zaps that **write** to Monday, and the **new-signup path** that creates rows there — then turning the mirror off.

**Every migration pattern is now built & proven in production:**
- `POST /api/students-db/update-by-email` — replaces Monday `Get Items + Update Item`. Returns `previous_values` for read-modify-write zaps.
- `POST /api/students-db/lookup-by-email` — read a student (scalar fields + named Monday columns).
- `POST /api/students-db/book-call` — `{email, coach}` → fills the next 1:1 Call slot (`Booked - <Coach>`); replaced the AI-by-Zapier slot picker.
- `POST /api/students-db/intake` — upsert a student by email; **mirror reconciliation** merges the `auto:` row when the Monday row syncs (no duplicates, no delay).
- **Outbound dispatcher** — fires `column_changed` to subscribers when a dashboard-owned field changes. Admin UI at `/webhooks` (admin-only). Only fires on **dashboard-originated** changes.
- `POST /api/toolkit/access` — `{email}` → which Kajabi add-ons they bought (gates tools.medicalinterviewprep.com).

**Migrated so far (write-side → dashboard):** Milestones 1–5, Mock Interview ×3, 15-min call ×3 ✅ · 8c Boss-badge (Path A) & 1:1 Round Robin ×3 🟦 Phase-1 (Monday safety-net steps still in place) · **AYCI signup create paths → `intake` ✅ (the P0 — new students now land in the dashboard directly).**

## To-dos

### Immediate (this week)
- [ ] **Verify new signups** land in Students (DB), then **remove the 3 Monday `Create Item` steps** from "[AYCI JUNE-26] Signups to Monday Board (OD)" (first real "Monday does less" step).
- [ ] After ~1wk verify: **remove the Monday safety-net steps** from the 15-min-call zaps; do **Round Robin Phase 2** (delete Monday/AI/Paths machinery → single Filter → Fallback). **Step-by-step teardown below.**

### Coralie batch (when she's back — week of 2026-06-08)
- [ ] **Circle:** Coralie connects her Circle account in Zapier (admin/mod rights needed) → **publish 8b** (first dispatcher consumer, catches `boss_badge`) → switch the other `(Oksana)` zaps' connections to Coralie **before Oksana's accounts are deactivated**.
- [ ] **Gmail:** Coralie re-connects her inbox via **My profile → Connect Gmail** (her token is expired → the lone `errors: 1` on gmail sync). Re-connect refreshes it + assigns ownership to her.

### Per-launch (recurring) ⚠️
- [ ] **Each new cohort:** update the hardcoded **`cohort_joined: "June 26"`** literal in the 3 signup `intake` POSTs (Academy/PP/VIP create paths). Cohort dates follow from the step 4/5 formatters automatically; only `cohort_joined` + `tier` are hardcoded.

### Later (the rest of retiring Monday)
- [ ] **Remaining write-side zaps → `update-by-email`** — cohort-lifecycle / Kit- / Circle-triggered ones, **plus the 2 legacy-upgrade signup paths** (need Tier End Date / In Active Cohort / Legacy added to the dashboard first; mirror covers them meanwhile).
- [ ] **Private-chat creation → dashboard-native (Route 2)** — zaps 46/47/53/54 create coach group chats when a student joins Circle; today they silently drop anyone who joined Circle under a different email than they signed up with. Plan to have the dashboard detect + match (on either email, fixing the dual-email gap) + create the chat itself. **Full plan in `PRIVATE_CHAT_MIGRATION.md`.** Coach assignment resolved (same shared coach[s], port the Zapier table to a dashboard config). Manual stopgap shipped: the `circle-email-gaps` Link panel in Settings → Integrations.
- [ ] **Outbound dispatcher rollout** to the remaining Monday-*triggered* zaps (after 8b proves it). Caveat: only fires on dashboard-originated changes — needs the triggering edits to happen in the dashboard (or a mirror-emit bridge).
- [ ] **AYGI / waitlist signups → `intake`** (AYGI deferred to the 2027 cohort).
- [ ] **Final cutover:** turn off the Monday→Mongo mirror → archive the board.

## Round Robin Phase 2 — teardown checklist (Zapier UI)

**Scope:** the 3 live siblings only — **18 Anoop · 18b Charlotte · 18c Becky**
(`[AYCI JUNE-26] 1:1 Calls - Round Robin`). Each already has the Phase-1
Webhooks POST → `/api/students-db/book-call` `{email, coach:"<Name>"}` right
after the Calendly trigger; that POST is now the source of truth (fills the
lowest un-booked Call slot server-side, writes `call_N = "Booked - <Coach>"`,
pins it dashboard-owned). **Out of scope:** 19 `[TVA Test] … Tessa` (draft) and
19c `… Becky (Oksana)` (has an extra VIP/PP filter; parked on the Coralie/Oksana
connection swap) — migrate those separately once 18/18b/18c are proven.

**End-state flow (per zap):**
1. Trigger — Calendly: Invitee Created _(unchanged)_
2. Webhooks: POST → `book-call` `{email, coach}` _(unchanged — keep exactly as is)_
3. **Filter** — _only continue if_ `reason` (from step 2) **exactly matches** `all_slots_booked`
4. Formatter: Date/Time → Circle: Find Member → Slack alert _(the existing Fallback, unchanged)_

That's it. On a normal booking `book-call` returns a `slot` number and the
Filter stops the zap (booking already written). Only the all-4-booked case
(`reason: all_slots_booked`) flows through to the Slack "call limit reached"
alert.

**Delete (per zap), in order:**
- [ ] monday: **Get Items by Column Value** (student lookup)
- [ ] monday: **Get Column Values** (reads current Call 1–4 state)
- [ ] **AI by Zapier ×2** (picked which slot — now done in `book-call`)
- [ ] **Paths** block: Call 1 / Call 2 / Call 3 / Call 4 (each ending in monday **Update Item**) — delete all 4 call paths
- [ ] Reconnect the surviving **Fallback** steps (Formatter → Circle → Slack) under the new step-3 Filter instead of the old Paths "Fallback" branch

**Notes / gotchas:**
- Filter on **`reason` = `all_slots_booked`**, not on "`slot` is empty" — `reason`
  is present only in the all-booked branch, so it's the unambiguous signal (a
  null `slot` can render inconsistently in Zapier).
- **404 edge:** if no student matches the email, the `book-call` step errors and
  the zap halts (rare — means they aren't in the system yet). Acceptable for now;
  if it bites, add an error-path Slack ping. The old Monday "Get Items" branch
  silently found nothing here, so this is stricter, not worse.
- Do **18/18b/18c together** — identical except the `coach` literal already set in step 2.
- After teardown, the dashboard owns `call_1..call_4`; the mirror leaves them
  alone (pinned in `dashboard_edited_fields`), so Monday no longer needs the writes.

## Key reference

- **Frontend:** https://ayci-dashboard-nfiw.vercel.app (Vercel) · **Backend:** https://ayci-dashboard.onrender.com (Render; env vars in Render UI — `backend/.env` is gitignored). Hosting + LLM are off Emergent.
- **Secrets:** `ZAPIER_WEBHOOK_SECRET` (in every migrated zap's `X-Webhook-Secret`) · `TOOLKIT_ACCESS_SECRET` (toolkit site's server-side call).
- **"Needs setup" flag** = current private tier (Private Plus / VIP / Boost & Go, incl. "Upgraded" B&G) **and not a Boss** **and not** marked "not needed" **and** missing a private chat link OR video allowance. Deprecated tiers (Platinum/1:1/legacy) excluded.
- **Video allowance map:** Private Plus 15 · VIP 30 · Boost & Go 5 · Boost & Go Plus 10. ("Used" column counts actual private-video submissions.)
- **Webhook Subscriptions** = admin-only. **Students (DB) / Student Lookup** = `students` board permission (manage in Settings → Users). The personal **Connect Gmail** is on every user's **My profile**.
