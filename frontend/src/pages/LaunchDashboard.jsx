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
import { Loader2, Calendar, TrendingUp, ShoppingBag, Users, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { PaceTrackerCard } from "@/components/PaceTracker";
import YearOverview from "@/components/YearOverview";

const PHASE_LABELS = {
  early_signups: "Early signups",
  flash_sale: "Flash sale",
  webinar: "Webinar",
  open_cart: "Open cart",
  legacy_upgrades: "Legacy upgrades",
  close_cart: "Close cart",
  in_between: "In-between",
};

const PHASE_COLORS = {
  early_signups: "#0ea5e9",
  flash_sale: "#dc2626",
  webinar: "#7c3aed",
  open_cart: "#10b981",
  legacy_upgrades: "#a855f7",
  close_cart: "#f59e0b",
  in_between: "#64748b",
};

const SERIES_COLORS = ["#0ea5e9", "#94a3b8", "#cbd5e1"];

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
  const [loading, setLoading] = useState(true);
  const [loadingComparison, setLoadingComparison] = useState(false);

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
        if (sorted[0]) setLaunchId(sorted[0].id);
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
  }, [launchId]);

  const loadComparison = async () => {
    if (!launchId) return;
    setLoadingComparison(true);
    try {
      const { data } = await apiClient.get(`/launches/${launchId}/comparison`, {
        params: { n_previous: 2 },
        timeout: 180000,
      });
      setComparison(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Comparison failed");
    } finally {
      setLoadingComparison(false);
    }
  };

  return (
    <div className="p-8 space-y-6" data-testid="launch-dashboard-page">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] font-display font-semibold tracking-[0.25em] uppercase text-[var(--ayci-teal)]">
            Launch
          </div>
          <h1 className="text-4xl font-display font-bold text-[var(--ayci-ink)] mt-1">
            {launch?.name || "Launch Dashboard"}
          </h1>
          <p className="text-[var(--ayci-ink-muted)] text-sm mt-1 max-w-2xl">
            Live webinar registrations from ConvertKit and revenue from Stripe — broken
            down by source / product, with overlay against the previous two launches.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={launchId || ""} onValueChange={setLaunchId}>
            <SelectTrigger className="w-56 h-10" data-testid="launch-selector">
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
        </div>
      </div>

      {!launch && (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
          Pick a launch to see details.
        </div>
      )}

      {/* Year overview strip — always visible, click a launch to switch */}
      <YearOverview onSelect={setLaunchId} selectedId={launchId} />

      {launch && (
        <>
          {/* Phase timeline */}
          <PhaseTimeline launch={launch} />

          {/* KPI summary */}
          {loading && !registrations && !sales ? (
            <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
              <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
              Loading registrations + sales…
            </div>
          ) : (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <Stat
                icon={Users}
                label="Webinar registrations"
                value={registrations?.total ?? "—"}
                sub={
                  registrations?.unique
                    ? `${registrations.unique} unique people`
                    : registrations?.error
                    ? registrations.error
                    : "Pulled from Kit"
                }
                tone="sky"
                testid="kpi-registrations"
              />
              <Stat
                icon={ShoppingBag}
                label="Sales"
                value={sales?.total_count ?? "—"}
                sub={
                  sales?.error || `${sales?.by_product?.length || 0} product types`
                }
                tone="emerald"
                testid="kpi-sales-count"
              />
              <Stat
                icon={TrendingUp}
                label="Revenue"
                value={sales ? fmtGbp(sales.total_amount_gbp) : "—"}
                sub={`Goal £${Math.round(launch.target_good / 1000)}k / £${Math.round(launch.target_better / 1000)}k / £${Math.round(launch.target_best / 1000)}k`}
                tone="violet"
                testid="kpi-revenue"
              />
              <Stat
                icon={Calendar}
                label="Conversion"
                value={
                  registrations?.unique && sales?.total_count
                    ? `${((sales.total_count / registrations.unique) * 100).toFixed(1)}%`
                    : "—"
                }
                sub="Sales / unique registrations"
                tone="amber"
                testid="kpi-conversion"
              />
            </div>
          )}

          {/* Compare button */}
          <div className="flex justify-end">
            <button
              onClick={loadComparison}
              disabled={loadingComparison || !launch.code}
              className="text-sm bg-white border border-[var(--ayci-border)] rounded-lg px-4 py-2 hover:bg-slate-50 disabled:opacity-50"
              data-testid="load-comparison-btn"
            >
              {loadingComparison ? (
                <>
                  <Loader2 className="w-4 h-4 inline mr-2 animate-spin" /> Loading comparison…
                </>
              ) : comparison ? (
                "Comparison loaded ✓"
              ) : (
                "Compare to previous 2 launches"
              )}
            </button>
          </div>

          {/* Pace tracker — only when current launch is the active one */}
          <PaceTrackerCard />

          {/* Webinar registrations chart */}
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

          {/* Sales chart */}
          {sales && !sales.error && (
            <SalesChart launch={launch} sales={sales} comparison={comparison} />
          )}

          {/* Sales by product */}
          {sales?.by_product && sales.by_product.length > 0 && (
            <SalesByProduct sales={sales} />
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
  };
  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm"
      data-testid={testid}
    >
      <div className={`inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${toneMap[tone]}`}>
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className="mt-2 font-display font-bold text-3xl text-[var(--ayci-ink)]">
        {value}
      </div>
      {sub && <div className="text-xs text-[var(--ayci-ink-muted)] mt-1 line-clamp-2">{sub}</div>}
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
    <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm">
      <h2 className="font-display font-bold text-base text-[var(--ayci-ink)] mb-4">
        Launch timeline
      </h2>
      <div className="space-y-2">
        {phaseList.map((p) => {
          const isCurrent = today >= p.start && today <= p.end;
          const isPast = today > p.end;
          return (
            <div key={p.key} className="flex items-center gap-3">
              <div
                className="w-3 h-3 rounded-full"
                style={{
                  backgroundColor: isPast
                    ? "#cbd5e1"
                    : isCurrent
                    ? PHASE_COLORS[p.key]
                    : "#e2e8f0",
                  boxShadow: isCurrent ? `0 0 0 4px ${PHASE_COLORS[p.key]}33` : "none",
                }}
              />
              <div className="flex-1 flex items-center justify-between text-sm">
                <span
                  className={
                    "font-medium " +
                    (isCurrent
                      ? "text-[var(--ayci-ink)]"
                      : "text-[var(--ayci-ink-muted)]")
                  }
                >
                  {p.label}
                  {isCurrent && (
                    <span
                      className="ml-2 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded-full"
                      style={{
                        backgroundColor: `${PHASE_COLORS[p.key]}1a`,
                        color: PHASE_COLORS[p.key],
                      }}
                    >
                      Live now
                    </span>
                  )}
                </span>
                <span className="text-xs text-[var(--ayci-ink-muted)]">
                  {fmtDate(p.start)} → {fmtDate(p.end)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
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
                    backgroundColor: "#0ea5e9",
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

  const series = [{ key: `${launch.name} cumulative`, color: SERIES_COLORS[0], strokeWidth: 3 }];
  if (comparison?.previous) {
    comparison.previous.forEach((p, i) => {
      series.push({
        key: `${p.name} cumulative`,
        color: SERIES_COLORS[i + 1] || "#cbd5e1",
        strokeWidth: 2,
        strokeDasharray: "4 4",
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
                dot={false}
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

function SalesByProduct({ sales }) {
  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="sales-by-product"
    >
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
          Sales breakdown by product
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
          <BarChart data={sales.by_product} margin={{ top: 5, right: 20, left: 0, bottom: 30 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis
              dataKey="product"
              tick={{ fontSize: 10, fill: "#64748b" }}
              angle={-25}
              textAnchor="end"
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#64748b" }}
              tickFormatter={(v) => `£${Math.round(v / 1000)}k`}
            />
            <Tooltip formatter={(v) => fmtGbp(v)} />
            <Bar dataKey="amount_gbp" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 text-xs text-[var(--ayci-ink-muted)] grid grid-cols-2 md:grid-cols-4 gap-2">
        {sales.by_product.map((p) => (
          <div
            key={p.product}
            className="bg-slate-50 border border-[var(--ayci-border)] rounded p-2"
          >
            <div className="font-medium text-[var(--ayci-ink)]">{p.product}</div>
            <div className="text-[var(--ayci-ink-muted)]">
              {p.count} sales · {fmtGbp(p.amount_gbp)}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
