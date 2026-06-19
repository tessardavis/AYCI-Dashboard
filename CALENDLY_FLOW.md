# Calendly → Dashboard flow (for the team)

How a student booking a call ends up ticking the right box on the dashboard.
Written 2026-06-19. Audience: Tessa + Megan + coaches.

## The one model

Every coaching session works the same way:

> **Student books in Calendly → a Zapier zap fires → it POSTs to the dashboard → the dashboard marks the matching "slot" on that student's record.**

Those slots (Call 1–4, mock, 15-min, bonus) are the student's *entitlements*. The
dashboard counts booked-vs-allowed, which powers the over-allowance alerts. So each
zap's whole job is: *"a call got booked → tick the matching box for that student."*

## The map

| Session | Calendly event | Zaps (one per coach) | Dashboard field written |
|---|---|---|---|
| **1:1 prep call (30 min)** | `AYCI 1:1 (30 min)` — **round robin** | 18 / 18b / 18c "Round Robin" | next free **Call 1–4** = `Booked - <coach>` |
| **Mock interview (60 min)** | each coach's own *Mock Interview* event | 14 / 14b / 14c "Mock interview" | **mock_interview_1** = `Booked - <coach>` |
| **15-min debrief** | each coach's own *Debrief / 15-min* event | 15 / 16 / 16b "15 minute call booked" | **fifteen_minute_call** = `Booked` |
| **Testimonial** | `AYCI Testimonial Call` | 19b *(not migrated yet)* | post-cohort metric |

(Plus VIP / Boost & Go / Bonus calls, which follow the same shape.)

## The two concepts that confuse people

### 1. Round-robin vs personal events

- **Round robin** — only the **30-min 1:1** uses this. It's **one shared Calendly event**
  (`AYCI 1:1 (30 min)`, link `calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min`) that
  auto-assigns each booking to one coach in a pool. It's a **team/managed event**, so it
  **doesn't appear on any individual coach's Event Types page** — only a Calendly
  Admin/Owner sees it (under team/managed events). Pool = **Becky, Anoop, Charlotte**.
- **Personal** — mocks and 15-min debriefs. Each coach has their **own** Calendly
  event/link. Nothing shared.

### 2. Why everything comes in threes (Becky / Anoop / Charlotte)

Zapier connects to Calendly **per coach account** — there's no single org-wide trigger.
So every session type needs **one zap per coach**, each listening to that coach's
bookings. For the round-robin, the three zaps each catch the bookings Calendly assigned
to *their* coach. That's why you see trios everywhere.

## How a round-robin booking actually flows (worked example)

1. Student opens `calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min` and books a slot.
2. Calendly's round robin assigns it to, say, **Anoop** (it rotates through Becky/Anoop/Charlotte).
3. The booking lands on **Anoop's** Calendly → his `Invitee Created` trigger fires the
   **Round Robin (Anoop)** zap.
4. The zap POSTs `{email, coach: "Anoop"}` to `…/api/students-db/book-call`.
5. The dashboard fills that student's **next free Call 1–4 slot** with `Booked - Anoop`,
   and returns which slot. If all 4 are already booked (or the email matches no student),
   it alerts #fulfillment-team instead.

All three coaches' round-robin bookings carry the **same** Calendly event
(`AYCI 1:1 (30 min)`) — Calendly just records which coach was assigned. So **each coach's
zap must be triggered on `AYCI 1:1 (30 min)`** (their connection only surfaces the
bookings assigned to them). If a coach's trigger is set to a *personal* event instead, it
won't fire for round-robin bookings.

## Mental model for Megan

For any zap that looks confusing, ask three questions:
1. **Which Calendly event got booked?**
2. **Which zap watches it?** (round-robin 1:1 → 18/18b/18c · mock → 14/14b/14c · 15-min → 15/16/16b)
3. **Which box does it tick on the student?** (Call slot · mock · 15-min)

## Verifying the round-robin (confirmed 2026-06-19)

Pulled from the Calendly API: the link is the managed round-robin event type
`AYCI 1:1 (30 min)` (uri `5ffedd84-90df-425e-bf24-e08e7c7b7bca`, `pooling_type: round_robin`).
Recent 18 bookings distributed to **Becky (12) + Anoop (6)**; Charlotte 0 recently but in
the pool. **Open item:** confirm each coach's zap step-1 Event Type = `AYCI 1:1 (30 min)`
(Becky's is firing; Anoop/Charlotte to confirm with Megan). There's also an
`AYCI 1:1 (60 min)` event (15 recent bookings) — possibly a second round-robin (VIP 1:1s)
with **no book-call zap yet**; confirm whether 60-min 1:1s should count against allowance.
