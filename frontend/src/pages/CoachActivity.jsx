import { useEffect, useState } from "react";
import { Loader2, RefreshCw, AlertTriangle, Video, MessageSquare, Users2, Clock, ExternalLink, BadgeCheck, Inbox, X } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import HeroBanner, { HERO_PRESETS } from "@/components/HeroBanner";
import TodayCallsWidget from "@/components/TodayCallsWidget";
import OverAllowanceWidget from "@/components/OverAllowanceWidget";

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

  useEffect(() => { load(false); }, []);

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

      {data && (
        <>
          <CircleSpaceCard space={data.recorded_answers} primaryNoun="video" showRateLimit onDismiss={() => load(true)} />
          <CircleSpaceCard space={data.interview_support} primaryNoun="post" showRateLimit={false} onDismiss={() => load(true)} />
          <PrivateVideosCard data={data.private_videos} />
        </>
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
          empty={`Every ${primaryNoun} has had a coach reply within 48 hours.`}
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
  const max = Math.max(1, ...perDay.map((d) => d.count));
  return (
    <div className="flex items-end gap-0.5 h-32 bg-slate-50 border border-[var(--ayci-border)] rounded-lg p-3">
      {perDay.map((d) => {
        const pct = (d.count / max) * 100;
        return (
          <div key={d.date} className="flex-1 flex flex-col items-center gap-1 min-w-0">
            <div
              className="w-full bg-[var(--ayci-teal)] rounded-t-sm hover:opacity-80 transition-opacity"
              style={{ height: `${pct}%`, minHeight: d.count > 0 ? "4px" : "0" }}
              title={`${d.date}: ${d.count}`}
            />
            <span className="text-[8px] text-[var(--ayci-ink-muted)] truncate w-full text-center">
              {d.date.slice(8)}
            </span>
          </div>
        );
      })}
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
