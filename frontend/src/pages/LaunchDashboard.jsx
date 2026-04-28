import { useEffect, useMemo, useState } from "react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { Loader2, Calendar, TrendingUp, ShoppingBag, Users, ExternalLink, AlertTriangle, RefreshCw, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import HeroBanner, { HERO_PRESETS } from "@/components/HeroBanner";
import { PaceTrackerCard } from "@/components/PaceTracker";

const PHASE_LABELS = {
  in_between_start: "In-between",
  early_access: "Early access",
  flash_sale: "Flash sale",
  webinar: "Webinar",
  open_cart: "Open cart",
  close_cart: "Close cart",
  in_between_end: "In-between",
};

const PHASE_COLORS = {
  in_between_start: "#94a3b8",
  early_access: "#4457B6",
  flash_sale: "#dc2626",
  webinar: "#7c3aed",
  open_cart: "#10b981",
  close_cart: "#FEB870",
  in_between_end: "#94a3b8",
};

const SERIES_COLORS = ["#4457B6", "#94a3b8", "#cbd5e1"];

const fmtGbp = (v) =>
  `£${Number(v || 0).toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
const fmtDate = (iso) =>
  iso ? new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }) : "—";

export default function LaunchDashboard() {
  const [launches, setLaunches] = useState([]);
  const [launchId, setLaunchId] = useState(null);
  const [registrations, setRegistrations] = useState(null);
  const [sales, setSales] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [phaseBreakdown, setPhaseBreakdown] = useState(null);
  const [onboardingGap, setOnboardingGap] = useState(null);
  const [loading, setLoading] = useState(true);

  const launch = useMemo(
    () => launches.find((L) => L.id === launchId),
    [launches, launchId],
  );

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/launches");
        const sorted = [...data].sort((a, b) =>
          (b.start_date || "").localeCompare(a.start_date || ""),
        );
        setLaunches(sorted);
        if (sorted.length > 0) {
          // Prefer the active launch (today between start_date and end_date)
          const today = new Date().toISOString().split("T")[0];
          const active = sorted.find(
            (L) =>
              (L.start_date || "") <= today &&
              today <= (L.end_date || "9999-12-31"),
          );
          setLaunchId((active || sorted[0]).id);
        }
      } catch (err) {
        toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load launches");
      }
    })();
  }, []);

  useEffect(() => {
    if (!launchId) return;
    setLoading(true);
    setRegistrations(null);
    setSales(null);
    setComparison(null);
    setPhaseBreakdown(null);
    setOnboardingGap(null);
    Promise.all([
      apiClient
        .get(`/launches/${launchId}/registrations`, { timeout: 60000 })
        .then((r) => r.data)
        .catch((e) => ({ error: formatApiErrorDetail(e.response?.data?.detail) || e.message })),
      apiClient
        .get(`/launches/${launchId}/sales`, { timeout: 90000 })
        .then((r) => r.data)
        .catch((e) => ({ error: formatApiErrorDetail(e.response?.data?.detail) || e.message })),
    ])
      .then(([regs, sales]) => {
        setRegistrations(regs);
        setSales(sales);
      })
      .finally(() => setLoading(false));
    // Auto-load comparison + phase breakdown in background
    apiClient
      .get(`/launches/${launchId}/comparison`, { params: { n_previous: 2 }, timeout: 180000 })
      .then((r) => setComparison(r.data))
      .catch(() => setComparison(null));
    apiClient
      .get(`/launches/${launchId}/phase-breakdown`, { timeout: 30000 })
      .then((r) => setPhaseBreakdown(r.data))
      .catch(() => setPhaseBreakdown(null));
    apiClient
      .get(`/launches/${launchId}/onboarding-gap`, { timeout: 60000 })
      .then((r) => setOnboardingGap(r.data))
      .catch(() => setOnboardingGap(null));
  }, [launchId]);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="launch-dashboard-page">
      <HeroBanner
        {...HERO_PRESETS.launch}
        eyebrow="Launch"
        title={launch?.name || "Launch Dashboard"}
        subtitle="Live webinar registrations from ConvertKit and revenue from Stripe — broken down by source / product, with overlay against the previous two launches."
        testid="launch-hero"
        actions={
          <Select value={launchId || ""} onValueChange={setLaunchId}>
            <SelectTrigger
              className="w-56 h-10 bg-white/95 border-white/20 text-[var(--ayci-ink)]"
              data-testid="launch-selector"
            >
              <SelectValue placeholder="Select launch" />
            </SelectTrigger>
            <SelectContent>
              {launches.map((L) => (
                <SelectItem key={L.id} value={L.id} data-testid={`launch-option-${L.code}`}>
                  {L.name} {L.code ? `(${L.code})` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      {!launch && (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
          Pick a launch to see details.
        </div>
      )}

      {launch && (
        <>
          {/* KPI summary — 6 cards: revenue, signups (new/legacy/total), conversion, EPL, AOV/user, webinar regs (right) */}
          {loading && !registrations && !sales ? (
            <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
              <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
              Loading registrations + sales…
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <Stat
                icon={TrendingUp}
                label="Revenue"
                value={sales ? fmtGbp(sales.total_amount_gbp) : "—"}
                sub={`Goal £${Math.round(launch.target_good / 1000)}k / £${Math.round(launch.target_better / 1000)}k / £${Math.round(launch.target_best / 1000)}k`}
                tone="violet"
                testid="kpi-revenue"
              />
              <SignupsTile sales={sales} />
              <Stat
                icon={Calendar}
                label="Conversion"
                value={
                  registrations?.unique && sales?.total_count
                    ? `${((sales.total_count / registrations.unique) * 100).toFixed(1)}%`
                    : "—"
                }
                sub="Signups / unique regs"
                tone="amber"
                testid="kpi-conversion"
              />
              <Stat
                icon={TrendingUp}
                label="EPL"
                value={
                  registrations?.unique && sales?.total_amount_gbp
                    ? fmtGbp(sales.total_amount_gbp / registrations.unique)
                    : "—"
                }
                sub="Earnings per lead"
                tone="cyan"
                testid="kpi-epl"
              />
              <Stat
                icon={ShoppingBag}
                label="AOV"
                value={sales?.aov_per_user_gbp ? fmtGbp(sales.aov_per_user_gbp) : "—"}
                sub={
                  sales?.unique_customers
                    ? `Avg per user · ${sales.unique_customers} unique`
                    : "Avg per unique customer"
                }
                tone="magenta"
                testid="kpi-aov"
              />
              <Stat
                icon={Users}
                label="Webinar regs"
                value={registrations?.total ?? "—"}
                sub={
                  registrations?.unique
                    ? `${registrations.unique} unique`
                    : registrations?.error
                    ? registrations.error
                    : "Pulled from Kit"
                }
                tone="sky"
                testid="kpi-registrations"
              />
            </div>
          )}

          {/* Pace forecast — primary prediction, always visible for the active launch */}
          <PaceTrackerCard />

          {/* Compact phase timeline */}
          <PhaseTimeline launch={launch} />

          {/* Sales chart (cumulative + comparison auto-loaded) */}
          {sales && !sales.error && (
            <SalesChart launch={launch} sales={sales} comparison={comparison} />
          )}

          {/* Phase breakdown — compare each phase against previous 2 launches */}
          <PhaseBreakdown data={phaseBreakdown} launch={launch} />

          {/* Onboarding gap — students who paid but aren't in Circle cohort yet */}
          <OnboardingGap data={onboardingGap} launchId={launchId} onRefresh={(d) => setOnboardingGap(d)} />

          {/* Sales by tier */}
          {sales?.by_tier && sales.by_tier.length > 0 && (
            <SalesByTier sales={sales} />
          )}

          {/* Webinar — moved to the bottom (lower priority post-webinar) */}
          {registrations && !registrations.error && (
            <RegistrationsChart
              launch={launch}
              registrations={registrations}
              comparison={comparison}
            />
          )}

          {/* UTM source breakdown */}
          {registrations?.by_source && registrations.by_source.length > 0 && (
            <SourceBreakdown registrations={registrations} />
          )}
        </>
      )}
    </div>
  );
}

function Stat({ icon: Icon, label, value, sub, tone = "slate", testid }) {
  const toneMap = {
    slate: "bg-slate-50 text-slate-700",
    sky: "bg-sky-50 text-sky-700",
    emerald: "bg-emerald-50 text-emerald-700",
    violet: "bg-violet-50 text-violet-700",
    amber: "bg-amber-50 text-amber-700",
    cyan: "bg-cyan-50 text-cyan-700",
    magenta: "bg-fuchsia-50 text-fuchsia-700",
  };
  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-3 shadow-sm"
      data-testid={testid}
    >
      <div className={`inline-flex items-center gap-1.5 text-[9px] uppercase tracking-wider px-2 py-0.5 rounded-full font-subhead ${toneMap[tone]}`}>
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className="mt-1.5 font-display font-bold text-2xl lg:text-[1.65rem] text-[var(--ayci-ink)] leading-tight">
        {value}
      </div>
      {sub && <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5 line-clamp-2">{sub}</div>}
    </div>
  );
}

function PhaseTimeline({ launch }) {
  const phases = launch.phases || {};
  const today = new Date().toISOString().split("T")[0];
  const phaseList = Object.entries(PHASE_LABELS)
    .map(([key, label]) => ({
      key,
      label,
      start: phases[key]?.start?.split("T")[0],
      end: phases[key]?.end?.split("T")[0],
    }))
    .filter((p) => p.start && p.end);

  if (phaseList.length === 0) {
    return (
      <div className="bg-white border border-dashed border-[var(--ayci-border)] rounded-lg p-4 text-sm text-[var(--ayci-ink-muted)]">
        No phase dates set for this launch yet. Set them in <strong>Settings → Launches</strong>.
      </div>
    );
  }

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg px-4 py-2.5 shadow-sm flex flex-wrap items-center gap-x-4 gap-y-2"
      data-testid="phase-timeline"
    >
      <span className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] font-subhead pr-2 border-r border-[var(--ayci-border)]">
        Timeline
      </span>
      {phaseList.map((p) => {
        const isCurrent = today >= p.start && today <= p.end;
        const isPast = today > p.end;
        return (
          <div
            key={p.key}
            className="flex items-center gap-1.5 text-xs whitespace-nowrap"
            title={`${fmtDate(p.start)} → ${fmtDate(p.end)}`}
          >
            <span
              className="w-2 h-2 rounded-full inline-block"
              style={{
                backgroundColor: isPast
                  ? "#cbd5e1"
                  : isCurrent
                  ? PHASE_COLORS[p.key]
                  : "#e2e8f0",
                boxShadow: isCurrent ? `0 0 0 3px ${PHASE_COLORS[p.key]}33` : "none",
              }}
            />
            <span
              className={
                isCurrent
                  ? "font-medium text-[var(--ayci-ink)]"
                  : "text-[var(--ayci-ink-muted)]"
              }
            >
              {p.label}
            </span>
            {isCurrent && (
              <span
                className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-full font-subhead"
                style={{
                  backgroundColor: `${PHASE_COLORS[p.key]}1a`,
                  color: PHASE_COLORS[p.key],
                }}
              >
                Live
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function RegistrationsChart({ launch, registrations, comparison }) {
  // Build dataset by day_offset (days from launch start) for overlay
  const start = launch.start_date;
  const startDate = new Date(start + "T00:00:00Z");
  const offsetForDate = (d) =>
    Math.round((new Date(d + "T00:00:00Z") - startDate) / (1000 * 60 * 60 * 24));

  const currentByOffset = Object.fromEntries(
    (registrations.by_day || []).map((row) => [offsetForDate(row.date), row.total]),
  );

  // Find max offset across current + previous
  const allOffsets = [...Object.keys(currentByOffset).map(Number)];
  if (comparison?.previous) {
    comparison.previous.forEach((p) => {
      (p.registrations_aligned || []).forEach((r) => allOffsets.push(r.day_offset));
    });
  }
  const maxOffset = allOffsets.length ? Math.max(...allOffsets) : 0;
  const minOffset = 0;

  const data = [];
  for (let o = minOffset; o <= maxOffset; o++) {
    const row = { day_offset: o };
    row[launch.name] = currentByOffset[o] || 0;
    if (comparison?.previous) {
      comparison.previous.forEach((p) => {
        const map = Object.fromEntries(
          (p.registrations_aligned || []).map((r) => [r.day_offset, r.total]),
        );
        row[p.name] = map[o] || 0;
      });
    }
    data.push(row);
  }

  const series = [{ key: launch.name, color: SERIES_COLORS[0], strokeWidth: 3 }];
  if (comparison?.previous) {
    comparison.previous.forEach((p, i) => {
      series.push({
        key: p.name,
        color: SERIES_COLORS[i + 1] || "#cbd5e1",
        strokeWidth: 2,
        strokeDasharray: "4 4",
      });
    });
  }

  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="registrations-chart"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Webinar registrations
          </h2>
          <div className="text-xs text-[var(--ayci-ink-muted)]">
            By day from launch start (day 0 = {fmtDate(launch.start_date)})
          </div>
        </div>
      </div>
      <div className="h-72">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis
              dataKey="day_offset"
              tick={{ fontSize: 11, fill: "#64748b" }}
              label={{
                value: "Day from launch start",
                position: "insideBottom",
                offset: -5,
                style: { fontSize: 10, fill: "#64748b" },
              }}
            />
            <YAxis tick={{ fontSize: 11, fill: "#64748b" }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                stroke={s.color}
                strokeWidth={s.strokeWidth}
                strokeDasharray={s.strokeDasharray}
                dot={false}
                activeDot={{ r: 5 }}
              />
            ))}
            {launch.phases?.webinar?.start && (
              <ReferenceLine
                x={offsetForDate(launch.phases.webinar.start.split("T")[0])}
                stroke="#7c3aed"
                strokeDasharray="2 2"
                label={{ value: "Webinar", fontSize: 10, fill: "#7c3aed" }}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function SourceBreakdown({ registrations }) {
  const total = registrations.by_source.reduce((s, r) => s + r.count, 0);
  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="source-breakdown"
    >
      <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)] mb-4">
        Registrations by source (UTM)
      </h2>
      <div className="space-y-2">
        {registrations.by_source.map((row) => {
          const pct = total ? (row.count / total) * 100 : 0;
          return (
            <div key={row.source}>
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="font-medium text-[var(--ayci-ink)]">{row.source}</span>
                <span className="text-[var(--ayci-ink-muted)] text-xs">
                  {row.count} · {pct.toFixed(1)}%
                </span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: "#4457B6",
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function SalesChart({ launch, sales, comparison }) {
  const start = launch.start_date;
  const startDate = new Date(start + "T00:00:00Z");
  const offsetForDate = (d) =>
    Math.round((new Date(d + "T00:00:00Z") - startDate) / (1000 * 60 * 60 * 24));

  const currentByOffset = {};
  let cumul = 0;
  (sales.by_day || []).forEach((row) => {
    cumul += row.amount_gbp;
    currentByOffset[offsetForDate(row.date)] = { daily: row.amount_gbp, cumulative: cumul };
  });

  const allOffsets = [...Object.keys(currentByOffset).map(Number)];
  if (comparison?.previous) {
    comparison.previous.forEach((p) => {
      (p.sales_aligned || []).forEach((r) => allOffsets.push(r.day_offset));
    });
  }
  const maxOffset = allOffsets.length ? Math.max(...allOffsets) : 0;

  const data = [];
  const prevCumul = {};
  if (comparison?.previous) {
    comparison.previous.forEach((p) => {
      prevCumul[p.name] = 0;
    });
  }
  for (let o = 0; o <= maxOffset; o++) {
    const row = { day_offset: o };
    row[`${launch.name} cumulative`] = currentByOffset[o]?.cumulative || (
      o > 0 ? data[o - 1]?.[`${launch.name} cumulative`] || 0 : 0
    );
    if (comparison?.previous) {
      comparison.previous.forEach((p) => {
        const map = Object.fromEntries(
          (p.sales_aligned || []).map((r) => [r.day_offset, r.amount_gbp]),
        );
        if (map[o] !== undefined) prevCumul[p.name] += map[o];
        row[`${p.name} cumulative`] = prevCumul[p.name];
      });
    }
    data.push(row);
  }

  const series = [{
    key: `${launch.name} cumulative`,
    color: "#4457B6",
    strokeWidth: 4,
    isCurrent: true,
  }];
  if (comparison?.previous) {
    comparison.previous.forEach((p, i) => {
      series.push({
        key: `${p.name} cumulative`,
        color: i === 0 ? "#94a3b8" : "#cbd5e1",
        strokeWidth: 1.5,
        strokeDasharray: "5 4",
        isCurrent: false,
      });
    });
  }

  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="sales-chart"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Sales (cumulative revenue)
          </h2>
          <div className="text-xs text-[var(--ayci-ink-muted)]">
            From Stripe — by day from launch start
          </div>
        </div>
      </div>
      <div className="h-72">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis
              dataKey="day_offset"
              tick={{ fontSize: 11, fill: "#64748b" }}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#64748b" }}
              tickFormatter={(v) => `£${Math.round(v / 1000)}k`}
            />
            <Tooltip formatter={(v) => fmtGbp(v)} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                stroke={s.color}
                strokeWidth={s.strokeWidth}
                strokeDasharray={s.strokeDasharray}
                dot={s.isCurrent ? { r: 3, fill: s.color, stroke: "white", strokeWidth: 1 } : false}
                activeDot={s.isCurrent ? { r: 5 } : { r: 4 }}
              />
            ))}
            <ReferenceLine
              y={launch.target_good}
              stroke="#10b981"
              strokeDasharray="3 3"
              label={{ value: "Good", fontSize: 10, fill: "#10b981", position: "right" }}
            />
            <ReferenceLine
              y={launch.target_better}
              stroke="#f59e0b"
              strokeDasharray="3 3"
              label={{ value: "Better", fontSize: 10, fill: "#f59e0b", position: "right" }}
            />
            <ReferenceLine
              y={launch.target_best}
              stroke="#7c3aed"
              strokeDasharray="3 3"
              label={{ value: "Best", fontSize: 10, fill: "#7c3aed", position: "right" }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function SalesByTier({ sales }) {
  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="sales-by-tier"
    >
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
          Sales breakdown by tier
        </h2>
        <a
          href="https://dashboard.stripe.com"
          target="_blank"
          rel="noreferrer"
          className="text-xs text-[var(--ayci-teal)] hover:underline inline-flex items-center gap-1"
        >
          Open Stripe <ExternalLink className="w-3 h-3" />
        </a>
      </div>
      <div className="h-64">
        <ResponsiveContainer>
          <BarChart data={sales.by_tier} margin={{ top: 5, right: 20, left: 0, bottom: 30 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis
              dataKey="tier"
              tick={{ fontSize: 10, fill: "#64748b" }}
              angle={-25}
              textAnchor="end"
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#64748b" }}
              tickFormatter={(v) => `£${Math.round(v / 1000)}k`}
            />
            <Tooltip formatter={(v) => fmtGbp(v)} />
            <Bar dataKey="amount_gbp" fill="#4457B6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 text-xs text-[var(--ayci-ink-muted)] grid grid-cols-2 md:grid-cols-4 gap-2">
        {sales.by_tier.map((p) => (
          <div
            key={p.tier}
            className="bg-slate-50 border border-[var(--ayci-border)] rounded p-2"
          >
            <div className="flex items-baseline justify-between gap-2">
              <div className="font-medium text-[var(--ayci-ink)] truncate">{p.tier}</div>
              <div className="text-[10px] font-semibold text-[var(--ayci-accent)] flex-shrink-0">
                {p.pct_of_revenue}%
              </div>
            </div>
            <div className="text-[var(--ayci-ink-muted)]">
              {p.count} sales · {fmtGbp(p.amount_gbp)}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}


function SignupsTile({ sales }) {
  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-3 shadow-sm"
      data-testid="kpi-sales-count"
    >
      <div className="inline-flex items-center gap-1.5 text-[9px] uppercase tracking-wider px-2 py-0.5 rounded-full font-subhead bg-emerald-50 text-emerald-700">
        <ShoppingBag className="w-3 h-3" />
        Signups
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="font-display font-bold text-2xl text-[var(--ayci-ink)] leading-none">
          {sales?.total_count ?? "—"}
        </span>
        <span className="text-[10px] text-[var(--ayci-ink-muted)] uppercase tracking-wider">
          total
        </span>
      </div>
      <div className="mt-1 flex items-center gap-3 text-[10px] text-[var(--ayci-ink-muted)]">
        <span>
          <span className="font-semibold text-emerald-700">
            {sales?.new_signup_count ?? 0}
          </span>{" "}
          new
        </span>
        <span>
          <span className="font-semibold text-violet-700">
            {sales?.legacy_count ?? 0}
          </span>{" "}
          legacy
        </span>
      </div>
    </div>
  );
}

const PHASE_BREAKDOWN_LABELS = {
  in_between_start: "In-between (start)",
  early_access: "Early access",
  flash_sale: "Flash sale",
  webinar: "Webinar",
  open_cart: "Open cart",
  close_cart: "Close cart",
  in_between_end: "In-between (end)",
};

function PhaseBreakdown({ data, launch }) {
  if (!data) {
    return (
      <section
        className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
        data-testid="phase-breakdown-loading"
      >
        <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)] mb-2">
          Phase breakdown vs previous launches
        </h2>
        <div className="text-xs text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading per-phase comparison…
        </div>
      </section>
    );
  }

  if (data.computing) {
    return (
      <section
        className="bg-sky-50 border border-sky-200 rounded-lg p-4 text-sm text-sky-800"
        data-testid="phase-breakdown-computing"
      >
        <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
        First-time scan running across the active + 2 previous launches.
        Refresh in 2-3 minutes.
      </section>
    );
  }

  const current = data.current || {};
  const previous = data.previous || [];
  const currentPhases = current.phases || [];
  // All series share the same phase order; map by phase key
  const allLaunches = [
    { code: launch.code, name: launch.name || current.code, phases: currentPhases, isCurrent: true },
    ...previous.map((p) => ({
      code: p.code,
      name: p.name || p.code,
      phases: p.phases || [],
      isCurrent: false,
    })),
  ];

  const phaseRows = currentPhases.map((p) => {
    const row = { phase: p.phase };
    for (const L of allLaunches) {
      const match = (L.phases || []).find((x) => x.phase === p.phase) || {};
      row[L.code] = {
        signups: match.signups || 0,
        revenue: match.revenue_gbp || 0,
        regs: match.registrations || 0,
      };
    }
    return row;
  });

  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm overflow-hidden"
      data-testid="phase-breakdown"
    >
      <div className="p-5 border-b border-[var(--ayci-border)]">
        <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
          Phase breakdown vs previous launches
        </h2>
        <div className="text-xs text-[var(--ayci-ink-muted)]">
          Signups · Revenue · Webinar regs per phase. Boost & Go excluded from sales.
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-[var(--ayci-border)]">
            <tr className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
              <th className="text-left p-3">Phase</th>
              {allLaunches.map((L) => (
                <th
                  key={L.code}
                  className={
                    "text-right p-3 " +
                    (L.isCurrent ? "text-[var(--ayci-accent)] font-bold" : "")
                  }
                >
                  {L.name}
                  {L.isCurrent && (
                    <span className="ml-1 inline-block text-[9px] px-1.5 py-0.5 bg-[var(--ayci-accent)]/10 text-[var(--ayci-accent)] rounded-full">
                      Current
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {phaseRows.map((row) => (
              <tr
                key={row.phase}
                className="border-b border-[var(--ayci-border)] last:border-b-0 hover:bg-slate-50 transition-colors"
              >
                <td className="p-3 font-medium text-[var(--ayci-ink)] text-xs">
                  {PHASE_BREAKDOWN_LABELS[row.phase] || row.phase}
                </td>
                {allLaunches.map((L) => {
                  const c = row[L.code] || {};
                  return (
                    <td
                      key={L.code}
                      className={
                        "p-3 text-right text-xs " +
                        (L.isCurrent ? "font-semibold" : "text-[var(--ayci-ink-muted)]")
                      }
                    >
                      <div className="text-[var(--ayci-ink)]">
                        {fmtGbp(c.revenue || 0)}
                      </div>
                      <div className="text-[10px] text-[var(--ayci-ink-muted)]">
                        {c.signups} signup{c.signups === 1 ? "" : "s"}
                        {c.regs > 0 && ` · ${c.regs} regs`}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ---- Onboarding gap: paid but not in Circle cohort yet --------------------
function OnboardingGap({ data, launchId, onRefresh }) {
  const [refreshing, setRefreshing] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [tab, setTab] = useState("gap"); // "gap" | "unmatched"

  if (!data) {
    return (
      <section className="bg-white border border-[var(--ayci-border)] rounded-2xl p-5 shadow-sm" data-testid="onboarding-gap-section">
        <div className="text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading onboarding gap…
        </div>
      </section>
    );
  }
  if (data.error) {
    return (
      <section className="bg-white border border-rose-200 rounded-2xl p-5 shadow-sm">
        <div className="text-sm text-rose-700">Couldn't load onboarding gap: {data.error}</div>
      </section>
    );
  }

  const refresh = async () => {
    setRefreshing(true);
    try {
      const { data: fresh } = await apiClient.get(
        `/launches/${launchId}/onboarding-gap`,
        { params: { refresh: true }, timeout: 90000 },
      );
      onRefresh(fresh);
      toast.success("Refreshed");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Couldn't refresh");
    } finally {
      setRefreshing(false);
    }
  };

  const total = data.new_signups_total || 0;
  const inCohort = data.in_cohort_count || 0;
  const inCohortPct = total ? Math.round((inCohort / total) * 100) : 0;
  const rows = tab === "gap" ? (data.gap || []) : (data.unmatched || []);
  const visible = showAll ? rows : rows.slice(0, 10);

  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-2xl p-5 sm:p-6 shadow-sm"
      data-testid="onboarding-gap-section"
    >
      <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-600" />
            <h2 className="font-display font-bold text-xl text-[var(--ayci-ink)]">
              Onboarding gap
            </h2>
          </div>
          <p className="text-xs text-[var(--ayci-ink-muted)] mt-1 max-w-2xl">
            New signups in this launch's window who aren't yet in the cohort's
            Circle spaces. Cross-references Stripe new-signup customers with
            Monday's "On Circle" status (looks for{" "}
            <strong>{data.expected_circle_label || "the cohort label"}</strong>).
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="text-sm bg-white border border-[var(--ayci-border)] rounded-lg px-3 py-1.5 hover:bg-slate-50 disabled:opacity-50 flex items-center gap-1.5"
          data-testid="onboarding-gap-refresh"
        >
          {refreshing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <GapStat label="New signups" value={total} />
        <GapStat label="In cohort" value={inCohort} hint={`${inCohortPct}%`} tone="emerald" />
        <GapStat label="Onboarding gap" value={data.gap_count || 0} tone={(data.gap_count || 0) > 0 ? "amber" : "slate"} />
        <GapStat label="Not on Monday" value={data.unmatched_count || 0} tone={(data.unmatched_count || 0) > 0 ? "rose" : "slate"} />
      </div>

      {/* Tab switcher */}
      <div className="flex items-center gap-2 mb-3">
        <TabButton active={tab === "gap"} onClick={() => { setTab("gap"); setShowAll(false); }} data-testid="onboarding-gap-tab-gap">
          Gap ({data.gap_count || 0})
        </TabButton>
        <TabButton active={tab === "unmatched"} onClick={() => { setTab("unmatched"); setShowAll(false); }} data-testid="onboarding-gap-tab-unmatched">
          Not on Monday ({data.unmatched_count || 0})
        </TabButton>
      </div>

      {rows.length === 0 ? (
        <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg p-4 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" />
          {tab === "gap"
            ? "Every paying customer is already in the cohort spaces. Nice work."
            : "Every paying customer has been added to the Monday Academy Members board."}
        </div>
      ) : (
        <div className="overflow-x-auto -mx-1 px-1 border border-[var(--ayci-border)] rounded-lg">
          <table className="min-w-full text-sm" data-testid="onboarding-gap-table">
            <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] font-display font-semibold">
              <tr>
                <th className="text-left px-3 py-2">Signed up</th>
                <th className="text-left px-3 py-2">Email</th>
                <th className="text-left px-3 py-2">Tier</th>
                <th className="text-left px-3 py-2">Reason</th>
                {tab === "gap" && <th className="text-left px-3 py-2">Monday</th>}
              </tr>
            </thead>
            <tbody>
              {visible.map((r, i) => (
                <tr key={`${r.email || r.customer_id}-${i}`} className="border-t border-[var(--ayci-border)]">
                  <td className="px-3 py-2 text-xs text-[var(--ayci-ink-muted)] whitespace-nowrap tabular-nums">
                    {r.signup_date}
                  </td>
                  <td className="px-3 py-2">
                    <div className="font-medium text-[var(--ayci-ink)]">{r.name || r.monday_name || "—"}</div>
                    <div className="text-xs text-[var(--ayci-ink-muted)] break-all">{r.email || "(no email)"}</div>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    <span className="px-2 py-0.5 bg-slate-100 text-slate-700 rounded-full font-semibold">
                      {r.tier_hint || "—"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-[var(--ayci-ink)]">
                    {r.reason}
                    {r.circle_join_followup && (
                      <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5">
                        Follow-up: <strong>{r.circle_join_followup}</strong>
                      </div>
                    )}
                  </td>
                  {tab === "gap" && (
                    <td className="px-3 py-2 text-xs">
                      {r.monday_url ? (
                        <a
                          href={r.monday_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[var(--ayci-teal)] hover:underline inline-flex items-center gap-1"
                        >
                          Open <ExternalLink className="w-3 h-3" />
                        </a>
                      ) : (
                        <span className="text-[var(--ayci-ink-muted)]">—</span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rows.length > 10 && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="mt-3 text-xs text-[var(--ayci-teal)] hover:underline font-display font-semibold"
          data-testid="onboarding-gap-toggle"
        >
          {showAll ? `Show top 10` : `Show all ${rows.length}`}
        </button>
      )}
    </section>
  );
}

function TabButton({ active, onClick, children, ...rest }) {
  return (
    <button
      onClick={onClick}
      className={[
        "text-xs font-display font-semibold px-3 py-1.5 rounded-full border transition-colors",
        active
          ? "bg-[var(--ayci-teal)] text-white border-[var(--ayci-teal)]"
          : "bg-white text-[var(--ayci-ink-muted)] border-[var(--ayci-border)] hover:bg-slate-50",
      ].join(" ")}
      {...rest}
    >
      {children}
    </button>
  );
}

function GapStat({ label, value, hint, tone = "slate" }) {
  const tones = {
    slate: "bg-slate-50 border-slate-200 text-slate-700",
    emerald: "bg-emerald-50 border-emerald-200 text-emerald-700",
    amber: "bg-amber-50 border-amber-200 text-amber-700",
    rose: "bg-rose-50 border-rose-200 text-rose-700",
  };
  return (
    <div className={`rounded-lg border p-2.5 ${tones[tone]}`}>
      <div className="text-[10px] uppercase tracking-wider font-display font-semibold opacity-80">
        {label}
      </div>
      <div className="font-display font-bold text-2xl text-[var(--ayci-ink)] mt-0.5 tabular-nums">{value}</div>
      {hint && <div className="text-[10px] opacity-70">{hint}</div>}
    </div>
  );
}
