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
