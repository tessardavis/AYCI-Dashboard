import { useState, useMemo } from "react";
import { Phone, Video, Award, Briefcase, Calendar, CheckCircle2, Gift, Loader2, Plus, Minus } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";

// Holding any of these Kit tags (current cohort, matched by suffix) = eligible
// for a bonus call. Mirrors backend calendly_webhook.ELIGIBILITY_TAG_SUFFIXES.
const BONUS_ELIGIBILITY_SUFFIXES = [
  "Purchase - Live webinar",
  "Legacy Video Launch Day 1 Upgrade",
  "Legacy Video Launch Last Day Upgrade",
  "Cart Close Signup",
  "Ad Hoc Bonus Call",
];
const BONUS_BOOKED_SUFFIX = "1:1 Call Booked";

const fmtDate = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
};

const fmtShort = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
    });
  } catch {
    return iso;
  }
};

export default function CoachSummary({ result }) {
  const monday = result?.monday?.data || {};
  const allowances = monday.allowances || {};
  const tier = monday?.columns?.Tier?.text || "-";
  const calls = allowances.calls_30min;
  const mocks = allowances.mock_interviews;
  const bonus = allowances.bonus_calls;
  const videos = allowances.videos;

  const calendly = result?.calendly?.data || {};
  const upcomingCalls = calendly?.upcoming || [];
  const pastCalls = calendly?.past || [];
  const lastCall = pastCalls[0];
  const nextCall = upcomingCalls[0];
  const tallyType = result?.tally?.type;
  const tallyCount = result?.tally?.history_count || 0;

  // Bonus-call eligibility, read off the student's ConvertKit tags.
  const kitTags = result?.convertkit?.data?.tags || [];
  const hasTagSuffix = (suf) => {
    const s = suf.toLowerCase();
    return kitTags.some((t) => {
      const n = (t.name || "").replace(/\s+/g, " ").trim().toLowerCase();
      return n.endsWith("] " + s) || n === s;
    });
  };
  const bonusBooked = hasTagSuffix(BONUS_BOOKED_SUFFIX);
  const eligibleVia = BONUS_ELIGIBILITY_SUFFIXES.find((s) => hasTagSuffix(s));
  // Booking lifecycle from the student record (set by Calendly webhook + coaches).
  const bonusCall = monday.bonus_call || {};
  // Private-tier (Private Plus / VIP) call allowance + bookings (null if the
  // student isn't on a private tier). Computed server-side from tier + bookings.
  const privateCalls = monday.private_calls;
  const bonusStatusTone =
    /no.?show|cancel/i.test(bonusCall.status || "") ? "bg-rose-50 text-rose-700 border-rose-200"
      : /reschedul/i.test(bonusCall.status || "") ? "bg-amber-50 text-amber-700 border-amber-200"
        : "bg-emerald-50 text-emerald-700 border-emerald-200";
  // Every email on file (primary + Circle + other), so the team sees all the
  // addresses this student is known by - not just the one that was searched.
  const linkedEmails = [...new Set(
    [monday.email, monday.circle_email, ...((monday.other_emails || "").split(/[,;]/))]
      .map((e) => (e || "").trim().toLowerCase())
      .filter((e) => e && e.includes("@"))
  )];
  const [markedNow, setMarkedNow] = useState(false);
  const [marking, setMarking] = useState(false);
  const eligible = bonusBooked || !!eligibleVia || markedNow;

  const markEligible = async () => {
    setMarking(true);
    try {
      await apiClient.post("/bonus-call/mark-eligible", { email: result?.email }, { timeout: 30000 });
      toast.success("Marked eligible - tagged 'Ad Hoc Bonus Call' in Kit");
      setMarkedNow(true);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Couldn't mark eligible");
    } finally {
      setMarking(false);
    }
  };

  const totalCallsRemaining =
    (calls?.available || 0) + (mocks?.available || 0) + (bonus?.available || 0);
  const totalCallsUsed =
    (calls?.used || 0) + (mocks?.used || 0) + (bonus?.used || 0);
  const totalCallsBooked = upcomingCalls.length + pastCalls.length;

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="coach-summary"
    >
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
          Coach view
        </span>
        <span
          className="px-2 py-0.5 bg-violet-50 text-violet-700 border border-violet-200 rounded-full text-[10px] uppercase tracking-wider font-semibold"
          data-testid="coach-summary-tier"
        >
          {tier}
        </span>
        {tallyType && (
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 border rounded-full text-[10px] uppercase tracking-wider font-semibold ${
              tallyType.toLowerCase().includes("locum")
                ? "bg-amber-50 text-amber-700 border-amber-200"
                : "bg-sky-50 text-sky-700 border-sky-200"
            }`}
            title="Latest interview type from Tally"
          >
            <Briefcase className="w-3 h-3" />
            {tallyType}
          </span>
        )}
        {tallyCount > 0 && (
          <span className="text-[10px] text-[var(--ayci-ink-muted)]">
            · {tallyCount} prior interview{tallyCount > 1 ? "s" : ""}
          </span>
        )}
      </div>

      {linkedEmails.length > 1 && (
        <div className="flex items-start gap-2 mb-3 text-[11px] text-[var(--ayci-ink-muted)]" data-testid="linked-emails">
          <span className="uppercase tracking-wider font-subhead shrink-0 mt-0.5">Emails</span>
          <span className="flex flex-wrap gap-x-2 gap-y-0.5">
            {linkedEmails.map((e) => (
              <span key={e} className="bg-slate-50 border border-[var(--ayci-border)] rounded px-1.5 py-0.5">{e}</span>
            ))}
          </span>
        </div>
      )}

      <div className="flex items-center gap-2 mb-3 flex-wrap" data-testid="bonus-call-eligibility">
        <span className="text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
          Bonus call
        </span>
        {bonusCall.status ? (
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 border rounded-full text-[10px] uppercase tracking-wider font-semibold ${bonusStatusTone}`}
            title="Bonus call status (from Calendly or set by a coach)"
          >
            <Gift className="w-3 h-3" /> {bonusCall.status}
            {(bonusCall.date || bonusCall.coach) && (
              <span className="normal-case font-normal opacity-80">
                {bonusCall.date ? `· ${fmtShort(bonusCall.date)}` : ""}
                {bonusCall.coach ? ` · ${bonusCall.coach}` : ""}
              </span>
            )}
          </span>
        ) : bonusBooked ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full text-[10px] uppercase tracking-wider font-semibold">
            <Gift className="w-3 h-3" /> Booked
          </span>
        ) : eligible ? (
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full text-[10px] uppercase tracking-wider font-semibold"
            title={eligibleVia ? `Eligible via "${eligibleVia}" Kit tag` : "Marked eligible (ad hoc)"}
          >
            <Gift className="w-3 h-3" /> Eligible
            <span className="normal-case font-normal opacity-80">· {eligibleVia || "ad hoc"}</span>
          </span>
        ) : (
          <>
            <span className="text-[10px] text-[var(--ayci-ink-muted)]">Not eligible</span>
            {result?.email && (
              <button
                type="button"
                onClick={markEligible}
                disabled={marking}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-[var(--ayci-border)] text-[10px] uppercase tracking-wider font-semibold text-[var(--ayci-teal)] hover:bg-slate-50 disabled:opacity-50"
                data-testid="mark-bonus-eligible"
                title="Tag this student 'Ad Hoc Bonus Call' in Kit so they get the booking link"
              >
                {marking ? <Loader2 className="w-3 h-3 animate-spin" /> : <Gift className="w-3 h-3" />}
                Mark eligible (ad hoc)
              </button>
            )}
          </>
        )}
      </div>

      {privateCalls?.eligible && (
        <PrivateCallsBlock summary={privateCalls} email={result?.email} />
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <CallsStat
          callsRemaining={totalCallsRemaining}
          callsUsed={totalCallsUsed}
          callsTotal={(calls?.total || 0) + (mocks?.total || 0) + (bonus?.total || 0)}
          nextCall={nextCall}
          upcomingCount={upcomingCalls.length}
          pastCount={pastCalls.length}
          totalBooked={totalCallsBooked}
        />
        <SummaryStat
          icon={Video}
          label="Videos remaining"
          value={videos?.remaining ?? "-"}
          sub={
            videos?.allowance
              ? `${videos.submitted}/${videos.allowance} submitted`
              : "Not in tier"
          }
          tone="violet"
          testid="summary-videos"
        />
        <SummaryStat
          icon={Award}
          label="Mocks left"
          value={mocks?.available ?? 0}
          sub={`${mocks?.used || 0} used · ${mocks?.total || 0} eligible`}
          tone="rose"
          testid="summary-mocks"
        />
        <SummaryStat
          icon={Calendar}
          label="Last call"
          value={lastCall ? fmtShort(lastCall.start_time) : "-"}
          sub={lastCall ? lastCall.name : "No Calendly history"}
          tone="amber"
          testid="summary-last-call"
        />
      </div>
    </div>
  );
}

