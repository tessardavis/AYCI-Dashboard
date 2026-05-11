import { useEffect, useState } from "react";
import { AlertOctagon, Check, ChevronDown, ChevronUp, ExternalLink, History, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";

const fmtAckTime = (iso) => {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch {
    return "—";
  }
};

/**
 * Shows students whose Calendly all-time private-call count exceeds
 * their Monday total allowance (calls + mocks + bonus columns).
 * Auto-refreshes every 5 min via the backend's `over_allowance_check`
 * scheduled job; this widget just polls the cached snapshot.
 *
 * Each row has an Acknowledge button — clicking it records the current
 * `over_by` and hides the row until the student goes further over.
 */
export default function OverAllowanceWidget() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [acking, setAcking] = useState({}); // email -> bool

  const load = async (refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    try {
      const { data } = await apiClient.get("/coach-activity/over-allowance", {
        params: refresh ? { refresh: true } : {},
        timeout: 120000,
      });
      setData(data);
      if (refresh) toast.success("Re-checked Calendly");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load over-allowance check");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const ack = async (s) => {
    setAcking((m) => ({ ...m, [s.email]: true }));
    try {
      await apiClient.post("/coach-activity/over-allowance/ack", {
        email: s.email,
        over_by: s.over_by,
      });
      toast.success(`Acknowledged ${s.name}`, {
        description: `Hidden unless they go over by more than ${s.over_by}.`,
      });
      // Optimistic: drop the row locally; backend already busted the cache
      setData((prev) => prev && {
        ...prev,
        students: (prev.students || []).filter((r) => r.email !== s.email),
      });
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Acknowledge failed");
    } finally {
      setAcking((m) => ({ ...m, [s.email]: false }));
    }
  };

  useEffect(() => { load(false); }, []);

  const students = data?.students || [];
  const empty = !loading && students.length === 0;

  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5"
      data-testid="over-allowance-widget"
    >
      <div className="flex items-start justify-between mb-3 gap-4">
        <div className="flex items-start gap-3">
          <div className="bg-rose-50 border border-rose-200 rounded-md p-2">
            <AlertOctagon className="w-4 h-4 text-rose-700" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-[var(--ayci-ink)]">
              Over-allowance bookings
              {students.length > 0 && (
                <span className="ml-2 text-[10px] uppercase tracking-wider font-bold bg-rose-100 text-rose-900 border border-rose-200 px-1.5 py-0.5 rounded-full align-middle">
                  {students.length}
                </span>
              )}
            </h3>
            <p className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">
              Calendly bookings exceed Monday slot allowance. Oksana is DM'd in Slack the moment a student crosses over. Acknowledge to hide a row until the breach grows further.
            </p>
          </div>
        </div>
        <button
          onClick={() => load(true)}
          disabled={loading || refreshing}
          className="text-xs bg-white border border-[var(--ayci-border)] rounded-md px-2.5 py-1.5 hover:bg-slate-50 disabled:opacity-50 flex items-center gap-1.5 text-[var(--ayci-ink-muted)] h-8 whitespace-nowrap"
          data-testid="over-allowance-refresh"
        >
          {refreshing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Re-check
        </button>
      </div>

      {loading && !data && (
        <div className="text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      )}

      {empty && (
        <div className="text-sm text-emerald-700 bg-emerald-50/60 border border-emerald-200 rounded-md px-3 py-2" data-testid="over-allowance-empty">
          Everyone is within their booked-call allowance. Nice.
        </div>
      )}

      {students.length > 0 && (
        <div className="divide-y divide-[var(--ayci-border)] border border-[var(--ayci-border)] rounded-md overflow-hidden" data-testid="over-allowance-list">
          {students.map((s) => (
            <div
              key={s.email}
              className="p-3 flex items-center justify-between gap-3 bg-rose-50/30 hover:bg-rose-50/60 transition-colors"
              data-testid={`over-allowance-row-${s.email}`}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-[var(--ayci-ink)]">{s.name}</span>
                  <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-bold border ${
                    s.tier === "VIP"
                      ? "bg-purple-50 text-purple-700 border-purple-200"
                      : "bg-sky-50 text-sky-700 border-sky-200"
                  }`}>
                    {s.tier}
                  </span>
                  <span className="text-[11px] text-[var(--ayci-ink-muted)] truncate">{s.email}</span>
                </div>
                <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">
                  Booked <span className="font-semibold text-rose-700">{s.calendly_calls_used}</span> Calendly calls
                  &nbsp;·&nbsp; Allowance <span className="font-semibold">{s.monday_total_allowance}</span>
                  &nbsp;<span className="opacity-60">({s.monday_calls_total} calls + {s.monday_mocks_total} mock + {s.monday_bonus_total} bonus)</span>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-rose-100 text-rose-900 border border-rose-200 text-[11px] font-bold">
                  +{s.over_by} over
                </span>
                <button
                  onClick={() => ack(s)}
                  disabled={!!acking[s.email]}
                  className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md bg-white border border-[var(--ayci-border)] text-[var(--ayci-ink)] hover:bg-emerald-50 hover:border-emerald-300 hover:text-emerald-800 disabled:opacity-50 transition-colors"
                  title={`Acknowledge — hide until they go over by more than ${s.over_by}`}
                  data-testid={`over-allowance-ack-${s.email}`}
                >
                  {acking[s.email] ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                  Acknowledge
                </button>
                {s.monday_url && (
                  <a
                    href={s.monday_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-teal)] transition-colors"
                    title="Open in Monday"
                    data-testid={`over-allowance-monday-link-${s.email}`}
                  >
                    <ExternalLink className="w-4 h-4" />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <AcknowledgementLog />
    </section>
  );
}

function AcknowledgementLog() {
  const [open, setOpen] = useState(false);
  const [acks, setAcks] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/coach-activity/over-allowance/acks");
      setAcks(data.acks || []);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load log");
    } finally {
      setLoading(false);
    }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && acks === null) load();
  };

  const count = acks?.length;

  return (
    <div className="mt-3 border-t border-[var(--ayci-border)] pt-3" data-testid="over-allowance-ack-log">
      <button
        onClick={toggle}
        className="flex items-center gap-1.5 text-[11px] text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-ink)] transition-colors"
        data-testid="over-allowance-ack-log-toggle"
      >
        <History className="w-3 h-3" />
        Acknowledgement log
        {count !== undefined && (
          <span className="opacity-70">({count})</span>
        )}
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
      {open && (
        <div className="mt-2" data-testid="over-allowance-ack-log-body">
          {loading && (
            <div className="text-xs text-[var(--ayci-ink-muted)] flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" /> Loading…
            </div>
          )}
          {!loading && acks && acks.length === 0 && (
            <div className="text-xs text-[var(--ayci-ink-muted)]">No acknowledgements yet.</div>
          )}
          {!loading && acks && acks.length > 0 && (
            <ul className="text-[11px] space-y-1 text-[var(--ayci-ink-muted)]">
              {acks.map((a) => (
                <li
                  key={a.email + a.acked_at}
                  className="flex items-center justify-between gap-2 px-2 py-1 bg-slate-50/60 rounded border border-[var(--ayci-border)]"
                  data-testid={`over-allowance-ack-log-row-${a.email}`}
                >
                  <span className="truncate">
                    <span className="font-semibold text-[var(--ayci-ink)]">{a.email}</span>
                    <span className="opacity-70"> — acked at +{a.over_by} over by {a.acked_by_name || "?"}</span>
                  </span>
                  <span className="text-[10px] flex-shrink-0 opacity-70">{fmtAckTime(a.acked_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
