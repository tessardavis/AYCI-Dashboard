# AYCI Team Dashboard — PRD

## Original problem statement
Build a clean, modern team performance dashboard for AYCI Academy (a company helping doctors prepare for consultant interviews, ~10-person team, runs on EOS). Three views: Weekly Scorecard, Quarterly Rocks, Launch Dashboard. Plus Settings/Admin. JWT auth, admin + user roles. Notion-meets-financial-dashboard vibe, dark navy sidebar (#1A1F36) + teal (#0EA5E9).

### Add-on (April 2026): Unified Student Lookup Dashboard
A single-page view where the team searches a student by email and sees a unified profile pulled live, in parallel, from Monday.com (Academy Members board 1956295952), Circle, Stripe, ConvertKit, and Calendly. Fields: name, email, tier, cohorts, private chat link, interview history, past calls, activity, last-seen on Circle, (future) private Google Doc summary.

## Architecture
- **Backend**: FastAPI + MongoDB (motor), JWT (PyJWT) auth via httpOnly cookies, bcrypt password hashing, all routes prefixed `/api`. APScheduler weekly cron (Monday 06:00 Europe/London).
- **Frontend**: React 19 + React Router 7 + shadcn/ui + Tailwind + Recharts + Sonner. Manrope (display) + Inter (body) fonts. AuthContext with `withCredentials: true`.
- **Data model (MongoDB)**: `users`, `team_members`, `metrics`, `weekly_values`, `rocks`, `launches`, `launch_data`, `daily_registrations`, `circle_members_cache` (slim Circle member list, 24 h TTL).

## User personas
- **Admin (Tessa / Arub)** — full CRUD on team, metrics, rocks, launches, users.
- **Team member (user)** — view everything, update scorecard weekly values, update own rock status/notes, edit launch KPIs, search students.

## Core requirements
1. Weekly Scorecard: 13-week grid of **completed** weeks (current in-progress Monday excluded), 5 categories, owner avatars, editable cells, green/red goal highlighting, sparklines, summary ring with "X of Y on track".
2. Quarterly Rocks: grouped by owner, status pills (On Track/Off Track/Done) click-to-cycle, expandable notes, quarter selector, donut summary.
3. Launch Dashboard: per-launch KPI cards, stepped Good/Better/Best target bar, daily registrations line chart with previous launch overlay + cumulative, editable sales breakdown, launch-over-launch bar chart.
4. Student Lookup: single search → 5 platform cards (Monday, Stripe, ConvertKit, Circle, Calendly) fan out in parallel; partial failures don't block the view.
5. Settings: tabs for Team, Users, Metrics, Rocks, Launches (admin-only CRUD).
6. Auth: JWT cookie login, admin-only register endpoint, logout.

## Implemented
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

## External integrations in use
| Platform   | Env var              | Purpose                                                 |
|------------|----------------------|---------------------------------------------------------|
| Transistor | TRANSISTOR_API_KEY   | Weekly podcast downloads                                |
| ConvertKit | CONVERTKIT_API_SECRET| Subscribers, tags, CTR, student lookup                  |
| Stripe     | STRIPE_API_KEY       | Revenue metrics, student payment history                |
| Circle     | CIRCLE_API_TOKEN     | Community members, activity, student profile           |
| Monday.com | MONDAY_API_TOKEN     | Academy Members board, student columns                 |
| Tally      | TALLY_API_KEY        | Form submissions (interviews, results)                 |
| Calendly   | CALENDLY_TOKEN       | Scheduled events, past calls per invitee               |
| YouTube    | YOUTUBE_API_KEY      | Podcast playlist views                                  |

## Prioritised backlog
**P1**
- Interview-date accuracy: decide whether "Interviews This Week" should track by Tally form Q8 (actual interview date) instead of submission date.
- Google Drive integration: Private-tier doc summary on Student Lookup card (requires Google OAuth setup).
- Drag-and-drop re-ordering of metrics within a category.
- Quarter archiving (make old quarters read-only once new one is active).
- `/api/auth/refresh` endpoint implementation.

**P2**
- "Sync preview" — show what would be pulled without writing.
- Per-user rock-edit restriction (currently any authenticated user can update any rock).
- CSV export of scorecard.
- Real-time updates via WebSocket for Monday live meetings.
- Email/Slack digest reminder before Monday meeting.
- Recharts Sparkline negative-width console warning cleanup (cosmetic).
- Tighten CORS_ORIGINS (currently `*` with credentials).

## Next tasks
- Confirm with user: switch "Interviews This Week" to Q8-based tracking? (asked, pending)
- Circle member auto-refresh: add a second APScheduler job for daily cache refresh (currently only startup + manual).
- Google Drive integration for private-tier docs (Student Lookup enhancement).
