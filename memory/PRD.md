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

### 2026-04 — Brand alignment (Apr 26)
- Applied AYCI brand guidelines across the entire app:
  - **Colors**: sidebar/dark backgrounds → `#182E87` (brand primary navy), accents/CTAs → `#4457B6` (brand indigo, matches the icon), warm spotlight → `#FEB870`, magenta/cyan available as `--ayci-brand-magenta` / `--ayci-brand-cyan`. All references to the legacy teal `#0EA5E9` swept through `LaunchDashboard`, `CohortDashboard`, `Sparkline`, `PaceTracker`, `YearOverview`, AppShell, and shadcn HSL primary/ring variables.
  - **Typography**: switched from Manrope/Inter to **TASA Orbiter** (Fontshare) for headlines + body and **Syne** (Google Fonts) for buttons/display, matching the brand style guide. Added utility classes `.font-display`, `.font-subhead`, `.font-button`.
  - **Logo**: AYCI icon (cross/diamond pattern from the brand kit) now used as the favicon (`/public/favicon.png`) and in the sidebar + login screen — replaced the old "A" letter tile.
  - Brand variables exposed as CSS custom properties (`--ayci-brand-primary`, `--ayci-brand-accent`, `--ayci-brand-cyan`, `--ayci-brand-magenta`, `--ayci-brand-warm`, `--ayci-brand-light`) for any future component to consume.

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
