import { useEffect, useState } from "react";
import { Heart, Loader2, RefreshCw } from "lucide-react";

import { apiClient } from "@/lib/api";

// Coach Activity widget — last 7 days of interview-eve check-in DMs.
// Headline counters at the top + focus rows for today's & tomorrow's
// interviews so the team can quickly see which students need a nudge.
export default function InterviewEveWidget() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const [version, setVersion] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [{ data }, verRes] = await Promise.all([
        apiClient.get("/interview-eve/summary"),
        apiClient.get("/version").catch(() => null),
      ]);
      setData(data);
      setVersion(verRes?.data || null);
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
          <SchedulerStatus run={data.last_scheduler_run} version={version} />
        </div>
        <button
          onClick={load}
          className="text-[11px] text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-teal)] flex items-center gap-1"
          data-testid="interview-eve-refresh"
        >
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
      </div>

      <div className="space-y-3 mb-4">
        <StatGroup
          title="All students"
          stats={c}
          tones={{ sent: "bg-slate-100 text-slate-800 border-slate-300",
                   replied: "bg-blue-50 text-blue-900 border-blue-200",
                   pending: "bg-amber-50 text-amber-900 border-amber-200",
                   low: "bg-rose-50 text-rose-900 border-rose-300" }}
          testidPrefix="eve-stat"
        />
        <StatGroup
          title="Private tier"
          stats={data.private_tier || {}}
          tones={{ sent: "bg-violet-50 text-violet-900 border-violet-200",
                   replied: "bg-violet-50 text-violet-900 border-violet-200",
                   pending: "bg-violet-50 text-violet-900 border-violet-200",
                   low: "bg-rose-50 text-rose-900 border-rose-300" }}
          testidPrefix="eve-stat-private"
        />
      </div>

      {(data.private_tier_rows || []).length > 0 && (
        <div className="mb-4">
          <div className="text-[11px] uppercase tracking-wider font-semibold text-violet-700 mb-1.5">
            Recent private-tier scores
          </div>
          <ul className="space-y-1.5 max-h-48 overflow-y-auto" data-testid="interview-eve-private-list">
            {data.private_tier_rows.map((r) => (
              <FocusRow key={`pt-${r.id}`} row={r} todayIso={data.today} tomorrowIso={data.tomorrow} />
            ))}
          </ul>
        </div>
      )}

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

function StatGroup({ title, stats, tones, testidPrefix }) {
  const avg = stats.avg_score;
  const reply = stats.reply_rate;
  const noReply = stats.no_reply ?? 0;
  const replied = stats.replied ?? 0;
  const closedCases = replied + noReply;
  const avgTone =
    avg == null ? "bg-slate-100 text-slate-600 border-slate-300"
    : avg <= 5 ? "bg-rose-100 text-rose-900 border-rose-300"
    : avg <= 7 ? "bg-amber-100 text-amber-900 border-amber-300"
    : "bg-emerald-100 text-emerald-900 border-emerald-300";
  const replyTone =
    reply == null ? "bg-slate-100 text-slate-600 border-slate-300"
    : reply >= 75 ? "bg-emerald-100 text-emerald-900 border-emerald-300"
    : reply >= 50 ? "bg-amber-100 text-amber-900 border-amber-300"
    : "bg-rose-100 text-rose-900 border-rose-300";
  return (
    <div data-testid={`${testidPrefix}-group`}>
      <div className="flex items-center justify-between gap-2 mb-1.5 flex-wrap">
        <div className="text-[11px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)]">{title}</div>
        <div className="flex items-center gap-1">
          <div
            className={`px-2 py-0.5 ${replyTone} border rounded-full text-[11px] font-bold uppercase tracking-wider tabular-nums`}
            data-testid={`${testidPrefix}-reply-rate`}
            title={
              closedCases === 0
                ? "No closed interview-eve cases yet — reply rate appears once interviews start happening"
                : `${replied} replied out of ${closedCases} past interviews (still-pending future interviews are excluded so the rate isn't artificially deflated)`
            }
          >
            Reply {reply == null ? "—" : `${reply}%`}
          </div>
          <div
            className={`px-2 py-0.5 ${avgTone} border rounded-full text-[11px] font-bold uppercase tracking-wider tabular-nums`}
            data-testid={`${testidPrefix}-avg`}
            title={avg == null ? "No scores received yet in this window" : `Average score across ${replied} replies in the last 7 days`}
          >
            Avg {avg == null ? "—" : `${avg}/10`}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="Sent" value={stats.sent} tone={tones.sent} testid={`${testidPrefix}-sent`} />
        <Stat label="Replied" value={replied} tone={tones.replied} testid={`${testidPrefix}-replied`} />
        <Stat
          label="Pending"
          value={stats.pending}
          tone={tones.pending}
          testid={`${testidPrefix}-pending`}
        />
        <Stat label="Low ≤5" value={stats.low_score} tone={tones.low} testid={`${testidPrefix}-low`} />
      </div>
      {noReply > 0 && (
        <div
          className="text-[11px] text-[var(--ayci-ink-muted)] italic mt-1"
          data-testid={`${testidPrefix}-no-reply-note`}
          title="Interview date has passed without a score — too late for the score to be meaningful, no action required"
        >
          {noReply} past interview-eve DM{noReply === 1 ? "" : "s"} didn't get a reply
        </div>
      )}
    </div>
  );
}

function SchedulerStatus({ run, version }) {
  const versionTail = version?.commit && version.commit !== "unknown" ? (
    <span
      className="text-[var(--ayci-ink-muted)] font-mono"
      title={`Running container SHA: ${version.commit_full || version.commit}. If this doesn't match the latest commit on main, the deploy didn't actually flush — try "Clear build cache & deploy" on Render.`}
      data-testid="interview-eve-version-sha"
    >
      · v{version.commit}
    </span>
  ) : null;
  if (!run) {
    return (
      <div
        className="mt-1.5 text-[11px] text-[var(--ayci-ink-muted)] italic flex items-center gap-1.5 flex-wrap"
        data-testid="interview-eve-scheduler-status"
        title="No audited cron runs yet — the audit started after this paper trail was added. The next run will be logged."
      >
        <span>Cron status: no audited runs yet (next: Mon-Fri 19:00 UK)</span>
        {versionTail}
      </div>
    );
  }
  const startedAt = run.started_at ? new Date(run.started_at) : null;
  const when = startedAt
    ? startedAt.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : "(unknown time)";
  const ok = run.status === "ok";
  const result = run.result || {};
  const summary = ok
    ? `sent=${result.sent ?? 0} · skipped=${result.skipped ?? 0} · errors=${result.errors ?? 0}`
    : `error: ${(run.error || "unknown").slice(0, 120)}`;
  const dotTone = ok ? "bg-emerald-500" : "bg-rose-500";
  const labelTone = ok ? "text-emerald-700" : "text-rose-700";
  return (
    <div
      className="mt-1.5 flex items-center gap-1.5 text-[11px] flex-wrap"
      data-testid="interview-eve-scheduler-status"
    >
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${dotTone}`} />
      <span className={`font-semibold ${labelTone}`}>{ok ? "Last cron ok" : "Last cron FAILED"}</span>
      <span className="text-[var(--ayci-ink-muted)]">· {when} · {summary}</span>
      {versionTail}
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
