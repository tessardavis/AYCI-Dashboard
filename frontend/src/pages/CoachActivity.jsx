import { useEffect, useState } from "react";
import { Loader2, RefreshCw, AlertTriangle, Video, MessageSquare, Users2, Clock, ExternalLink, BadgeCheck, Inbox, X, Search } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import HeroBanner, { HERO_PRESETS } from "@/components/HeroBanner";
import TodayCallsWidget from "@/components/TodayCallsWidget";
import OverAllowanceWidget from "@/components/OverAllowanceWidget";
import InterviewEveWidget from "@/components/InterviewEveWidget";

const fmtShortDate = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  } catch {
    return "—";
  }
};

export default function CoachActivity() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async (refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    try {
      const { data } = await apiClient.get("/coach-activity/summary", {
        params: refresh ? { refresh: true } : {},
        timeout: 60000,
      });
      setData(data);
      if (refresh) toast.success("Refreshed");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load coach activity");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    // Honour ?refresh=true in the URL — busts the 30-min server cache on
    // initial load, useful after fixing Circle API tokens / changing config.
    const params = new URLSearchParams(window.location.search);
    load(params.get("refresh") === "true");
  }, []);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="coach-activity-page">
      <HeroBanner
        gradient="linear-gradient(135deg, #0F766E 0%, #0EA5A4 55%, #14B8A6 100%)"
        accentDot="rgba(165,243,252,0.30)"
        eyebrowColor="#A5F3FC"
        eyebrow="Coaching engagement"
        title="Coach Activity"
        subtitle="How quickly the team is reviewing student videos & interview-support posts across Circle and the private-tier Monday board."
        testid="coach-activity-hero"
        actions={
          <button
            onClick={() => load(true)}
            disabled={refreshing || loading}
            className="text-sm bg-white/95 border border-white/20 rounded-lg px-4 py-2 hover:bg-white disabled:opacity-50 flex items-center gap-2 h-10 text-[var(--ayci-ink)]"
            data-testid="coach-activity-refresh"
          >
            {refreshing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            Refresh
          </button>
        }
      />

      {loading && !data && (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
          Loading from Circle and Monday…
        </div>
      )}

      <TodayCallsWidget />

      <OverAllowanceWidget />

      <InterviewEveWidget />

      {data && (
        <>
          <CircleSpaceCard space={data.recorded_answers} primaryNoun="video" showRateLimit onDismiss={() => load(true)} />
          <CircleSpaceCard space={data.interview_support} primaryNoun="post" showRateLimit={false} onDismiss={() => load(true)} />
          <PrivateVideosCard data={data.private_videos} />
          <DebugPostInspector />
        </>
      )}
    </div>
  );
}

