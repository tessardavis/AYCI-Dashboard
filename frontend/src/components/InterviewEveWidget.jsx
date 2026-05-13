import { useEffect, useState } from "react";
import { Heart, Loader2, RefreshCw } from "lucide-react";

import { apiClient } from "@/lib/api";

// Coach Activity widget — last 7 days of interview-eve check-in DMs.
// Headline counters at the top + focus rows for today's & tomorrow's
// interviews so the team can quickly see which students need a nudge.
export default function InterviewEveWidget() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/interview-eve/summary");
      setData(data);
    } catch (err) {
      setData(null);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  if (loading && !data) {
    return (
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-6 text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
        <Loader2 className="w-4 h-4 animate-spin text-[var(--ayci-teal)]" />
        Loading interview-eve check-ins…
      </div>
    );
  }
  if (!data) return null;

  const c = data.counts || {};
  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="interview-eve-widget"
    >
      <div className="flex items-start justify-between gap-2 flex-wrap mb-3">
        <div className="min-w-0">
          <h3 className="font-display font-semibold text-base text-[var(--ayci-ink)] flex items-center gap-2">
            <Heart className="w-4 h-4 text-rose-500" />
            Interview-eve check-ins
          </h3>
          <p className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">
            Last 7 days · DMs sent from Coralie's account the evening before each interview asking for a 1-10 support score.
          </p>
        </div>
        <button
          onClick={load}
          className="text-[11px] text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-teal)] flex items-center gap-1"
          data-testid="interview-eve-refresh"
        >
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
        <Stat label="Sent" value={c.sent} tone="bg-slate-100 text-slate-800 border-slate-300" testid="eve-stat-sent" />
        <Stat label="Replied" value={c.replied} tone="bg-blue-50 text-blue-900 border-blue-200" testid="eve-stat-replied" />
        <Stat label="Pending" value={c.pending} tone="bg-amber-50 text-amber-900 border-amber-200" testid="eve-stat-pending" />
        <Stat label="Low score ≤5" value={c.low_score} tone="bg-rose-50 text-rose-900 border-rose-300" testid="eve-stat-low" />
      </div>

      {(data.focus || []).length > 0 ? (
        <div>
          <div className="text-[11px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)] mb-1.5">
            Today's & tomorrow's interviews
          </div>
          <ul className="space-y-1.5 max-h-80 overflow-y-auto" data-testid="interview-eve-focus-list">
            {data.focus.map((r) => (
              <FocusRow key={r.id} row={r} todayIso={data.today} tomorrowIso={data.tomorrow} />
            ))}
          </ul>
        </div>
      ) : (
        <div className="text-xs text-[var(--ayci-ink-muted)] italic">
          No interviews scheduled in the next 2 days. New DMs will fire at 19:00 UK the night before each interview.
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone, testid }) {
  return (
    <div className={`border rounded px-2 py-2 text-center ${tone}`} data-testid={testid}>
      <div className="text-xl font-bold leading-none tabular-nums">{value ?? 0}</div>
      <div className="text-[10px] uppercase tracking-wider mt-1">{label}</div>
    </div>
  );
}

function FocusRow({ row, todayIso, tomorrowIso }) {
  const when = row.interview_date === todayIso ? "today"
              : row.interview_date === tomorrowIso ? "tomorrow"
              : row.interview_date;
  const score = row.score;
  const scoreTone = score == null
    ? "bg-slate-100 text-slate-600 border-slate-200"
    : score <= 5 ? "bg-rose-100 text-rose-900 border-rose-300"
    : score <= 7 ? "bg-amber-100 text-amber-900 border-amber-300"
    : "bg-emerald-100 text-emerald-900 border-emerald-300";
  return (
    <li
      className="flex items-center justify-between gap-2 bg-slate-50/60 border border-slate-200 rounded px-3 py-2 text-sm"
      data-testid={`interview-eve-row-${row.id}`}
    >
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-[var(--ayci-ink)] truncate">{row.student_name}</div>
        <div className="text-[11px] text-[var(--ayci-ink-muted)]">
          Interview {when} · {row.tier} {row.is_private_tier ? " · Private tier" : ""}
        </div>
      </div>
      <span
        className={`px-2 py-1 ${scoreTone} border rounded-full text-[11px] font-bold uppercase tracking-wider tabular-nums`}
        title={score == null ? "Awaiting reply" : `Replied ${new Date(row.score_received_at).toLocaleString("en-GB")}`}
      >
        {score == null ? "pending" : `${score}/10`}
      </span>
    </li>
  );
}
