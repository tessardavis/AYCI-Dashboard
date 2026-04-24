import { useEffect, useState } from "react";
import { Loader2, Users, CircleDot, Trophy, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";

const DEFAULT_COHORT = "April 26";

export default function CohortDashboard() {
  const [cohort, setCohort] = useState(DEFAULT_COHORT);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

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
    load(DEFAULT_COHORT);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="p-8 space-y-6" data-testid="cohort-dashboard-page">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] font-display font-semibold tracking-[0.25em] uppercase text-[var(--ayci-teal)]">
            Current cohort
          </div>
          <h1 className="text-4xl font-display font-bold text-[var(--ayci-ink)] mt-1">
            {cohort} Cohort
          </h1>
          <p className="text-[var(--ayci-ink-muted)] text-sm mt-1 max-w-2xl">
            Live from Monday.com Academy Members board, cross-referenced with Circle membership.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={cohort}
            onChange={(e) => {
              setCohort(e.target.value);
              load(e.target.value);
            }}
            className="bg-white border border-[var(--ayci-border)] rounded-lg px-3 py-2 text-sm font-medium text-[var(--ayci-ink)] focus:outline-none focus:border-[var(--ayci-teal)]"
            data-testid="cohort-selector"
          >
            {[
              "April 26",
              "February 26",
              "November 25",
              "September 25",
              "July 25",
              "April 25",
            ].map((c) => (
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
          >
            {loading ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4 mr-2" />
            )}
            Refresh
          </Button>
        </div>
      </div>

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
              label="Total students"
              value={data.totals.students}
              testid="stat-total"
            />
            <StatCard
              icon={Users}
              label="New"
              value={data.totals.new}
              sub={`${pct(data.totals.new, data.totals.students)} of cohort`}
              tone="emerald"
              testid="stat-new"
            />
            <StatCard
              icon={Users}
              label="Legacy"
              value={data.totals.legacy}
              sub={`${pct(data.totals.legacy, data.totals.students)} of cohort`}
              tone="violet"
              testid="stat-legacy"
            />
            <StatCard
              icon={CircleDot}
              label="On Circle"
              value={`${data.circle.students_on_circle} / ${data.circle.students_total}`}
              sub={`${data.circle.coverage_percent}% joined (tag "${data.circle.tag}")`}
              tone="sky"
              testid="stat-circle"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Tier split */}
            <section
              className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
              data-testid="tier-split"
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
                  Tier split
                </h2>
                <span className="text-xs text-[var(--ayci-ink-muted)]">
                  {data.tiers.length} tiers
                </span>
              </div>
              <div className="space-y-3">
                {data.tiers.map((t) => (
                  <Bar
                    key={t.tier}
                    label={t.tier}
                    value={t.count}
                    total={data.totals.students}
                    percent={t.percent}
                    color={tierColor(t.tier)}
                  />
                ))}
              </div>
            </section>

            {/* Milestone progress */}
            <section
              className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
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

            {/* Speciality */}
            <section
              className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm lg:col-span-2"
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
          </div>

          {/* Circle detail */}
          <section
            className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
            data-testid="circle-detail"
          >
            <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)] mb-1">
              Circle community join rate
            </h2>
            <p className="text-xs text-[var(--ayci-ink-muted)] mb-4">
              Of the {data.circle.students_total} {cohort} students,{" "}
              <span className="text-[var(--ayci-ink)] font-semibold">
                {data.circle.students_on_circle}
              </span>{" "}
              have logged into Circle and been tagged "{data.circle.tag}". Circle itself has{" "}
              <span className="text-[var(--ayci-ink)] font-semibold">
                {data.circle.tag_total_in_circle}
              </span>{" "}
              members total with this tag (includes legacy/non-cohort folks).
            </p>
            <div className="h-5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-[var(--ayci-teal)] to-sky-400 flex items-center justify-end pr-2 text-[10px] font-semibold text-white transition-all"
                style={{ width: `${data.circle.coverage_percent}%` }}
              >
                {data.circle.coverage_percent > 15 ? `${data.circle.coverage_percent}%` : ""}
              </div>
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
  if (t.includes("platinum")) return "#0ea5e9";
  if (t.includes("gold")) return "#f59e0b";
  if (t.includes("silver")) return "#64748b";
  if (t.includes("boost")) return "#10b981";
  if (t === "academy") return "#0EA5E9";
  return "#6366f1";
}
