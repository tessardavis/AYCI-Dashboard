import { useEffect, useMemo, useState } from "react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
  Legend,
} from "recharts";
import { toast } from "sonner";
import { formatValue, formatDateShort } from "@/lib/format";

const TIER_PRICES = {
  academy: 597,
  private_plus: 1188,
  vip: 1782,
  boost: 594,
  upgrade: 591, // avg PP upgrade
  upsell: 297, // avg upsell
};

export default function LaunchDashboard() {
  const [launches, setLaunches] = useState([]);
  const [launchId, setLaunchId] = useState(null);
  const [launchData, setLaunchData] = useState(null);
  const [daily, setDaily] = useState([]);
  const [prevDaily, setPrevDaily] = useState([]);
  const [allData, setAllData] = useState({}); // launch_id -> data
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/launches");
        const sorted = [...data].sort((a, b) =>
          (b.start_date || "").localeCompare(a.start_date || "")
        );
        setLaunches(sorted);
        if (sorted.length > 0) setLaunchId(sorted[0].id);
      } catch (e) {
        toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
      }
    })();
  }, []);

  useEffect(() => {
    if (!launchId || launches.length === 0) return;
    const idx = launches.findIndex((l) => l.id === launchId);
    const prev = idx >= 0 && idx + 1 < launches.length ? launches[idx + 1] : null;
    (async () => {
      setLoading(true);
      try {
        const calls = [
          apiClient.get(`/launches/${launchId}/data`),
          apiClient.get(`/launches/${launchId}/daily-registrations`),
        ];
        if (prev) {
          calls.push(apiClient.get(`/launches/${prev.id}/daily-registrations`));
        }
        const results = await Promise.all(calls);
        setLaunchData(results[0].data);
        setDaily(results[1].data);
        setPrevDaily(prev ? results[2].data : []);

        // Fetch all launch data for comparison chart (once)
        const allDataResp = await Promise.all(
          launches.map((l) => apiClient.get(`/launches/${l.id}/data`).then((r) => [l.id, r.data]))
        );
        setAllData(Object.fromEntries(allDataResp));
      } catch (e) {
        toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [launchId, launches]);

  const activeLaunch = useMemo(
    () => launches.find((l) => l.id === launchId) || null,
    [launches, launchId]
  );
  const prevLaunch = useMemo(() => {
    const idx = launches.findIndex((l) => l.id === launchId);
    return idx >= 0 && idx + 1 < launches.length ? launches[idx + 1] : null;
  }, [launches, launchId]);

  const sales = useMemo(() => {
    if (!launchData) return { rows: [], totalCount: 0, totalRevenue: 0 };
    const rows = [
      { key: "academy", label: "Academy", price: 597, count: launchData.sales_academy_count || 0 },
      { key: "private_plus", label: "Private Plus", price: 1188, count: launchData.sales_private_plus_count || 0 },
      { key: "vip", label: "VIP", price: 1782, count: launchData.sales_vip_count || 0 },
      { key: "boost", label: "Boost & Go", price: 594, count: launchData.sales_boost_count || 0 },
      { key: "upgrade", label: "Upgrades (PP/VIP)", price: TIER_PRICES.upgrade, count: launchData.upgrade_count || 0 },
      { key: "upsell", label: "Upsells (120 Q / 25 Q)", price: TIER_PRICES.upsell, count: launchData.upsell_count || 0 },
    ].map((r) => ({ ...r, revenue: r.price * r.count }));
    const totalCount = rows.reduce((s, r) => s + r.count, 0);
    const totalRevenue = rows.reduce((s, r) => s + r.revenue, 0);
    return { rows, totalCount, totalRevenue };
  }, [launchData]);

  const chartData = useMemo(() => {
    // merge current + prev daily registrations on date (label = day offset relative to webinar)
    const cur = [...(daily || [])].sort((a, b) => a.date.localeCompare(b.date));
    const prev = [...(prevDaily || [])].sort((a, b) => a.date.localeCompare(b.date));
    const curLen = cur.length;
    const prevLen = prev.length;

    let cumCur = 0;
    return cur.map((d, i) => {
      cumCur += Number(d.count) || 0;
      const prevItem = prev[prev.length - curLen + i]; // align by days-before-webinar
      return {
        date: formatDateShort(d.date),
        daily: Number(d.count) || 0,
        cumulative: cumCur,
        prev: prevItem ? Number(prevItem.count) || 0 : null,
      };
    });
  }, [daily, prevDaily]);

  const comparison = useMemo(() => {
    return launches
      .slice()
      .reverse()
      .map((l) => {
        const d = allData[l.id] || {};
        const revenue =
          (d.sales_academy_count || 0) * 597 +
          (d.sales_private_plus_count || 0) * 1188 +
          (d.sales_vip_count || 0) * 1782 +
          (d.sales_boost_count || 0) * 594 +
          (d.upgrade_count || 0) * TIER_PRICES.upgrade +
          (d.upsell_count || 0) * TIER_PRICES.upsell;
        const salesCount =
          (d.sales_academy_count || 0) +
          (d.sales_private_plus_count || 0) +
          (d.sales_vip_count || 0) +
          (d.sales_boost_count || 0);
        return {
          name: l.name,
          regs: d.total_registrations || 0,
          sales: salesCount,
          revenue: Math.round(revenue),
        };
      });
  }, [launches, allData]);

  const updateField = async (field, value) => {
    const num = Number(value);
    const safe = Number.isNaN(num) ? 0 : num;
    setLaunchData((s) => ({ ...s, [field]: safe }));
    try {
      await apiClient.patch(`/launches/${launchId}/data`, { [field]: safe });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  if (!launches.length) {
    return (
      <div className="p-8">
        <PageHeader eyebrow="Launches" title="Launch Dashboard" />
        <div className="text-sm text-[var(--ayci-ink-muted)]">
          No launches yet. Create one from Settings → Launches.
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 lg:p-12 ayci-fade-up">
      <PageHeader
        eyebrow="Launch Pacing"
        title="Launch Dashboard"
        description="Webinar-driven launch cycles. Track registrations, attendance, sales and revenue against Good/Better/Best targets."
        right={
          <Select value={launchId || ""} onValueChange={setLaunchId}>
            <SelectTrigger className="w-[180px] bg-white" data-testid="launch-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {launches.map((l) => (
                <SelectItem key={l.id} value={l.id} data-testid={`launch-option-${l.name}`}>
                  {l.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      {loading || !launchData ? (
        <div className="text-sm text-[var(--ayci-ink-muted)]">Loading…</div>
      ) : (
        <div className="space-y-8">
          {/* KPI Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
            <KPICard
              label="Webinar Registrations"
              value={launchData.total_registrations}
              format="number"
              editable
              onChange={(v) => updateField("total_registrations", v)}
              testid="kpi-regs"
            />
            <KPICard
              label="Webinar Attendance Rate"
              value={launchData.webinar_attendance_rate}
              format="percentage"
              editable
              onChange={(v) => updateField("webinar_attendance_rate", v)}
              testid="kpi-attendance"
            />
            <KPICard
              label="Total Sales"
              value={sales.totalCount}
              format="number"
              testid="kpi-sales"
            />
            <KPICard
              label="Total Revenue"
              value={sales.totalRevenue}
              format="currency"
              testid="kpi-revenue"
            />
          </div>

          {/* Revenue vs Target stepped bar */}
          {activeLaunch && (
            <RevenueTargetBar
              current={sales.totalRevenue}
              good={activeLaunch.target_good}
              better={activeLaunch.target_better}
              best={activeLaunch.target_best}
            />
          )}

          {/* Daily registrations chart */}
          <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-6 lg:p-8 shadow-sm">
            <div className="flex items-baseline justify-between mb-6">
              <div>
                <div className="font-display text-lg font-bold text-[var(--ayci-ink)]">
                  Daily Registrations
                </div>
                <div className="text-xs text-[var(--ayci-ink-muted)] mt-1">
                  {activeLaunch?.name} vs {prevLaunch ? prevLaunch.name : "—"} (aligned by days-to-webinar)
                </div>
              </div>
              <Legend
                payload={[
                  { value: `${activeLaunch?.name} daily`, type: "line", color: "#0EA5E9" },
                  { value: "Cumulative", type: "line", color: "#1A1F36" },
                  ...(prevLaunch ? [{ value: `${prevLaunch.name} daily`, type: "line", color: "#CBD5E1" }] : []),
                ]}
              />
            </div>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="date" tick={{ fill: "#6B7280", fontSize: 11 }} />
                  <YAxis yAxisId="left" tick={{ fill: "#6B7280", fontSize: 11 }} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fill: "#6B7280", fontSize: 11 }} />
                  <Tooltip />
                  {prevLaunch && (
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="prev"
                      stroke="#CBD5E1"
                      strokeWidth={2}
                      strokeDasharray="4 4"
                      dot={false}
                      name={`${prevLaunch.name}`}
                    />
                  )}
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="daily"
                    stroke="#0EA5E9"
                    strokeWidth={2.5}
                    dot={{ r: 3, fill: "#0EA5E9" }}
                    name="Daily"
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="cumulative"
                    stroke="#1A1F36"
                    strokeWidth={2}
                    dot={false}
                    name="Cumulative"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Sales breakdown + Comparison */}
          <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">
            <div className="xl:col-span-3 bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm overflow-hidden">
              <div className="px-6 pt-6 pb-4 border-b border-[var(--ayci-border)]">
                <div className="font-display text-lg font-bold text-[var(--ayci-ink)]">Sales Breakdown</div>
                <div className="text-xs text-[var(--ayci-ink-muted)] mt-1">
                  Enter unit counts — revenue calculated automatically.
                </div>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 border-b border-[var(--ayci-border)]">
                    <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Tier</th>
                    <th className="text-right px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Unit £</th>
                    <th className="text-right px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Count</th>
                    <th className="text-right px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Revenue</th>
                  </tr>
                </thead>
                <tbody>
                  {sales.rows.map((r) => {
                    const field =
                      r.key === "academy"
                        ? "sales_academy_count"
                        : r.key === "private_plus"
                        ? "sales_private_plus_count"
                        : r.key === "vip"
                        ? "sales_vip_count"
                        : r.key === "boost"
                        ? "sales_boost_count"
                        : r.key === "upgrade"
                        ? "upgrade_count"
                        : "upsell_count";
                    return (
                      <tr key={r.key} className="border-b border-[var(--ayci-border)] last:border-0">
                        <td className="px-6 py-3 font-medium text-[var(--ayci-ink)]">{r.label}</td>
                        <td className="px-6 py-3 text-right text-[var(--ayci-ink-muted)] tabular-nums">
                          £{r.price.toLocaleString("en-GB")}
                        </td>
                        <td className="px-6 py-3 text-right">
                          <Input
                            type="number"
                            value={r.count}
                            onChange={(e) => updateField(field, e.target.value)}
                            className="w-24 ml-auto text-right h-8 tabular-nums"
                            data-testid={`sales-input-${r.key}`}
                          />
                        </td>
                        <td className="px-6 py-3 text-right font-semibold metric-number text-[var(--ayci-ink)]">
                          {formatValue(r.revenue, "currency")}
                        </td>
                      </tr>
                    );
                  })}
                  <tr className="bg-slate-50">
                    <td className="px-6 py-3 font-semibold">Total</td>
                    <td />
                    <td className="px-6 py-3 text-right font-semibold tabular-nums">{sales.totalCount}</td>
                    <td className="px-6 py-3 text-right font-bold metric-number text-[var(--ayci-ink)]">
                      {formatValue(sales.totalRevenue, "currency")}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="xl:col-span-2 bg-white border border-[var(--ayci-border)] rounded-lg p-6 lg:p-8 shadow-sm">
              <div className="font-display text-lg font-bold text-[var(--ayci-ink)]">Launch-over-Launch</div>
              <div className="text-xs text-[var(--ayci-ink-muted)] mt-1 mb-4">Total revenue comparison.</div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={comparison}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="name" tick={{ fill: "#6B7280", fontSize: 11 }} />
                    <YAxis tick={{ fill: "#6B7280", fontSize: 11 }} />
                    <Tooltip
                      formatter={(v, k) => (k === "revenue" ? [formatValue(v, "currency"), "Revenue"] : [v, k])}
                    />
                    <Bar dataKey="revenue" radius={[4, 4, 0, 0]} fill="#0EA5E9" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="grid grid-cols-3 gap-3 mt-4 text-center">
                {comparison.map((c) => (
                  <div key={c.name} className="bg-slate-50 rounded-md py-2">
                    <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">{c.name}</div>
                    <div className="text-xs metric-number font-semibold mt-0.5">{c.regs} regs · {c.sales} sales</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function KPICard({ label, value, format, editable, onChange, testid }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value ?? ""));
  useEffect(() => setDraft(String(value ?? "")), [value]);

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-6 shadow-sm ayci-card-hover cursor-pointer"
      onClick={() => editable && setEditing(true)}
      data-testid={testid}
    >
      <div className="text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-3">{label}</div>
      {editing ? (
        <Input
          autoFocus
          type="number"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            setEditing(false);
            onChange(draft);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              setEditing(false);
              onChange(draft);
            }
            if (e.key === "Escape") setEditing(false);
          }}
          className="font-display text-3xl font-bold h-12 tabular-nums"
        />
      ) : (
        <div className="font-display text-3xl font-bold metric-number text-[var(--ayci-ink)]">
          {formatValue(value, format)}
        </div>
      )}
      {editable && !editing && (
        <div className="text-[10px] text-[var(--ayci-accent)] mt-2">Click to edit</div>
      )}
    </div>
  );
}

function RevenueTargetBar({ current, good, better, best }) {
  const max = best * 1.05;
  const pct = Math.min(100, (current / max) * 100);
  const goodPct = (good / max) * 100;
  const betterPct = (better / max) * 100;
  const bestPct = (best / max) * 100;

  let tier = "Pre-Good";
  let tierColor = "#64748B";
  if (current >= best) { tier = "🏆 Best"; tierColor = "#D97706"; }
  else if (current >= better) { tier = "Better"; tierColor = "#0EA5E9"; }
  else if (current >= good) { tier = "Good"; tierColor = "#10B981"; }

  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-6 lg:p-8 shadow-sm" data-testid="revenue-target-bar">
      <div className="flex items-baseline justify-between mb-4 flex-wrap gap-2">
        <div>
          <div className="font-display text-lg font-bold text-[var(--ayci-ink)]">Revenue vs Target</div>
          <div className="text-xs text-[var(--ayci-ink-muted)] mt-1">
            Current: <span className="metric-number font-semibold text-[var(--ayci-ink)]">{formatValue(current, "currency")}</span>
            <span className="mx-2">·</span>
            Tier: <span className="font-semibold" style={{ color: tierColor }}>{tier}</span>
          </div>
        </div>
        <div className="text-xs text-[var(--ayci-ink-muted)] space-x-4">
          <span>Good <span className="metric-number font-medium text-[var(--ayci-ink)]">{formatValue(good, "currency")}</span></span>
          <span>Better <span className="metric-number font-medium text-[var(--ayci-ink)]">{formatValue(better, "currency")}</span></span>
          <span>Best <span className="metric-number font-medium text-[var(--ayci-ink)]">{formatValue(best, "currency")}</span></span>
        </div>
      </div>

      <div className="relative h-8 bg-slate-100 rounded-md overflow-visible">
        <div
          className="absolute inset-y-0 left-0 rounded-md transition-all duration-500"
          style={{
            width: `${pct}%`,
            background: "linear-gradient(90deg, #10B981 0%, #0EA5E9 50%, #F59E0B 100%)",
          }}
        />
        <TierTick label="Good" pct={goodPct} color="#10B981" />
        <TierTick label="Better" pct={betterPct} color="#0EA5E9" />
        <TierTick label="Best ★" pct={bestPct} color="#D97706" />
      </div>
    </div>
  );
}

function TierTick({ label, pct, color }) {
  return (
    <div className="absolute -top-1 -bottom-1" style={{ left: `${pct}%` }}>
      <div className="w-0.5 h-full" style={{ backgroundColor: color }} />
      <div
        className="absolute top-full mt-1 text-[10px] font-semibold whitespace-nowrap -translate-x-1/2"
        style={{ color }}
      >
        {label}
      </div>
    </div>
  );
}
