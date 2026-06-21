# HANDOFF — session 21 Jun 2026

Pick-up notes. Everything below is **committed + pushed** to `main`; Render
auto-deploys the backend and Vercel auto-deploys the frontend, so the live app
already reflects it. Working tree is clean.

## Use this on another computer

**Just to USE the dashboard (no setup):** open the live app in any browser and
log in — nothing to install.
- Frontend: **https://ayci-dashboard-nfiw.vercel.app**
- Backend API: https://ayci-dashboard.onrender.com (`/docs` for the API)
- Login: your admin email + the production password.

**To continue DEVELOPING on another computer:**
1. `git clone git@github.com:tessardavis/AYCI-Dashboard.git && cd AYCI-Dashboard`
2. **Carry over the 3 secret files** — they're gitignored (real secrets) so
   `git clone` will NOT bring them. Copy them from this machine to the same
   paths on the new one:
   - `backend/.env`
   - `frontend/.env`  (just `REACT_APP_BACKEND_URL`)
   - `backend/google_service_account.json`
   (Alternatively, all backend secret *values* also live in the Render
   dashboard → service → Environment.)
3. Backend: `cd backend && pip install -r requirements.txt && uvicorn server:app --reload`
   (Python 3.12; entrypoint is `server:app`.)
4. Frontend: `cd frontend && npm install && npm start` (craco; `npm run build` to verify a prod build).
5. You don't need to run anything locally to ship — pushing to `main`
   auto-deploys both halves. A brief 502 during the Render bounce is normal.

## Shipped this session (code, live)
Performance + one feature, all committed/pushed (`985e59e`, `83efa88`,
`5e16013`, `5865e67`):
- **Circle cache kept permanently warm** — the 1.7MB members doc is cached
  in-process for 30 min; after idle the next person paid a ~5-10s cold Atlas
  read on Students DB / Lookup / name-search. Added a 20-min keep-warm
  scheduler job (`server.py`) so the window never lapses (only a fresh
  deploy/restart is cold, and startup warm covers that).
- **Students DB** — the two per-load aggregations (videos-used,
  refunds-by-email) are cached in-process ~60s.
- **Indexes added** (`server.py` startup) — `refunds(student_email/status/
  refunded_at)`, `private_video_submissions(email)`.
- **Lookup** — alternate-email retries (calendly/stripe/circle/tally) now run
  concurrently instead of serially.
- **Frontend stale-while-revalidate** — new `frontend/src/lib/swrCache.js`;
  Students DB, Refunds, and Private Videos paint last-loaded rows instantly
  from localStorage, then refresh in the background. Reusable for any board.
- **Private Videos board** — list query now projects the heavy embedded
  transcript text OUT (computes `has_transcript` server-side; full text is
  fetched on demand) and **excludes Done rows by default** (only fetched when
  the "show Done" toggle is on or a Done status filter is set). Team-member
  lookup cached ~60s.
- **Editable "videos used"** (the request) — new field in the Students DB Edit
  modal. Stored as an *adjustment* (delta over the live submission count), so a
  manually-set figure **keeps incrementing** as new private-video feedback
  arrives. Set 5 today → a new submission tomorrow shows 6. The cell shows a ✎
  marker; clear the field to revert to pure auto-counting. Backend:
  `videos_used_set` (input) → `videos_used_adjustment` (stored) in
  `routes/students_db.py`.

## Open to-dos (all external — do from any machine)
*(carried over from 19 Jun — still valid)*
1. **Oksana → Coralie zap handover** — see `ZAPIER_OKSANA_HANDOVER.md`. Done: 72, 46, 47, 53, 17,
   8b, full Student-Wins family (First + FU1/2/3). **Left: 47b (if active), 54 (Grid, low priority),
   and a final Circle-app filter sweep.** Deadline = before Oksana's Circle account is deactivated.
2. **Coralie's Gmail reconnect** — "Connect Gmail" was spinning; almost certainly a blocked popup.
   Reload → allow popups → Connect once → sign in as `coralie@medicalinterviewprep.com`.
3. **Narges** — fresh private chat (manual): Coralie starts a Circle group chat (Coralie + Becky +
   Narges), then set her Private chat URL on the dashboard. (Old Oksana chat left to go quiet.)
4. **Miriam Saey Al-Rifai** — her NHS email is now on her record; re-run upgrade-bonus
   `audit?refresh=true` then `apply?apply=true` (should take applied 7 → 8).
5. **Anoop's Round Robin trigger** — confirm step-1 Event Type = `AYCI 1:1 (30 min)` (Becky + Charlotte done).
6. **60-min 1:1 round-robin** (`AYCI 1:1 (60 min)`) — has real bookings but **no book-call zap**, so those
   calls don't write a slot. Decide whether 60-min 1:1s count toward allowance; build a zap if so.

## Key facts / gotchas (so they're not re-derived)
- **Circle token types** (Circle → Settings → Developers): **Admin v2** = `CIRCLE_API_TOKEN` (member
  cache, chat, space-*group* adds); **Headless Auth** = `CIRCLE_HEADLESS_TOKEN` (per-member session by
  email via one parent token); **Admin v1** = `CIRCLE_ADMIN_V1_TOKEN` (the one that does **single-space**
  adds). All on Render, not in the repo.
- **Coralie's Circle login = `coralie.fairon@yahoo.co.uk`** (NOT her `@medicalinterviewprep.com` work
  email, which is *not* a Circle member). Same split-identity trap bites buyers (Miriam = NHS email).
- **Early-access via Monday** (fallback if the dashboard button ever fails): set the
  **"Trigger - Previous cohort access"** status column (`color_mksa60n6`) to **"Previous cohort access
  + Bonus Calls"** → fires zap #43 (adds to space + DM).
- **Spaces:** previous-cohort curriculum = `2529501` (AYCI Curriculum - April 26); bonus =
  `1944718` (Bonus Live Sessions).
- **Private chat config** (Settings → Private chat config): sender = Coralie; all 4 coaches verified on
  valid Circle emails (Coralie/Becky `becky.platt2@nhs.net`/Arub `arubyousuf89@gmail.com`/Tessa).
- **The 1.7MB Circle members doc** drives many endpoints; never `find_one({"_id":"all"})` per request —
  use `student_lookup._get_name_index(db)` (now kept warm by the 20-min keep-warm job).
- **Auto-commit + push** convention; Render redeploys on push (brief 502 during the bounce is normal).

## Where the detail lives
`ZAPIER_AUDIT.md` (master Monday-retirement plan) · `ZAPIER_NEXT_BATCH.md` (Calendly batches) ·
`ZAPIER_OKSANA_HANDOVER.md` (Oksana zaps) · `CALENDLY_FLOW.md` (Calendly→dashboard map) ·
`MONDAY_REPLACEMENT_SPEC.md` · `SUPPORT_TEAM_SOP.md` / `TEAM_SOP.md`.
