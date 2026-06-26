# Zapier: Oksana → Coralie connection handover

**Why:** several zaps authenticate their **Circle** steps as **Oksana's** account.
When her Circle account is deactivated, those steps **break** (not just wrong
sender) - `Send Direct Message` sends *from* the connected account, and `Find
Member` / `Tag Member` / `Add to Space` / `Start Group Chat` *authenticate as* it.
So every Circle step (and Circle **trigger**) currently on Oksana must move to
**Coralie** before Oksana is offboarded.

**Coralie's Circle identity:** `coralie.fairon@yahoo.co.uk` (NOT her work email -
that's not a Circle member). She has a Zapier Circle connection already (the
"Coralie" token). **She must have Circle moderator/admin rights** for the
Tag / Add-to-Space / Start-Group-Chat steps to work as her - confirm in Circle.

## How to switch a step (same for every row below)
1. Open the zap → click the Circle step.
2. In the step's **Setup**, the **Circle account / connection** selector is near
   the top - change it from **Oksana** to **Coralie** (`coralie.fairon@...`).
3. Do this for **every** Circle step in the zap (switching one doesn't switch the
   others) - and the **trigger** too if it's a Circle trigger on Oksana's account.
4. **Test** the step, then **Publish**. Tick the box here.

## Checklist (the `(Oksana)` zaps from ZAPIER_AUDIT.md)

> For each, switch every listed Circle step's connection to Coralie. Step names
> are from the audit - confirm against the live zap (counts may vary slightly).

- [ ] **17 - `AYCI 1:1 Call booking reminders - DM on Circle (Oksana)`**
  Circle steps: **Find Member**, **Send DM**.
- [ ] **46 - `[AYCI JUNE-26] Private Chat for Legacy Upgrades`**
  Circle steps: **Find Member**, **Tag Member**, **Start Group Chat**, **Send DM**.
- [ ] **47 - `[AYCI JUNE-26] Private Chat for VIP & Private Plus`**
  Circle steps: **Find Member**, **Tag Member**, **Start Group Chat**, **Send DM**.
  *(Check 47b - the linked/duplicate variant - and switch it too if it's active.)*
- [ ] **53 - `[AYCI] Private Chat for the Boost & Go`**
  Circle steps: **Find Member**, **Tag Member**, **Start Group Chat**, **Send DM**.
- [ ] **68 - `Student Wins Tracking - First Message (Oksana)`**
  Circle steps: **Find Member**, **Send DM**.
- [ ] **72 - `2. When Cohort Tag added in Circle update contact with cohort dates`**
  ⚠️ **Trigger** is `Circle: New Tagged Member` - if that trigger's connection is
  Oksana's, it **stops firing** on deactivation. Switch the **trigger** connection
  (+ any Circle action steps) to Coralie.
- [ ] **8b - `Substantive success - tags Boss on Circle/CK + bonus access`** (draft)
  Circle steps: **Find Member**, **Tag Member**, **Add to Space**, **Send DM**.
  This is the parked catch-hook draft - switching its 4 Circle steps to Coralie is
  the blocker to publishing it (see boss-badge migration notes).

### Lower priority (Grid / AYGI - cohort not until Jan 2027)
- [ ] **54 - `[AYGI 2025] Private Chat for the VIP members`**
  Circle steps: Find Member, Tag, Start Group Chat, Send DM. Still breaks on
  deactivation (would just error harmlessly with no Grid cohort running), so
  switch it whenever convenient.

## Catch-all
Any **other** zap with a Circle step or Circle trigger: open it and check the
connection - if it shows **Oksana**, switch it to Coralie. The list above is the
known set from the last audit, but the deactivation breaks *anything* on her
Circle login, so a quick scan of all Circle-using zaps before she goes is worth it.

## Not a zap - but same deadline
- **Coralie's dashboard Gmail inbox** has an expired token (`invalid_grant`) - she
  re-connects via the dashboard Gmail flow, or support email to `coralie@` isn't ticketed.
- **Settings → Private chat config → sender = `coralie.fairon@yahoo.co.uk`** - needed
  for the dashboard's video-answer reply + new-chat creation to run as Coralie.
- Oksana's **other (non-Circle) Zapier connections** (e.g. any Gmail/Slack steps on
  her account) - same deactivation risk; check those too.