function CallsStat({
  callsRemaining,
  callsUsed,
  callsTotal,
  nextCall,
  upcomingCount,
  pastCount,
  totalBooked,
}) {
  return (
    <div
      className="border rounded-lg p-3 bg-emerald-50 border-emerald-200 flex flex-col"
      data-testid="summary-calls"
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
        <Phone className="w-3 h-3" />
        Calls
      </div>
      {nextCall ? (
        <>
          <div className="flex items-baseline gap-1.5 mt-1">
            <span className="font-display font-bold text-lg text-emerald-800 leading-tight">
              {fmtShort(nextCall.start_time)}
            </span>
            <span className="inline-flex items-center gap-0.5 text-[10px] font-bold text-emerald-700 bg-white border border-emerald-300 px-1.5 py-0.5 rounded-full">
              <CheckCircle2 className="w-3 h-3" />
              Next
            </span>
          </div>
          <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5 truncate" title={nextCall.name}>
            {nextCall.name}
          </div>
          <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-1.5 pt-1.5 border-t border-emerald-200/60">
            <span className="font-semibold text-emerald-800">{callsRemaining} left</span> ·{" "}
            {callsUsed}/{callsTotal} used
            {upcomingCount > 1 && <span> · {upcomingCount} upcoming</span>}
          </div>
        </>
      ) : totalBooked > 0 ? (
        <>
          <div className="font-display font-bold text-2xl text-[var(--ayci-ink)] mt-1 leading-tight">
            {callsRemaining}
          </div>
          <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5">
            <span className="font-semibold text-emerald-800">remaining</span> · {callsUsed}/{callsTotal} used
          </div>
          <div className="text-[10px] text-amber-700 mt-1.5 pt-1.5 border-t border-emerald-200/60 font-semibold">
            ⚠ No upcoming call booked
          </div>
        </>
      ) : (
        <>
          <div className="font-display font-bold text-2xl text-[var(--ayci-ink)] mt-1 leading-tight">
            {callsRemaining}
          </div>
          <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5">
            remaining · {callsTotal} total
          </div>
          {callsTotal > 0 && (
            <div className="text-[10px] text-amber-700 mt-1.5 pt-1.5 border-t border-emerald-200/60 font-semibold">
              ⚠ Hasn't booked any call yet
            </div>
          )}
        </>
      )}
    </div>
  );
}

