# SOP — Private Chats (troubleshooting guide for the team)

_For Coralie & Megan. How to keep every private-tier student's coach chat set up,
spot who's been missed, handle "DMs off" and dual-email cases, and know when to
escalate. Last updated 2026-06-16._

> **30-second background.** Every **private-tier student** (Private Plus, VIP,
> Boost & Go, Boost & Go Plus) should have a **coach group chat** in Circle —
> where they get video feedback and ask questions. New chats are created **from the
> dashboard** (Settings → Integrations → **Private chat setup**) with the coaches
> **Tessa, Arub, Coralie, Becky** (Coralie sends the opener — **no Oksana**). This
> SOP is how you catch the ones that slipped through and fix them.

---

## A. Daily / weekly check — who's been missed?

**Fastest scan — Students (DB):**
1. Left menu → **Students (DB)**.
2. Click the **"⚠ Needs setup"** filter.
3. Every current private-tier / Boost & Go student missing their chat (or video
   allowance) shows here with a **⚠ Setup** badge and **"— missing"** under Private chat.

**Authoritative check — the Circle audit** (catches anyone the quick scan can miss):
1. **Settings → Integrations → Private chat setup**.
2. Scroll to **"Backlog audit — no group chat in Circle" → Run audit**.
3. It checks Circle directly and lists every eligible student **not in any coach
   group chat**, each with a **Create chat** button.

> Do the **Needs setup** scan often (e.g. daily during a cohort intake); run the
> **audit** weekly, and any time someone reports a missing chat.

---

## B. Creating a missing chat

In **Private chat setup**:
- **"Ready to create"** lists eligible students who are on Circle with no chat.
- Click **Create chat** → it makes the coach group chat, posts the **tier-specific
  welcome message**, and links it on their row. Done.

**If "Create chat" is greyed out / disabled**, it's one of:
- **"no `<tier>` template"** → that tier's welcome message isn't set. Add it in the
  same card → **Welcome message per tier** → pick the tab → paste → Save. *(Plain
  Boost & Go template may still need adding.)*
- Coach config incomplete (every coach needs a Circle email + one set as sender).

> **Never worry about duplicates.** Creating from the dashboard only ever makes a
> chat for someone who has **none** — it checks all coaches first, so it won't spawn
> a second thread, and video replies keep going to the existing chat.

---

## C. Troubleshooting flow — "X should have a chat but doesn't"

Work down this list (it's the exact order to check):

**1. Do they already have one?**
Students (DB) → search their name → if **Private chat** shows a link, they have a
chat. (They may just not have found it in Circle.)

**2. Are they eligible?**
Open their row (Edit). **Tier** must be Private Plus / VIP / Boost & Go (or **Boost
& Go** dropdown set). A plain **Academy** student doesn't get a coach chat.
⚠️ **Tier-label gotcha:** the tier must be a value the dashboard recognises. If a
student is clearly private-tier but **doesn't appear in Needs setup or Ready to
create at all**, the tier text may be an unrecognised variant — **tell Tessa/Claude
the exact tier string** (e.g. it once read "Private Plus" instead of "Academy
Private Plus" and made students invisible).

**3. Are their Circle DMs off?** (most common real blocker)
- If their row shows an orange **"Awaiting DMs"** status, that's it — a chat can't be
  created until they turn DMs on.
- If you're not sure, just click **Create chat**. If it fails because DMs are off,
  they get flagged **Awaiting DMs**.
- **Fix:** message the student → ask them to **turn Circle DMs on** (*Circle →
  their avatar → Settings → Messaging → allow direct messages*) → then **Create
  chat** → then clear the flag (row → Edit → empty **Private chat status** → Save;
  it also clears automatically when the chat is created).

**4. Are they on Circle under a different email?** (dual-email)
The dashboard matches on **both** their email and Circle email. If **Create chat**
says **"not on Circle"** but you know they're a member, they likely joined Circle
with a **different email** than they signed up with. Find their Circle email
(search Circle by name), add it to their row (Edit → **Circle email** → Save), then
**Create chat**.

**5. None of the above?**
They're eligible, on Circle, DMs on, no chat → they simply slipped through. Just
**Create chat**. If that errors, **escalate** (see §E) with the exact message.

---

## D. "Who doesn't have their DMs on?"

There's no Circle setting we can read directly, so DMs-off only surfaces **when a
chat creation is attempted and fails**:
- Students (DB) → **Needs setup** → anyone with the orange **"Awaiting DMs"** badge
  has been confirmed DMs-off (chase them to enable DMs, then create).
- To proactively find them: run **Create chat** for each student in "Ready to
  create" — the ones whose DMs are off will fail and get the **Awaiting DMs** flag,
  which both confirms it and puts them on the chase list.

---

## E. When to escalate (to Tessa / Claude)

Escalate with the **student's name + email + the exact on-screen message** if:
- A clearly private-tier student **never appears** in Needs setup or Ready to
  create (likely a tier-label issue — a code fix).
- **Create chat** errors with anything other than "not on Circle" / DMs-off.
- The same student keeps losing their chat or getting duplicates.
- The audit shows a **large batch** missing at once (may be an upstream issue worth
  fixing at the source, not one-by-one).

---

## Quick reference

| You want to… | Where | What you do |
|---|---|---|
| See who still needs a chat (fast) | Students (DB) → **⚠ Needs setup** | ⚠ Setup badge · "— missing" |
| Confirm who has no chat in Circle | Private chat setup → **Run audit** | the no-chat list + Create |
| Create a chat | Private chat setup → **Create chat** | chat made + welcome posted + linked |
| Handle DMs-off | Students (DB) → **Awaiting DMs** badge | ask them to enable DMs → Create → clear status |
| Fix "not on Circle" (dual-email) | row → Edit → **Circle email** | add their Circle email → Create |
| Hand a student their interview form | Students (DB) row → **Copy link** | sends pre-filled Tally link |

## Good to know
- New chats are **Coralie-sent, no Oksana**. Existing chats can't have people
  removed (Circle limitation), so old chats may still show Oksana — that's expected.
- Access: these pages are **admin / students-board** only. If you can't see them,
  ask Tessa to add the board (Settings → Users).
