# Zapier next-batch runbook — Calendly booking zaps (2026-06-19)

Finishes the **Phase-1'd Calendly zaps** by removing their Monday safety-net
steps (Phase 1 ran 2026-06-04/05 — well past the ~1 week verify window, so
they're safe to tear down). After this batch, no Calendly booking writes
Monday. Backend endpoints are already live; this is all Zapier-UI work.

**Golden rule for every teardown:** after deleting a Monday step, check every
*later* step for a field that was mapped from a Monday output (most commonly
**Circle: Find Member**'s email). Re-map it to the **Calendly trigger's invitee
email** instead, or it'll break when the Monday step is gone.

**Per zap:** make the edits → turn the zap **on** → book one test Calendly slot
→ confirm the dashboard updated (Student Lookup, or `dashboard_edited_fields`
on the row) → tick it here.

---

## A. 1:1 Round Robin — Phase-2 teardown  (zaps 18 / 18b / 18c)

Coaches: **Anoop (18) · Charlotte (18b) · Becky (18c).** Each is identical bar the coach name.

Current shape (Phase 1): `Calendly: Invitee Created` → **Webhooks POST `/api/students-db/book-call`** `{email, coach}` → [Monday Get Items] → [Monday Get Column Values] → [AI ×2] → Paths (Call 1 / 2 / 3 / 4 / Fallback).

**Do this:**
1. **Delete** the two Monday steps: `Get Items by Column Value` and `Get Column Values`.
2. **Delete** both `AI by Zapier` steps.
3. **Delete** the four **Call 1–4 paths** (each is just a Monday `Update Item` — `book-call` now does the slot logic server-side).
4. Replace the whole Paths block with **one Filter** right after the Webhooks step:
   - **Only continue if** `slot` (from the book-call response) **Does not exist / Is empty.**
   - `book-call` returns `slot` = 1–4 on success, or `slot: null, reason: "all_slots_booked"`. So an empty `slot` = every slot already booked = the only case the fallback should fire.
5. **Keep** the existing **Fallback** steps after that Filter: `Formatter (Date/Time)` → `Circle: Find Member` → `Slack alert`. ⚠️ Re-map `Circle: Find Member`'s email to the **Calendly invitee email**.

Result: a booking just POSTs to `book-call`; if all 4 slots are full, the coach gets the same Slack alert as before.

- [x] 18 Anoop — published 2026-06-19
- [x] 18b Charlotte — published 2026-06-19
- [x] 18c Becky — published 2026-06-19

**Done 2026-06-19.** All three torn down to `Calendly → book-call POST → Filter (slot empty) → Slack #fulfillment-team`. Monday read/AI/Paths steps removed. `book-call` hardened along the way: 200 (not 404) on no-match, combined-identity email lookup, and a uniform response schema (`reason` = booked|all_slots_booked|student_not_found) so the Slack alert always has Email/Reason to map.

> **⏳ OPEN — waiting on Megan (as of 2026-06-19):** Tessa is waiting for Megan to confirm the right Calendly event types trigger these zaps.
>
> **Round-robin resolved via Calendly API (2026-06-19):** the student link `/d/cxkz-kf9-xb4/ayci-1-1-30-min` is a **single managed round-robin event type** `AYCI 1:1 (30 min)` (uri `5ffedd84-90df-425e-bf24-e08e7c7b7bca`, `pooling_type: round_robin`, `profile: null` — which is why it doesn't appear under any coach's personal event types). Recent 18 bookings all carry that one event_type URI, distributed to **Becky (12) + Anoop (6)**; Charlotte 0 recently but is in the intended pool. **Each coach's zap trigger must be scoped to `AYCI 1:1 (30 min)`** — if it's not selectable in the Event-Type dropdown for that coach's connection, use *All Event Types* + a Filter `event type name = AYCI 1:1 (30 min)`, else the zap fires on their mock/boost/personal bookings and burns a 1:1 slot. Likely the cause of Anoop looking quiet (wrong event type on his trigger).
>
> **⚠️ Also flag for Megan:** there's an `AYCI 1:1 (60 min)` event with 15 recent bookings — possibly a *second* round-robin (VIP 1:1s). If those 60-min calls should count against the call allowance, they need their own book-call zap (none exists today).
>
> Pool is intended to be **only Anoop/Charlotte/Becky** (confirmed by Tessa) for the 30-min — so the 3 zaps are the complete set; no Megan/Tessa zap needed. Don't consider A fully closed until Megan confirms the triggers.

---

## B. 15-minute call — remove Monday safety net  (zaps 15 / 16 / 16b)

Coaches: **Charlotte (15) · Becky (16) · Anoop (16b).** Already writing `fifteen_minute_call: "Booked"` via `update-by-email`; Monday steps were left as a net.

Current shape: `Calendly: Invitee Created` → **Webhooks POST `/api/students-db/update-by-email`** `{email, fifteen_minute_call: "Booked"}` → [Monday Get Items] → [Monday Update Item] → Slack.

**Do this:**
1. **Delete** the `Monday: Get Items by Column Value` step.
2. **Delete** the `Monday: Update Item` step.
3. **Keep** the Slack step. ⚠️ If Slack mapped any field from the Monday steps, re-map from the Calendly trigger or the Webhooks response.

- [ ] 15 Charlotte
- [ ] 16 Becky
- [ ] 16b Anoop

---

## C. Mock Interview — verify clean  (zaps 14 / 14b / 14c)

Coaches: **Becky (14) · Anoop (14b) · Charlotte (14c).** The audit shows these were
re-pointed to `update-by-email` (`mock_interview_1: "Booked - <coach>"`, eligibility
filter now off the endpoint's `previous_values`). Likely already fully torn down.

**Do this — just confirm:**
1. Open each. If a `Monday: Get Items` / `Monday: Update Item` step is still present as a leftover net, delete it (same as batch B).
2. If the only Monday steps are already gone → nothing to do, just tick.

- [ ] 14 Becky
- [ ] 14b Anoop
- [ ] 14c Charlotte

---

## D. Testimonial call  (zap 19b) — NEEDS ONE ANSWER FIRST

`Calendly: AYCI Interview booked` → `Monday: Find student in post-cohort metrics` →
`Monday: Update column 'Zap -…'`. This writes to a **post-cohort metrics** view.

**Question before I give steps:** is that the **Academy Members** board (1956295952)
or a separate post-cohort/metrics board? If it's a *different* board, it's out of
scope for this retirement (leave it). If it's Academy Members, tell me which column
it flips and I'll map it to an `update-by-email` field (likely `testimonial_call`
or a bonus slot) for the same teardown pattern.

- [ ] 19b — blocked on the board/column answer above
