# Retiring the Monday board(s) - migration plan

**Goal:** make the dashboard the system of record and switch off Monday, without
losing data or breaking any flow. This is a staged migration, not a big-bang cutover.

## Why it's not a quick job (the current dependency)

The dashboard's whole student database, `academy_members`, is a **15-minute mirror
of the Monday "Academy Members" board (`1956295952`)**:

- Each student row is **keyed by their Monday item id** (`_id = <monday_item_id>`).
- The row stores the raw Monday columns (`columns` / `columns_by_id`).
- The dashboard already **owns** some fields via `dashboard_edited_fields` (pinned so
  the Monday sync can't overwrite them - e.g. interview date, Boost & Go, Boss, bonus
  call). This is the seed of making the dashboard primary: today it owns *some* fields;
  the migration is about it owning *all* of them.

So Monday is doing three jobs we must re-home before we can switch it off:
1. **Source of new students** (contacts added on Monday → mirrored in).
2. **Data entry surface** (team edits fields on Monday).
3. **Write target** (zaps push purchase/interview/Boss data to Monday).

Other Monday boards are **separate, smaller** decommissions and can go independently:
- `5083952249` Private-Tier Videos - already mirrored to Mongo (largely done).
- `5095636561` Student Wins Tracker - being retired (chase moved to the dashboard).

## Phase 0 - get the interview / Boss flow off Monday  *(= "#1", in progress)*

Not part of the board decommission itself, but it removes the biggest *active* Monday
dependency in a fragile flow and proves the pattern (Tally → dashboard direct).

- [x] **Success path:** `POST /api/students-db/tally/interview` marks Boss on a
  Substantive "I got it!" (replaces zap 8a + the Monday-triggered 8c). **Live &
  verified end-to-end** (native Tally Webhook on form nGyGj2 → dashboard →
  matched a real student → idempotent). The student's follow-up link **pre-fills
  their Circle email**, and the receiver matches on **any** email field vs
  email / circle_email / other_emails - so the dual-email gap is largely closed;
  a mismatch just means no auto-mark and Coralie marks by hand.
- [ ] **Turn off 8c** and discard draft 8a (dashboard now owns the success path).
- [ ] **Unsuccessful path (Stage 2):** receiver detects "didn't get it" and fires the
  15-min-link follow-up (Circle DM <4 days / email >4 days) - replaces the
  Monday-triggered 8d.
- [ ] **Interview dates (Stage 3):** receiver records the interview date straight to
  the dashboard's Upcoming Interviews - replaces zap "3" (Tally→Monday).

## Phase 1 - field inventory & origin audit  *(the foundation)*

For **every** field the dashboard reads out of the Monday mirror, classify its *true*
origin. This is the single most important step - it tells us what's easy vs hard.

| Origin class | Re-home approach |
|---|---|
| **Derived elsewhere** (Kit tags, Circle, Calendly, Tally) | Re-source directly from that system; stop reading it from Monday. |
| **Dashboard-edited** (already in `dashboard_edited_fields`) | No change - already owned. |
| **Set by a zap via update-by-email** (e.g. Kajabi purchase) | Repoint the zap to a dashboard endpoint (see Phase 3). |
| **Hand-keyed on Monday by the team** | Must become **editable in the dashboard** (Phase 3) so data entry moves. |

Deliverable: a table of every mirrored column → its class → its re-home. Nothing else
in this plan is safe to finish until this exists.

## Phase 2 - re-source the derivable fields

For every "derived elsewhere" field, wire the dashboard to read it from the real
source (Kit/Circle/Calendly/Tally connectors already exist) instead of Monday. After
this, the mirror is only carrying hand-keyed + zap-written fields.

## Phase 3 - make the dashboard the write target & data-entry surface

- **Repoint write zaps:** the Kajabi purchase-capture (update-by-email) and any other
  zap that writes to Monday should call a dashboard endpoint instead (same pattern as
  `mark-boss-by-email`). Each field it sets becomes pinned/owned.
- **Make hand-keyed fields editable in the dashboard** (extend the existing in-place
  edit + `dashboard_edited_fields` pattern) so the team stops typing into Monday.
- Run **dual-write** for a cooldown: dashboard is authoritative, Monday still receives
  a copy, so nothing breaks while we watch.

## Phase 4 - new-student intake into the dashboard

Today a new contact is created **on Monday** (which gives the mirror row its `_id`).
Replace that with dashboard-native intake:
- Create the `academy_members` row directly from the purchase/join event (Kajabi/Kit),
  with a **new stable id scheme** (generated id, not a Monday item id).
- Existing rows keep their Monday-id `_id` (opaque identifier - fine, nothing else
  needs Monday to resolve it).

## Phase 5 - flip to primary

- Stop the 15-minute Monday→Mongo sync; `academy_members` is now authoritative.
- Keep Monday **read-only** for a cooldown window as a safety net (and export a full
  CSV/JSON snapshot first).
- Watch for anything that silently depended on the sync.

## Phase 6 - archive the board

Once a cooldown passes with no regressions, archive `1956295952` (and the other boards
as their own mini-migrations complete).

## Key risks & mitigations

- **Keying (`_id = monday item id`):** keep existing ids as opaque identifiers; only
  *new* students get the new scheme. No re-keying of existing rows.
- **Silent Monday-only data:** Phase 1's audit is what prevents losing a hand-keyed
  field nobody remembered. Do it thoroughly.
- **Cutover risk:** dual-write (Phase 3) + read-only cooldown (Phase 5) mean we never
  have a moment where data can only live in one unproven place.
- **Backups:** full export before Phase 5; the nightly Mongo snapshots continue.

## Status

| Phase | Status |
|---|---|
| 0 - interview/Boss flow off Monday | 🔨 Stage 1 live; Stages 2-3 to build |
| 1 - field inventory & origin audit | ⬜ not started (the next real step for #2) |
| 2 - re-source derivable fields | ⬜ |
| 3 - dashboard as write target + data entry | ⬜ |
| 4 - dashboard-native intake | ⬜ |
| 5 - flip to primary | ⬜ |
| 6 - archive board | ⬜ |