// Paste a Circle post URL → see Circle's raw comments + how our coach-matcher
// reads each one. Use when a post is flagged "unanswered" but you've replied.
function DebugPostInspector() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const inspect = async () => {
    if (!url.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const { data } = await apiClient.get("/coach-activity/debug-comments-by-url", {
        params: { url: url.trim() }, timeout: 120000,
      });
      setResult(data);
    } catch (err) {
      const parts = [];
      if (err.response?.status) parts.push(`HTTP ${err.response.status}`);
      const detail = formatApiErrorDetail(err.response?.data?.detail);
      if (detail && detail !== "Something went wrong. Please try again.") parts.push(detail);
      if (err.message && !parts.some((p) => p.includes(err.message))) parts.push(err.message);
      if (err.code) parts.push(`(${err.code})`);
      setError(parts.join(" · ") || "Request failed with no detail.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-5" data-testid="debug-post-inspector">
      <div className="flex items-start gap-2 mb-3">
        <Search className="w-5 h-5 text-slate-500 mt-0.5" />
        <div className="flex-1">
          <h3 className="font-display font-bold text-lg text-[var(--ayci-ink)]">Inspect a flagged post</h3>
          <p className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">
            Paste a Circle post URL to see what comments the matcher finds and which it recognises as coach replies. Use when a post is flagged "unanswered" but you've already replied.
          </p>
        </div>
      </div>
      <div className="flex gap-2 flex-wrap">
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") inspect(); }}
          placeholder="https://ayci-academy.circle.so/c/recorded-answer-review/..."
          className="flex-1 min-w-[280px] text-sm border border-[var(--ayci-border)] rounded px-3 py-2"
          data-testid="debug-post-url"
        />
        <button
          type="button"
          onClick={inspect}
          disabled={loading || !url.trim()}
          className="text-sm font-medium px-4 py-2 rounded-md bg-[var(--ayci-teal)] text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
          data-testid="debug-post-inspect"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
          {loading ? "Inspecting…" : "Inspect"}
        </button>
      </div>
      {error && (
        <div className="mt-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded px-3 py-2">
          {error}
        </div>
      )}
      {result && (
        <div className="mt-4 space-y-3">
          {result.error && result.comment_count === undefined ? (
            <div className="text-sm px-3 py-2 rounded border bg-rose-50 border-rose-300 text-rose-900">
              <strong>Lookup failed:</strong> {result.error}
              {result.searched && (
                <ul className="mt-1 text-xs list-disc pl-5">
                  {result.searched.map((s, i) => (
                    <li key={i}>{s.space}: {s.error ? `error — ${s.error}` : `${s.post_count} posts`}</li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className={`text-sm px-3 py-2 rounded border ${
              result.would_be_marked_answered
                ? "bg-emerald-50 border-emerald-200 text-emerald-900"
                : "bg-amber-50 border-amber-300 text-amber-900"
            }`}>
              <strong>{result.would_be_marked_answered ? "✓ Counted as answered" : "✗ Counted as unanswered"}</strong>
              {" — "}{result.comment_count} comment{result.comment_count === 1 ? "" : "s"} returned by Circle
              {result.error && <div className="mt-1 text-xs">{result.error}</div>}
            </div>
          )}
          {(result.interpreted || []).length > 0 && (
            <div className="border border-[var(--ayci-border)] rounded overflow-hidden">
              <div className="bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700 border-b border-[var(--ayci-border)]">
                How the matcher reads each comment
              </div>
              <div className="divide-y divide-[var(--ayci-border)]">
                {result.interpreted.map((c, i) => (
                  <div key={c.comment_id || i} className="px-3 py-2 text-xs flex items-start gap-2 flex-wrap">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                      c.is_recognised_coach
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-slate-100 text-slate-700"
                    }`}>
                      {c.is_recognised_coach ? `✓ ${c.matched_coach}` : "✗ no match"}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="font-mono text-[11px]">
                        name=<strong>{c.extracted_name || "(none)"}</strong>
                        {" · "}email=<strong>{c.extracted_email || "(none)"}</strong>
                      </div>
                      {c.body_preview && (
                        <div className="text-[var(--ayci-ink-muted)] mt-0.5 italic">"{c.body_preview}"</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {(result.interpreted || []).length === 0 && !result.error && (
            <div className="text-sm text-[var(--ayci-ink-muted)] italic">
              Circle returned zero comments for this post. If you replied with a voice note, it might be a separate Circle artefact the comments API doesn't surface — share what you see in Circle and we'll dig.
            </div>
          )}
          <details className="text-xs">
            <summary className="cursor-pointer text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-ink)]">Raw JSON</summary>
            <pre className="mt-2 bg-slate-50 border border-[var(--ayci-border)] rounded p-2 overflow-x-auto text-[10px] leading-relaxed">{JSON.stringify(result, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}

// Helper for rate-limit dedup key — must match backend `coach_activity_dismissals.rate_limit_key`
function _normName(name) {
  return (name || "").trim().toLowerCase().replace(/\s+/g, " ");
}
function rateLimitKey(name, weekStart) {
  return `${_normName(name)}::${(weekStart || "").trim()}`;
}

async function dismissAlert({ alert_type, key, onSuccess }) {
  try {
    await apiClient.post("/coach-activity/dismiss", { alert_type, key });
    toast.success("Dismissed — won't show again");
    onSuccess?.();
  } catch (err) {
    toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Couldn't dismiss");
  }
}

function CircleSpaceCard({ space, primaryNoun, showRateLimit = true, onDismiss }) {
  if (!space || space.error) {
    return (
      <Section title="Circle space" subtitle="">
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded p-3">
          {space?.error ? `Couldn't load: ${space.error}` : "No data."}
        </div>
      </Section>
    );
  }

  const subtitle = `Day 1 was ${fmtShortDate(space.window.start)} · ${space.window.days} days · ${space.total_posts} ${primaryNoun}${space.total_posts === 1 ? "" : "s"} from ${space.total_unique_authors} student${space.total_unique_authors === 1 ? "" : "s"}`;

  return (
    <Section title={space.label} subtitle={subtitle} testid={`section-${space.space_id}`}>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <SubLabel>Posts per day</SubLabel>
          <DailyBars perDay={space.per_day} />
        </div>
        <div>
          <SubLabel>Replies per coach</SubLabel>
          <CoachList per={space.per_coach} />
        </div>
      </div>

      <div className={`grid grid-cols-1 ${showRateLimit ? "lg:grid-cols-2" : ""} gap-4 mt-4`}>
        <FlagCard
          icon={Clock}
          title={`Awaiting coach reply (${space.unanswered.length})`}
          tone="rose"
          empty={`Every ${primaryNoun} has had a coach reply within 24 hours.`}
          testid="flag-unanswered"
        >
          {space.unanswered.map((u) => (
            <div key={u.id} className="text-sm py-1.5 border-b border-rose-100 last:border-0 flex items-center justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="font-display font-semibold text-[var(--ayci-ink)] truncate">{u.author || "Unknown"}</div>
                <div className="text-xs text-[var(--ayci-ink-muted)] truncate">
                  "{u.name}" · posted {fmtShortDate(u.created_at)} · <strong className="text-rose-700">{u.hours_old}h ago</strong>
                </div>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {u.url && (
                  <a href={u.url} target="_blank" rel="noreferrer" className="text-xs text-rose-700 hover:underline flex items-center gap-1">
                    Open <ExternalLink className="w-3 h-3" />
                  </a>
                )}
                <button
                  type="button"
                  title="Mark as not needed"
                  onClick={() => dismissAlert({ alert_type: "unanswered", key: String(u.id), onSuccess: onDismiss })}
                  className="text-xs text-[var(--ayci-ink-muted)] hover:text-rose-700 hover:bg-rose-50 px-1.5 py-0.5 rounded inline-flex items-center gap-0.5 border border-transparent hover:border-rose-200"
                  data-testid={`dismiss-unanswered-${u.id}`}
                >
                  <X className="w-3 h-3" /> Dismiss
                </button>
              </div>
            </div>
          ))}
        </FlagCard>

        {showRateLimit && (
          <FlagCard
            icon={AlertTriangle}
            title={`Posting > 3 / week (${space.rate_limited.length})`}
            tone="amber"
            empty="No student has exceeded the 3-per-week limit."
            testid="flag-rate-limited"
          >
            {space.rate_limited.map((rl) => (
              <RateLimitedRow key={`${rl.name}-${rl.week_start}`} rl={rl} onDismiss={onDismiss} />
            ))}
          </FlagCard>
        )}
      </div>
    </Section>
  );
}

function RateLimitedRow({ rl, onDismiss }) {
  const [expanded, setExpanded] = useState(false);
  const posts = rl.posts || [];
  return (
    <div
      className="text-sm py-1.5 border-b border-amber-100 last:border-0"
      data-testid={`rate-limited-row-${rl.name}`}
    >
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex-1 flex items-center justify-between gap-2 text-left hover:bg-amber-50/60 -mx-1 px-1 py-0.5 rounded min-w-0"
        >
          <div className="font-display font-semibold text-[var(--ayci-ink)] flex items-center gap-1.5 min-w-0">
            <span className={`text-amber-700 transition-transform ${expanded ? "rotate-90" : ""}`}>›</span>
            <span className="truncate">{rl.name}</span>
          </div>
          <span className="text-xs text-amber-800 bg-amber-100 border border-amber-200 px-2 py-0.5 rounded-full font-semibold whitespace-nowrap">
            {rl.count} videos
          </span>
        </button>
        <button
          type="button"
          title="Mark as seen — won't ping Slack again for this week"
          onClick={() => dismissAlert({
            alert_type: "rate_limited",
            key: rateLimitKey(rl.name, rl.week_start),
            onSuccess: onDismiss,
          })}
          className="text-xs text-[var(--ayci-ink-muted)] hover:text-amber-800 hover:bg-amber-100 px-1.5 py-0.5 rounded inline-flex items-center gap-0.5 border border-transparent hover:border-amber-300 shrink-0"
          data-testid={`dismiss-rate-limited-${rl.name}`}
        >
          <X className="w-3 h-3" /> Dismiss
        </button>
      </div>
      <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5 ml-3">
        Week of {fmtShortDate(rl.week_start)}
      </div>
      {expanded && posts.length > 0 && (
        <ul className="ml-5 mt-2 mb-1 space-y-1 border-l-2 border-amber-200 pl-3">
          {posts.map((p, i) => (
            <li key={p.id || i} className="text-xs text-[var(--ayci-ink-muted)] flex items-center gap-2">
              <span className="font-mono text-[10px] text-amber-700 w-4">{i + 1}.</span>
              <span className="flex-1 truncate">{p.title}</span>
              <span className="text-[10px] tabular-nums whitespace-nowrap">
                {fmtShortDate(p.created_at)}
              </span>
              {p.url && (
                <a
                  href={p.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-amber-700 hover:underline flex items-center gap-0.5 whitespace-nowrap"
                  onClick={(e) => e.stopPropagation()}
                >
                  Open <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


function PrivateVideosCard({ data }) {
  if (!data || data.error) {
    return (
      <Section title="Private tier video submissions" subtitle="">
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded p-3">
          {data?.error ? `Couldn't load: ${data.error}` : "No data."}
        </div>
      </Section>
    );
  }
  const responsePct = data.total_submissions
    ? Math.round((data.replied / data.total_submissions) * 100)
    : 0;

  return (
    <Section
      title="Private tier video submissions"
      subtitle={`Live from Monday · "${data.board_name}"`}
      testid="section-private-videos"
    >
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Stat icon={Inbox} label="Total submitted" value={data.total_submissions} />
        <Stat icon={BadgeCheck} label="Replied" value={data.replied} hint={`${responsePct}% of total`} tone="emerald" />
        <Stat icon={Video} label="New (unactioned)" value={data.new} tone="amber" />
        <Stat icon={Users2} label="Unassigned" value={data.unassigned} tone={data.unassigned > 0 ? "rose" : "slate"} />
      </div>
      <SubLabel>Assignments per coach</SubLabel>
      <CoachList per={data.per_coach} />
    </Section>
  );
}

// ----------- Building blocks ------------------------------------------------

function Section({ title, subtitle, children, testid }) {
  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-2xl p-6 shadow-sm"
      data-testid={testid}
    >
      <div className="mb-4">
        <h2 className="font-display font-bold text-xl text-[var(--ayci-ink)]">{title}</h2>
        {subtitle && <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">{subtitle}</div>}
      </div>
      {children}
    </section>
  );
}

function SubLabel({ children }) {
  return (
    <div className="text-[10px] uppercase tracking-widest font-display font-semibold text-[var(--ayci-ink-muted)] mb-2">
      {children}
    </div>
  );
}

function DailyBars({ perDay }) {
  if (!perDay?.length) return <div className="text-sm text-[var(--ayci-ink-muted)]">No activity yet.</div>;
  const counts = perDay.map((d) => d.count);
  const max = Math.max(1, ...counts);
  const total = counts.reduce((a, b) => a + b, 0);
  const nonZeroDays = counts.filter((c) => c > 0).length;
  const avg = nonZeroDays > 0 ? (total / nonZeroDays).toFixed(1) : "0";
  const isLong = perDay.length > 14; // cohort/month views
  // UK day-of-week labels (e.g. "Mon"). The `date` field is YYYY-MM-DD;
  // parse as local midday to avoid timezone day-shifts.
  const weekday = (iso) => {
    try {
      return new Date(iso + "T12:00:00Z").toLocaleDateString("en-GB", { weekday: "short" });
    } catch {
      return "";
    }
  };
  const weekdayLong = (iso) => {
    try {
      return new Date(iso + "T12:00:00Z").toLocaleDateString("en-GB", { weekday: "long" });
    } catch {
      return "";
    }
  };
  const niceDate = (iso) => {
    try {
      return new Date(iso + "T12:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    } catch {
      return iso;
    }
  };
  const isWeekend = (iso) => {
    const d = new Date(iso + "T12:00:00Z").getUTCDay();
    return d === 0 || d === 6;
  };
  // For long ranges (e.g. 28-day cohort), drop the inline count label above
  // every bar — it's noisy at 28 columns. Keep weekly totals + tooltip-on-hover.
  const showInlineCounts = !isLong;
  // Week-boundary detection: insert a visual break at the start of each new
  // ISO week (Mon = 1). The first column never gets a leading break.
  const isWeekStart = (iso, idx) => {
    if (idx === 0) return false;
    try {
      return new Date(iso + "T12:00:00Z").getUTCDay() === 1;
    } catch {
      return false;
    }
  };
  // Pre-compute weekly totals so we can render a thin "week summary" row
  // above the bars on long views.
  const weekTotals = [];
  if (isLong) {
    let bucket = { start: perDay[0].date, end: perDay[0].date, count: 0 };
    perDay.forEach((d, idx) => {
      if (idx > 0 && isWeekStart(d.date, idx)) {
        weekTotals.push(bucket);
        bucket = { start: d.date, end: d.date, count: 0 };
      }
      bucket.end = d.date;
      bucket.count += d.count;
    });
    weekTotals.push(bucket);
  }
  return (
    <div className="bg-slate-50 border border-[var(--ayci-border)] rounded-lg p-3 sm:p-4" data-testid="daily-bars">
      {isLong && weekTotals.length > 0 && (
        <div className="flex items-stretch gap-2 mb-3" data-testid="weekly-totals">
          {weekTotals.map((w, i) => (
            <div
              key={w.start}
              className="flex-1 bg-white border border-[var(--ayci-border)] rounded-md px-2 py-1.5 flex items-center justify-between gap-2 min-w-0"
              data-testid={`week-total-${i}`}
            >
              <div className="min-w-0">
                <div className="text-[9px] uppercase tracking-wider font-display font-semibold text-[var(--ayci-ink-muted)] leading-tight">
                  Week {i + 1}
                </div>
                <div className="text-[10px] text-[var(--ayci-ink-muted)] truncate leading-tight">
                  {niceDate(w.start)} – {niceDate(w.end)}
                </div>
              </div>
              <div className="font-display font-bold text-base text-[var(--ayci-ink)] tabular-nums shrink-0">
                {w.count}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className={"flex items-end gap-1 " + (isLong ? "h-56" : "h-40")}>
        {perDay.map((d, idx) => {
          // Reserve top 18% of the bar area for the count label so tall
          // bars don't push the number out of view.
          const pct = (d.count / max) * 82;
          const weekend = isWeekend(d.date);
          const weekBreak = isWeekStart(d.date, idx);
          return (
            <div
              key={d.date}
              className={
                "flex-1 flex flex-col items-center gap-1 min-w-[16px] h-full relative group " +
                (weekBreak ? "ml-1.5 pl-1.5 border-l border-slate-200" : "")
              }
            >
              <div className="flex-1 w-full flex flex-col justify-end items-center">
                {showInlineCounts && (
                  <span
                    className={
                      "text-[10px] font-semibold tabular-nums leading-none mb-0.5 " +
                      (d.count > 0 ? "text-[var(--ayci-ink)]" : "text-slate-300")
                    }
                    data-testid={`bar-count-${d.date}`}
                  >
                    {d.count}
                  </span>
                )}
                <div
                  className={
                    "w-full rounded-t-sm transition-all duration-150 origin-bottom group-hover:opacity-90 group-hover:scale-y-[1.03] " +
                    (d.count === 0
                      ? "bg-slate-200"
                      : weekend
                      ? "bg-[var(--ayci-teal)]/60"
                      : "bg-[var(--ayci-teal)]")
                  }
                  style={{
                    height: d.count > 0 ? `${pct}%` : "2px",
                    minHeight: d.count > 0 ? "4px" : "2px",
                  }}
                  data-testid={`bar-${d.date}`}
                  data-count={d.count}
                  title={`${weekdayLong(d.date)}, ${niceDate(d.date)} · ${d.count} ${d.count === 1 ? "post" : "posts"}`}
                />
              </div>
              <div className="flex flex-col items-center w-full">
                <span className={
                  "text-[9.5px] uppercase tracking-wider truncate w-full text-center leading-tight " +
                  (weekend ? "text-[var(--ayci-ink-muted)]" : "text-[var(--ayci-ink)]")
                }>
                  {weekday(d.date)}
                </span>
                <span className="text-[8.5px] text-[var(--ayci-ink-muted)] truncate w-full text-center leading-tight">
                  {d.date.slice(8)}
                </span>
              </div>
              {/* Rich hover tooltip */}
              <div
                className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 z-20 opacity-0 group-hover:opacity-100 transition-opacity duration-150"
                data-testid={`bar-tooltip-${d.date}`}
              >
                <div className="bg-[var(--ayci-ink)] text-white text-[11px] rounded-md px-2.5 py-1.5 shadow-lg whitespace-nowrap">
                  <div className="font-semibold leading-tight">
                    {weekdayLong(d.date)}, {niceDate(d.date)}
                  </div>
                  <div className="opacity-90 tabular-nums leading-tight mt-0.5">
                    {d.count} {d.count === 1 ? "post" : "posts"}
                  </div>
                </div>
                <div className="w-2 h-2 bg-[var(--ayci-ink)] rotate-45 mx-auto -mt-1" />
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-[var(--ayci-border)] text-[10px] text-[var(--ayci-ink-muted)]">
        <span>
          Total <strong className="text-[var(--ayci-ink)] tabular-nums">{total}</strong>
          <span className="mx-2 text-slate-300">·</span>
          Avg/active-day <strong className="text-[var(--ayci-ink)] tabular-nums">{avg}</strong>
          <span className="mx-2 text-slate-300">·</span>
          Peak <strong className="text-[var(--ayci-ink)] tabular-nums">{max}</strong>
        </span>
        <span className="hidden sm:inline opacity-70">
          {isLong ? "Weekends faded · Week breaks shown · Hover for details" : "Weekends shown faded"}
        </span>
      </div>
    </div>
  );
}

function CoachList({ per }) {
  const max = Math.max(1, ...(per || []).map((p) => p.replies));
  return (
    <ul className="space-y-1.5" data-testid="coach-list">
      {(per || []).map((p) => {
        const pct = (p.replies / max) * 100;
        return (
          <li key={p.name} className="flex items-center gap-2 text-sm">
            <span className="w-32 truncate text-[var(--ayci-ink)] font-medium">{p.name}</span>
            <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-[var(--ayci-teal)] rounded-full"
                style={{ width: p.replies > 0 ? `${Math.max(8, pct)}%` : "0" }}
              />
            </div>
            <span className="w-8 text-right font-display font-semibold text-[var(--ayci-ink)] tabular-nums">
              {p.replies}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function FlagCard({ icon: Icon, title, tone, empty, children, testid }) {
  const tones = {
    rose: "bg-rose-50 border-rose-200 text-rose-900",
    amber: "bg-amber-50 border-amber-200 text-amber-900",
  };
  const isEmpty = !children || (Array.isArray(children) && children.filter(Boolean).length === 0);
  return (
    <div className={`rounded-lg border p-4 ${tones[tone] || tones.rose}`} data-testid={testid}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4" />
        <h3 className="font-display font-semibold">{title}</h3>
      </div>
      {isEmpty ? (
        <div className="text-xs opacity-70 italic flex items-center gap-1.5">
          <MessageSquare className="w-3 h-3" />
          {empty}
        </div>
      ) : (
        <div>{children}</div>
      )}
    </div>
  );
}

function Stat({ icon: Icon, label, value, hint, tone = "slate" }) {
  const tones = {
    slate: "bg-slate-50 border-slate-200 text-slate-700",
    emerald: "bg-emerald-50 border-emerald-200 text-emerald-700",
    amber: "bg-amber-50 border-amber-200 text-amber-700",
    rose: "bg-rose-50 border-rose-200 text-rose-700",
  };
  return (
    <div className={`rounded-lg border p-3 ${tones[tone]}`}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-display font-semibold opacity-80">
        <Icon className="w-3 h-3" /> {label}
      </div>
      <div className="font-display font-bold text-2xl text-[var(--ayci-ink)] mt-1 tabular-nums">{value}</div>
      {hint && <div className="text-[10px] opacity-70">{hint}</div>}
    </div>
  );
}
