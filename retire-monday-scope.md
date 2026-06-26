# Retiring Monday.com - Migration Scope

_Scoping doc · AYCI Dashboard · prepared 2026-06-22_

## TL;DR

The dashboard has **already** quietly migrated most of the way off Monday:

- **Dashboard edits are Mongo-only.** Every dashboard write goes to the `academy_members` Mongo mirror and is "pinned" (`dashboard_edited_fields`) so the sync can't clobber it. The dashboard does **not** write student data back to the Academy Members board.
- **Monday's only remaining job for Academy Members is to *feed* the mirror** via a 15-minute one-way sync.

So "retire Monday" is mostly about **(a)** moving the handful of features that still read Monday *live* onto the mirror, **(b)** safely turning off the sync (which currently can overwrite and delete data), and **(c)** making sure new students can be created without a Monday row.

The risky parts are narrow and known. There are only **two** write-backs to Monday left, and one of them is on a *different* board.

---

## Current state

```
            ┌─────────────────────────────────────────────┐
 Monday     │  Academy Members board (1956295952)          │
 (board)    └───────────────┬─────────────────────────────┘
                            │  15-min one-way sync (full_sync)
                            │  • overwrites UNPINNED fields
                            ▼  • PURGES rows not on the board
            ┌─────────────────────────────────────────────┐
 Mongo      │  db.academy_members  (the "mirror")           │◄── Zapier intake
 (truth)    │  • pinned fields are dashboard-owned          │    (auto: rows,
            └───┬───────────────────────────────┬──────────┘     by email)
                │ mirror reads (fast path)       │ LIVE Monday reads
                ▼                                ▼ (still hit the board)
   Upcoming Interviews, Student Lookup,   Private Tier Utilisation, Over-Allowance,
   Students DB, routes/interviews,        Cohort, Student Prewarm, Scorecard Auto,
   refunds, bg_audit, private_video_alerts Onboarding Gap
```

### What writes to Monday today (the whole list)
1. **`student_edit.py`** - renames the Academy Members item when a student's name is edited. *(Mongo also updated.)*
2. **`private_videos.py`** - updates status / assignee / replied / reply-link on the **Private Videos board (5083952249)** - a *separate* board, not Academy Members.

That's it. Nothing else writes to Monday.

### What still *reads* Monday live (must move to the mirror)
`private_tier_utilisation.py`, `over_allowance_alerts.py`, `cohort.py`, `student_prewarm.py`, `scorecard_auto.py`, `onboarding_gap.py`, plus the live-Monday *fallback* branches in `upcoming_interviews.py` and `student_lookup.py`. The generic scorecard connector (`connectors.py`) also queries Monday.

### The dangerous bits in the sync (`academy_members_mirror.py`)
- **Stale purge** (`delete_many` of rows whose `_id` isn't in the latest Monday feed). If Monday is frozen/edited while the sync runs, this can **delete dashboard rows**. Auto-created (`auto:`) rows are excluded, but Monday-origin rows are not.
- **Unpinned-field overwrite.** Any field a coach hasn't explicitly pinned is still owned by Monday, so a stale Monday board slowly drags dashboard data backwards.

---

## Open questions (need answers before Phase 2)

1. **How do NEW students get created today?** All via the Zapier/Kajabi **intake endpoint** (`POST /api/students-db/intake` → `auto:` rows), or do some still require a manually-created Monday row? → Determines whether we must build a dashboard "Add student" flow *before* cutting the sync.
2. **Is the Private Videos board (5083952249) also being retired**, or just Academy Members? Coaches may still log video reviews there. → Determines whether `private_videos.py` / `coach_activity.py` need migrating too.
3. **Do any Zapier zaps still WRITE to the Academy Members board** (status fields the dashboard then reads via the mirror - e.g. mock/call/15-min/boss-badge zaps)? If so they must be repointed to the intake endpoint first, or those fields freeze.
4. **Historical data:** is the Mongo mirror a complete-enough copy, or do we need a one-time export of the Monday board first? (The mirror stores all columns, but rows archived/deleted on Monday in the past were purged.)

---

## Proposed phases

### Phase 1 - Move all reads onto the mirror _(low risk, no behaviour change)_
- Convert the 8 live-Monday readers to read `db.academy_members` instead (they already have `columns_by_id` in the mirror doc, so it's mostly mechanical).
- `cohort.py` also reads the board's **column *schema*** (the "Cohort Joined" dropdown options) - source that from config/Mongo instead of a live schema query.
- Delete the live-Monday fallback branches in `upcoming_interviews.py` / `student_lookup.py` (or keep them but pointed at nothing).
- **Outcome:** nothing reads Monday live anymore; behaviour identical because the mirror is still synced.

### Phase 2 - Make the sync safe, then freeze it _(the pivotal step)_
- **First, disable the stale-purge** (so the sync can never delete rows).
- Confirm new-student creation no longer needs Monday (Q1) - build a dashboard "Add student" path if required.
- Repoint any Monday-writing zaps to the intake endpoint (Q3).
- **Then stop the 15-min `full_sync`.** From here, the mirror is the sole source of truth and Monday edits are ignored (which is the goal).
- **Outcome:** Monday is fully decoupled operationally; nothing reads or syncs it.

### Phase 3 - Replace the two write-backs
- `student_edit.py`: drop the Monday rename mutation; Mongo-only.
- `private_videos.py`: depends on Q2 - keep (if that board lives on) or migrate video submissions to Mongo.

### Phase 4 - Delete Monday from the codebase _(cleanup)_
- Remove `MONDAY_API_TOKEN`, `connectors.monday_*`, the Monday-fetch half of the mirror module (repurpose the module as the primary store).
- **Consolidate the duplicated `COL_*` constants.** The same column IDs (email, tier, `interview_date`, call/mock/bonus, …) are currently redefined in ~8 files - collapse to one module as part of this.

---

## Effort / risk summary

| Phase | Scope | Risk | Reversible? |
|---|---|---|---|
| 1 · Reads → mirror | 8 modules, mechanical | Low | Yes |
| 2 · Freeze sync | Purge off, sync off, intake/zap checks | **High** (data loss if Q1/Q3 wrong) | Yes (re-enable sync) |
| 3 · Write-backs | 2 modules | Low-Med | Yes |
| 4 · Delete + consolidate | Cleanup, constant consolidation | Low | n/a |

**Recommended starting point:** Phase 1 is safe and can ship immediately - it removes the live-Monday reads with zero behaviour change and shrinks the blast radius before we touch the sync. The just-merged interview-date editor is the template for making fields dashboard-owned.

The one thing to settle before Phase 2 is **Q1 (how new students are created)** - that's the only place where turning off the sync could make students silently disappear.
