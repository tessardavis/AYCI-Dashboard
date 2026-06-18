import { useEffect, useState } from "react";
import { Loader2, Users, CircleDot, Trophy, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import HeroBanner, { HERO_PRESETS } from "@/components/HeroBanner";

const DEFAULT_COHORT = "June 26";

export default function CohortDashboard() {
  const [cohort, setCohort] = useState(DEFAULT_COHORT);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [labels, setLabels] = useState([DEFAULT_COHORT]);

  const load = async (label = cohort) => {
    setLoading(true);
    try {
      const { data } = await apiClient.get(`/cohorts/summary`, {
        params: { cohort: label },
        timeout: 45000,
      });
      setData(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load cohort");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Fetch the live cohort label list from Monday, then load the default cohort.
    (async () => {
      try {
        const { data } = await apiClient.get(`/cohorts/labels`, { timeout: 15000 });
        if (Array.isArray(data) && data.length) {
          setLabels(data.map((l) => l.name));
        }
      } catch (e) {
        console.warn("[cohort] failed to load labels, falling back to default", e);
      }
      load(DEFAULT_COHORT);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="cohort-dashboard-page">
      <HeroBanner
        {...HERO_PRESETS.cohort}
        eyebrow="Current cohort"
        title={`${cohort} Cohort`}
        subtitle="Live from Monday.com Academy Members board, cross-referenced with Circle membership."
        testid="cohort-hero"
        actions={
          <>
            <select
              value={cohort}
              onChange={(e) => {
                setCohort(e.target.value);
                load(e.target.value);
              }}
              className="bg-white/95 border border-white/20 rounded-lg px-3 py-2 text-sm font-medium text-[var(--ayci-ink)] focus:outline-none focus:border-[var(--ayci-teal)] h-10"
              data-testid="cohort-selector"
            >
              {labels.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              onClick={() => load()}
              disabled={loading}
              data-testid="cohort-refresh"
              className="bg-white/95 border-white/20 text-[var(--ayci-ink)] hover:bg-white"
            >
              {loading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4 mr-2" />
              )}
              Refresh
            </Button>
          </>
        }
      />

      {loading && !data && (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
          Loading cohort from Monday…
        </div>
      )}

      {data && (
        <>
          {/* Top stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard
              icon={Users}
              label="Cohort total"
              value={data.totals.students}
              sub={
                data.totals.new_plus_legacy
                  ? `New + legacy in this launch`
                  : "from Academy Members board"
              }
              testid="stat-total"
            />
            <StatCard
              icon={Users}
              label="New (Kit)"
              value={data.totals.new}
              sub={`${pct(data.totals.new, data.totals.new_plus_legacy)} of Kit`}
              tone="emerald"
              testid="stat-new"
            />
            <StatCard
              icon={Users}
              label="Legacy (Kit)"
              value={data.totals.legacy}
              sub={`${pct(data.totals.legacy, data.totals.new_plus_legacy)} of Kit`}
              tone="violet"
              testid="stat-legacy"
            />
            <StatCard
              icon={CircleDot}
              label="On Circle"
              value={`${data.circle.students_on_circle} / ${data.circle.students_total}`}
              sub={`${data.circle.coverage_percent}% of new signups (tag "${data.circle.tag}")`}
              tone="sky"
              testid="stat-circle"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Tier split — compact */}
            <section
              className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm"
              data-testid="tier-split"
            >
              <div className="flex items-center justify-between mb-3">
                <h2 className="font-display font-bold text-base text-[var(--ayci-ink)]">
                  Tier split
                </h2>
                <span className="text-xs text-[var(--ayci-ink-muted)]">
                  {data.tiers.length} tiers
                </span>
              </div>
              {/* Stacked horizontal bar */}
              <div className="flex h-2.5 rounded-full overflow-hidden bg-slate-100" data-testid="tier-stacked-bar">
                {data.tiers.map((t) => (
                  <div
                    key={t.tier}
                    title={`${t.tier}: ${t.count} (${t.percent}%)`}
                    style={{ width: `${t.percent}%`, backgroundColor: tierColor(t.tier) }}
                  />
                ))}
              </div>
              {/* Compact chip legend */}
              <ul className="mt-3 space-y-1.5">
                {data.tiers.map((t) => (
                  <li
                    key={t.tier}
                    className="flex items-center justify-between text-xs"
                    data-testid={`tier-row-${t.tier}`}
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: tierColor(t.tier) }}
                      />
                      <span className="truncate text-[var(--ayci-ink)]">{t.tier}</span>
                    </span>
                    <span className="text-[var(--ayci-ink-muted)] tabular-nums shrink-0 ml-2">
                      {t.count} · {t.percent}%
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            {/* Milestone progress */}
            <section
              className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm lg:col-span-2"
              data-testid="milestone-progress"
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
                  Milestones completed
                </h2>
                <Trophy className="w-4 h-4 text-amber-500" />
              </div>
              <div className="space-y-3">
                {data.milestones.map((m) => (
                  <Bar
                    key={m.label}
                    label={m.label}
                    value={m.completed}
                    total={m.total}
                    percent={m.percent}
                    color="#f59e0b"
                  />
                ))}
              </div>
              {data.milestones.every((m) => m.completed === 0) && (
                <div className="mt-4 text-xs text-[var(--ayci-ink-muted)] bg-slate-50 border border-dashed border-[var(--ayci-border)] rounded p-3">
                  No milestones ticked yet — check back after cohort kick-off.
                </div>
              )}
            </section>
          </div>

          {/* Circle detail */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <section
              className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
              data-testid="circle-detail"
            >
              <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)] mb-1">
                Circle community join rate
              </h2>
              <p className="text-xs text-[var(--ayci-ink-muted)] mb-4">
                Of the {data.circle.students_total} new {cohort} signups,{" "}
                <span className="text-[var(--ayci-ink)] font-semibold">
                  {data.circle.students_on_circle}
                </span>{" "}
                have the tag "{data.circle.tag}" on Circle. The tag has{" "}
                <span className="text-[var(--ayci-ink)] font-semibold">
                  {data.circle.tag_total_in_circle}
                </span>{" "}
                members total (legacy + new combined).
              </p>
              <div className="h-5 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full flex items-center justify-end pr-2 text-[10px] font-semibold text-white"
                  style={{
                    width: `${Math.max(2, data.circle.coverage_percent)}%`,
                    background: "linear-gradient(90deg, #4457B6 0%, #01D9DC 100%)",
                    transition: "width 600ms ease-out",
                  }}
                  data-testid="circle-coverage-bar"
                >
                  {data.circle.coverage_percent > 15 ? `${data.circle.coverage_percent}%` : ""}
                </div>
              </div>
              {data.circle.pending && data.circle.pending.count > 0 && (
                <div
                  className="mt-4 pt-4 border-t border-[var(--ayci-border)]"
                  data-testid="circle-pending-summary"
                >
                  <div className="flex items-baseline justify-between mb-2 flex-wrap gap-2">
                    <div className="text-xs text-[var(--ayci-ink-muted)]">
                      Still to join Circle
                    </div>
                    <div className="font-display font-bold text-2xl text-rose-600 tabular-nums">
                      {data.circle.pending.count}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {data.circle.pending.by_tier.map((t) => (
                      <span
                        key={t.tier}
                        className="inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full border"
                        style={{
                          color: tierColor(t.tier),
                          borderColor: tierColor(t.tier) + "55",
                          background: tierColor(t.tier) + "11",
                        }}
                        data-testid={`pending-tier-${t.tier}`}
                      >
                        <span
                          className="w-1.5 h-1.5 rounded-full"
                          style={{ background: tierColor(t.tier) }}
                        />
                        {t.tier}
                        <span className="font-semibold">{t.count}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </section>

            {/* Intros space */}
            {data.circle.intros && (
              <section
                className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
                data-testid="intros-detail"
              >
                <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)] mb-1">
                  Introduced themselves on Circle
                </h2>
                <p className="text-xs text-[var(--ayci-ink-muted)] mb-4">
                  <span className="text-[var(--ayci-ink)] font-semibold">
                    {data.circle.intros.students_posted}
                  </span>{" "}
                  of {data.circle.intros.students_total} students have posted in the
                  "Introduce Yourself" space.{" "}
                  <span className="opacity-80">
                    ({data.circle.intros.posts_total} posts in the space total)
                  </span>
                </p>
                <div className="h-5 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-full flex items-center justify-end pr-2 text-[10px] font-semibold text-white"
                    style={{
                      width: `${Math.max(2, data.circle.intros.coverage_percent)}%`,
                      background: "linear-gradient(90deg, #8b5cf6 0%, #ec4899 100%)",
                      transition: "width 600ms ease-out",
                    }}
                    data-testid="intros-coverage-bar"
                  >
                    {data.circle.intros.coverage_percent > 15
                      ? `${data.circle.intros.coverage_percent}%`
                      : ""}
                  </div>
                </div>
                {data.circle.intros.error && (
                  <div className="text-xs text-amber-700 mt-2">
                    {data.circle.intros.error}
                  </div>
                )}
              </section>
            )}
          </div>

          {/* Pending-Circle chase list */}
          {data.circle.pending && data.circle.pending.list.length > 0 && (
            <section
              className="bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm overflow-hidden"
              data-testid="circle-pending-list"
            >
              <div className="px-5 py-4 border-b border-[var(--ayci-border)] bg-rose-50/30">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
                    Still to join Circle ({data.circle.pending.count})
                  </h2>
                  <p className="text-xs text-[var(--ayci-ink-muted)]">
                    Cohort students without the "{data.circle.tag}" tag on Circle.
                    Sorted by tier (highest first).
                  </p>
                </div>
              </div>
              <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-white z-10">
                    <tr className="text-left text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
                      <th className="px-4 py-2 font-semibold">Name</th>
                      <th className="px-3 py-2 font-semibold">Tier</th>
                      <th className="px-3 py-2 font-semibold whitespace-nowrap">Signed up</th>
                      <th className="px-3 py-2 font-semibold">Email</th>
                      <th className="px-3 py-2 font-semibold text-center">Has Circle account?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.circle.pending.list.map((s) => (
                      <tr
                        key={s.email}
                        className="border-t border-[var(--ayci-border)] hover:bg-slate-50/50"
                        data-testid={`pending-row-${s.email}`}
                      >
                        <td className="px-4 py-2">
                          {s.monday_url ? (
                            <a
                              href={s.monday_url}
                              target="_blank"
                              rel="noreferrer"
                              className="font-semibold text-[var(--ayci-ink)] hover:text-[var(--ayci-teal)]"
                            >
                              {s.name || "(name unknown)"}
                            </a>
                          ) : (
                            <span className="font-semibold text-[var(--ayci-ink)]">
                              {s.name || "(name unknown)"}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className="inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full border"
                            style={{
                              color: tierColor(s.tier),
                              borderColor: tierColor(s.tier) + "55",
                              background: tierColor(s.tier) + "11",
                            }}
                          >
                            <span
                              className="w-1.5 h-1.5 rounded-full"
                              style={{ background: tierColor(s.tier) }}
                            />
                            {s.tier}
                          </span>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {s.signup_date ? (
                            <SignupDateBadge iso={s.signup_date} />
                          ) : (
                            <span className="text-xs text-[var(--ayci-ink-muted)]">—</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-[var(--ayci-ink-muted)] font-mono text-xs">
                          {s.email}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {s.has_circle_account ? (
                            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-semibold">
                              Yes — needs tag
                            </span>
                          ) : (
                            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 font-semibold">
                              No account
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Speciality (bottom) */}
          <section
            className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
            data-testid="speciality-breakdown"
          >
            <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)] mb-4">
              Top specialities
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
              {data.specialities.map((s) => (
                <div
                  key={s.speciality}
                  className="bg-slate-50 border border-[var(--ayci-border)] rounded p-3"
                >
                  <div className="text-xs text-[var(--ayci-ink-muted)]">{s.speciality}</div>
                  <div className="font-display font-bold text-xl text-[var(--ayci-ink)] mt-0.5">
                    {s.count}
                  </div>
                </div>
              ))}
              {data.specialities.length === 0 && (
                <div className="col-span-full text-sm text-[var(--ayci-ink-muted)] italic">
                  No speciality data
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, sub, tone = "slate", testid }) {
  const toneMap = {
    slate: "bg-slate-50 text-slate-700",
    emerald: "bg-emerald-50 text-emerald-700",
    violet: "bg-violet-50 text-violet-700",
    sky: "bg-sky-50 text-sky-700",
  };
  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm"
      data-testid={testid}
    >
      <div
        className={`inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${toneMap[tone]}`}
      >
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className="mt-2 font-display font-bold text-3xl text-[var(--ayci-ink)]">
        {value}
      </div>
      {sub && <div className="text-xs text-[var(--ayci-ink-muted)] mt-1">{sub}</div>}
    </div>
  );
}

function Bar({ label, value, total, percent, color }) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm mb-1">
        <span className="font-medium text-[var(--ayci-ink)]">{label}</span>
        <span className="text-[var(--ayci-ink-muted)] text-xs">
          {value} / {total} · {percent}%
        </span>
      </div>
      <div className="h-2.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${percent}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

function pct(part, total) {
  if (!total) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

function tierColor(tier) {
  const t = tier.toLowerCase();
  if (t.includes("academy private") || t === "academy 1:1") return "#7c3aed";
  if (t.includes("vip")) return "#dc2626";
  if (t.includes("platinum")) return "#4457B6";
  if (t.includes("gold")) return "#FEB870";
  if (t.includes("silver")) return "#64748b";
  if (t.includes("boost")) return "#10b981";
  if (t === "academy") return "#4457B6";
  return "#AF41AC";
}

function SignupDateBadge({ iso }) {
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return <span className="text-xs text-[var(--ayci-ink-muted)]">—</span>;
  const days = Math.floor((Date.now() - dt.getTime()) / 86400000);
  const dateStr = dt.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  // Tone the badge based on how long they've been waiting:
  //  ≤7 days → green (just signed up, give it time)
  //  8-21 days → amber (chase soon)
  //  >21 days → rose (overdue)
  let tone = "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (days > 21) tone = "bg-rose-50 text-rose-700 border-rose-200";
  else if (days > 7) tone = "bg-amber-50 text-amber-700 border-amber-200";
  return (
    <span
      className={`inline-flex flex-col items-start gap-0 px-2 py-0.5 border rounded ${tone}`}
      title={dt.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}
    >
      <span className="text-xs font-semibold tabular-nums leading-tight">{dateStr}</span>
      <span className="text-[10px] uppercase tracking-wider opacity-80">
        {days === 0 ? "today" : days === 1 ? "1d ago" : `${days}d ago`}
      </span>
    </span>
  );
}