const privateStatusTone = (status) =>
  /no.?show|cancel/i.test(status || "") ? "bg-rose-50 text-rose-700 border-rose-200"
    : /reschedul/i.test(status || "") ? "bg-amber-50 text-amber-700 border-amber-200"
      : /attend|done/i.test(status || "") ? "bg-emerald-50 text-emerald-700 border-emerald-200"
        : "bg-sky-50 text-sky-700 border-sky-200";

const PRIVATE_KIND_OPTIONS = [
  { key: "tessa_30", label: "30-min call with Tessa" },
  { key: "coach_30", label: "30-min coach call" },
  { key: "mock_60", label: "60-min mock interview" },
];
const PRIVATE_KIND_ORDER = ["tessa_30", "coach_30", "mock_60"];

// Private-tier (Private Plus / VIP) call allowance: per-kind booked/remaining,
// each booking with a coach action to mark Attended / No-show, a +/- stepper to
// grant or remove extra allowance above the tier default, and an "Add a call"
// form to log a call that wasn't booked through Calendly. Local state updates
// optimistically so the view reflects changes without a full re-lookup.
function PrivateCallsBlock({ summary, email }) {
  const [overrides, setOverrides] = useState({}); // invitee_uri -> new status
  const [extra, setExtra] = useState({});         // kind -> extra-allowance delta added this session
  const [added, setAdded] = useState([]);         // calls logged manually this session
  const [busy, setBusy] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ kind: "coach_30", coach: "", date: "", status: "Attended" });

  const setStatus = async (uri, status) => {
    if (!email || !uri) return;
    setBusy(uri);
    try {
      await apiClient.post("/private-call/set-status", { email, invitee_uri: uri, status }, { timeout: 30000 });
      setOverrides((o) => ({ ...o, [uri]: status }));
      toast.success(`Marked ${status}`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Couldn't update");
    } finally {
      setBusy(null);
    }
  };

  const grant = async (kind, delta) => {
    if (!email) return;
    setBusy(`grant:${kind}`);
    try {
      await apiClient.post("/private-call/grant", { email, kind, delta }, { timeout: 30000 });
      setExtra((e) => ({ ...e, [kind]: (e[kind] || 0) + delta }));
      toast.success(delta > 0 ? "Extra call granted" : "Extra call removed");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Couldn't update allowance");
    } finally {
      setBusy(null);
    }
  };

  const logCall = async () => {
    if (!email) return;
    setBusy("log");
    try {
      const { data } = await apiClient.post(
        "/private-call/log",
        { email, kind: form.kind, coach: form.coach || null, date: form.date || null, status: form.status },
        { timeout: 30000 }
      );
      setAdded((a) => [...a, data.entry]);
      setShowForm(false);
      setForm({ kind: "coach_30", coach: "", date: "", status: "Attended" });
      toast.success("Call logged");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Couldn't log the call");
    } finally {
      setBusy(null);
    }
  };

  // Merge the server summary with this session's optimistic changes.
  const view = useMemo(() => {
    const out = {};
    for (const [kind, k] of Object.entries(summary.by_kind || {})) {
      out[kind] = { label: k.label, base: k.allowance - (k.extra || 0), serverExtra: k.extra || 0, calls: [...(k.calls || [])] };
    }
    const ensure = (kind) => {
      if (!out[kind]) {
        const opt = PRIVATE_KIND_OPTIONS.find((o) => o.key === kind);
        out[kind] = { label: opt?.label || kind, base: 0, serverExtra: 0, calls: [] };
      }
      return out[kind];
    };
    Object.keys(extra).forEach((kind) => ensure(kind));
    added.forEach((c) => ensure(c.kind).calls.push(c));

    const rows = Object.entries(out).map(([kind, o]) => {
      const shownExtra = Math.max(0, o.serverExtra + (extra[kind] || 0));
      const allowance = o.base + shownExtra;
      const active = o.calls.filter((c) => !/no.?show|cancel/i.test(overrides[c.invitee_uri] || c.status || ""));
      return {
        kind, label: o.label, allowance, shownExtra,
        booked: active.length, remaining: Math.max(0, allowance - active.length),
        calls: o.calls.slice().sort((a, b) => (a.date || "").localeCompare(b.date || "")),
      };
    });
    rows.sort((a, b) => ((PRIVATE_KIND_ORDER.indexOf(a.kind) + 1 || 99) - (PRIVATE_KIND_ORDER.indexOf(b.kind) + 1 || 99)));
    const totalAllow = rows.reduce((s, r) => s + r.allowance, 0);
    const totalBooked = rows.reduce((s, r) => s + r.booked, 0);
    return { rows, totalAllow, totalBooked, totalRemaining: Math.max(0, totalAllow - totalBooked) };
  }, [summary, extra, added, overrides]);

  return (
    <div className="mt-3 rounded-lg border border-[var(--ayci-border)] bg-slate-50/60 p-3" data-testid="private-calls">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
          Private Tier calls
        </span>
        <span className="text-[10px] text-[var(--ayci-ink-muted)]">
          {view.totalBooked}/{view.totalAllow} booked
          {view.totalRemaining > 0 ? ` · ${view.totalRemaining} remaining` : ""}
        </span>
      </div>
      <div className="space-y-2">
        {view.rows.map((r) => (
          <div key={r.kind}>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-semibold text-[var(--ayci-ink)]">{r.label}</span>
              <span className="text-[10px] text-[var(--ayci-ink-muted)]">
                {r.booked}/{r.allowance} booked{r.remaining > 0 ? ` · ${r.remaining} left` : ""}
                {r.shownExtra > 0 ? ` · +${r.shownExtra} extra` : ""}
              </span>
              {email && (
                <span className="inline-flex items-center gap-0.5">
                  <button
                    type="button"
                    onClick={() => grant(r.kind, 1)}
                    disabled={busy === `grant:${r.kind}`}
                    title="Grant one extra call of this type"
                    className="inline-flex items-center justify-center w-4 h-4 rounded border border-[var(--ayci-border)] text-[var(--ayci-teal)] hover:bg-white disabled:opacity-50"
                  >
                    {busy === `grant:${r.kind}` ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Plus className="w-2.5 h-2.5" />}
                  </button>
                  {r.shownExtra > 0 && (
                    <button
                      type="button"
                      onClick={() => grant(r.kind, -1)}
                      disabled={busy === `grant:${r.kind}`}
                      title="Remove an extra call"
                      className="inline-flex items-center justify-center w-4 h-4 rounded border border-[var(--ayci-border)] text-[var(--ayci-ink-muted)] hover:bg-white disabled:opacity-50"
                    >
                      <Minus className="w-2.5 h-2.5" />
                    </button>
                  )}
                </span>
              )}
            </div>
            {r.calls.map((c) => {
              const status = overrides[c.invitee_uri] || c.status;
              return (
                <div key={c.invitee_uri || `${r.kind}-${c.date}`} className="flex items-center gap-2 flex-wrap mt-1 pl-1">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 border rounded-full text-[10px] uppercase tracking-wider font-semibold ${privateStatusTone(status)}`}>
                    <Phone className="w-3 h-3" /> {status}
                    <span className="normal-case font-normal opacity-80">
                      {c.date ? `· ${fmtShort(c.date)}` : ""}{c.coach ? ` · ${c.coach}` : ""}{c.manual ? " · logged" : ""}
                    </span>
                  </span>
                  {c.invitee_uri && !/cancel/i.test(status) && (
                    <span className="inline-flex gap-1">
                      {!/attend/i.test(status) && (
                        <button
                          type="button"
                          onClick={() => setStatus(c.invitee_uri, "Attended")}
                          disabled={busy === c.invitee_uri}
                          className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--ayci-border)] text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                        >
                          {busy === c.invitee_uri ? <Loader2 className="w-3 h-3 animate-spin" /> : "Attended"}
                        </button>
                      )}
                      {!/no.?show/i.test(status) && (
                        <button
                          type="button"
                          onClick={() => setStatus(c.invitee_uri, "No-show")}
                          disabled={busy === c.invitee_uri}
                          className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--ayci-border)] text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                        >
                          No-show
                        </button>
                      )}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {email && (
        <div className="mt-3 pt-2 border-t border-[var(--ayci-border)]">
          {!showForm ? (
            <button
              type="button"
              onClick={() => setShowForm(true)}
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--ayci-teal)] hover:underline"
              data-testid="private-add-call"
            >
              <Plus className="w-3 h-3" /> Log a call (not booked via Calendly)
            </button>
          ) : (
            <div className="space-y-2" data-testid="private-add-call-form">
              <div className="flex flex-wrap gap-2">
                <select
                  value={form.kind}
                  onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value }))}
                  className="text-xs border border-[var(--ayci-border)] rounded px-2 py-1"
                >
                  {PRIVATE_KIND_OPTIONS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                </select>
                <input
                  type="text"
                  value={form.coach}
                  onChange={(e) => setForm((f) => ({ ...f, coach: e.target.value }))}
                  placeholder="Coach"
                  className="text-xs border border-[var(--ayci-border)] rounded px-2 py-1 w-24"
                />
                <input
                  type="date"
                  value={form.date}
                  onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                  className="text-xs border border-[var(--ayci-border)] rounded px-2 py-1"
                />
                <select
                  value={form.status}
                  onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
                  className="text-xs border border-[var(--ayci-border)] rounded px-2 py-1"
                >
                  {["Attended", "Booked", "No-show", "Done"].map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={logCall}
                  disabled={busy === "log"}
                  className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded bg-[var(--ayci-teal)] text-white disabled:opacity-50"
                  data-testid="private-add-call-submit"
                >
                  {busy === "log" ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                  Log call
                </button>
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="text-[11px] px-2 py-1 rounded border border-[var(--ayci-border)] text-[var(--ayci-ink-muted)]"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SummaryStat({ icon: Icon, label, value, sub, tone, testid }) {
  const TONES = {
    teal: "bg-emerald-50 border-emerald-200",
    rose: "bg-rose-50 border-rose-200",
    violet: "bg-violet-50 border-violet-200",
    amber: "bg-amber-50 border-amber-200",
  };
  return (
    <div
      className={`border rounded-lg p-3 ${TONES[tone] || TONES.teal}`}
      data-testid={testid}
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className="font-display font-bold text-2xl text-[var(--ayci-ink)] mt-1 leading-tight">
        {value}
      </div>
      {sub && (
        <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5 line-clamp-2">
          {sub}
        </div>
      )}
    </div>
  );
}
