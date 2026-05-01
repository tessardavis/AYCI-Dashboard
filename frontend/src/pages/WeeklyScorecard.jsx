import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { formatValue, lastNWeekStarts, formatWeekLabel, isOnTrack } from "@/lib/format";
import PageHeader from "@/components/PageHeader";
import Sparkline from "@/components/Sparkline";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Filter, X, RefreshCw, Download, ChevronDown } from "lucide-react";
import MobileScorecard from "@/components/MobileScorecard";
import PulseCard from "@/components/PulseCard";

const CATEGORY_ORDER = [
  "GROWTH + INTEREST",
  "CONVERSION + INTENT",
  "REVENUE",
  "SOCIAL PROOF",
  "DELIVERY + OPERATIONS",
];

const WEEKS_VISIBLE = 13;

export default function WeeklyScorecard() {
  const { user } = useAuth();
  const [metrics, setMetrics] = useState([]);
  const [team, setTeam] = useState([]);
  const [values, setValues] = useState([]); // all weekly_values
  const [loading, setLoading] = useState(true);
  const [filterOwnerId, setFilterOwnerId] = useState(null);
  const [editingCell, setEditingCell] = useState(null); // { metric_id, week_start }
  const [editingValue, setEditingValue] = useState("");
  const [syncing, setSyncing] = useState(false);

  // Weeks oldest → newest (left to right) — newest is right-most
  const weeks = useMemo(() => lastNWeekStarts(WEEKS_VISIBLE), []);
  const latestWeek = weeks[weeks.length - 1];
  const teamById = useMemo(() => {
    const m = {};
    team.forEach((t) => (m[t.id] = t));
    return m;
  }, [team]);

  const valueMap = useMemo(() => {
    const map = {};
    values.forEach((v) => {
      map[`${v.metric_id}|${v.week_start}`] = v.value;
    });
    return map;
  }, [values]);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [m, t, wv] = await Promise.all([
        apiClient.get("/metrics"),
        apiClient.get("/team"),
        apiClient.get("/weekly-values"),
      ]);
      setMetrics(m.data);
      setTeam(t.data);
      setValues(wv.data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const filteredMetrics = useMemo(() => {
    // Hide cohort-only metrics from the weekly view
    let xs = metrics.filter((m) => !m.cohort_only);
    if (filterOwnerId) {
      xs = xs.filter((m) => (m.owner_ids || []).includes(filterOwnerId));
    }
    return xs;
  }, [metrics, filterOwnerId]);

  const grouped = useMemo(() => {
    const g = {};
    CATEGORY_ORDER.forEach((c) => (g[c] = []));
    filteredMetrics.forEach((m) => {
      if (!g[m.category]) g[m.category] = [];
      g[m.category].push(m);
    });
    return g;
  }, [filteredMetrics]);

  // Summary: count of metrics on-track for latest week
  const summary = useMemo(() => {
    const withValue = metrics.filter(
      (m) => valueMap[`${m.id}|${latestWeek}`] !== undefined
    );
    const onTrack = withValue.filter((m) =>
      isOnTrack(valueMap[`${m.id}|${latestWeek}`], m.goal, m.goal_direction)
    ).length;
    return { total: metrics.length, withValue: withValue.length, onTrack };
  }, [metrics, valueMap, latestWeek]);

  const startEdit = (metric, week) => {
    setEditingCell({ metric_id: metric.id, week_start: week });
    const existing = valueMap[`${metric.id}|${week}`];
    setEditingValue(existing !== undefined ? String(existing) : "");
  };

  const commitEdit = async () => {
    if (!editingCell) return;
    const { metric_id, week_start } = editingCell;
    const raw = editingValue.trim();
    if (raw === "") {
      setEditingCell(null);
      return;
    }
    const num = Number(raw.replace(/[£,%,\s]/g, ""));
    if (Number.isNaN(num)) {
      toast.error("Please enter a valid number");
      setEditingCell(null);
      return;
    }
    try {
      const { data } = await apiClient.post("/weekly-values", {
        metric_id,
        week_start,
        value: num,
      });
      setValues((prev) => {
        const idx = prev.findIndex(
          (v) => v.metric_id === metric_id && v.week_start === week_start
        );
        if (idx >= 0) {
          const next = prev.slice();
          next[idx] = { ...next[idx], value: num };
          return next;
        }
        return [...prev, data];
      });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setEditingCell(null);
    }
  };

  const onCellKey = (e) => {
    if (e.key === "Enter") commitEdit();
    if (e.key === "Escape") setEditingCell(null);
  };

  const cellClass = (value, goal, direction) => {
    const track = isOnTrack(value, goal, direction);
    if (track === null) return "";
    return track ? "bg-[var(--ayci-success-bg)] text-[var(--ayci-success-ink)]" : "bg-[var(--ayci-danger-bg)] text-[var(--ayci-danger-ink)]";
  };

  const onTrackPct = summary.withValue === 0 ? 0 : Math.round((summary.onTrack / summary.withValue) * 100);

  const [autoFilling, setAutoFilling] = useState(false);
  const runAutoFill = async () => {
    setAutoFilling(true);
    try {
      const { data } = await apiClient.get(`/scorecard/auto-compute?week_start=${latestWeek}`, { timeout: 90000 });
      const computeMap = data.metrics || {};
      // Map from name → metric id
      const byName = {};
      metrics.forEach((m) => {
        byName[m.name.toLowerCase()] = m;
      });
      let written = 0;
      const errors = [];
      // Write each computed value if metric exists and value is numeric
      const writes = [];
      for (const [name, payload] of Object.entries(computeMap)) {
        const metric = byName[name];
        if (!metric || payload.value == null || payload.error) continue;
        writes.push(
          apiClient
            .post(`/weekly-values`, {
              metric_id: metric.id,
              week_start: latestWeek,
              value: Number(payload.value),
            })
            .then(() => { written += 1; })
            .catch((err) => errors.push({ name, msg: err?.response?.data?.detail || err.message })),
        );
      }
      await Promise.all(writes);
      await loadAll();
      if (written > 0) toast.success(`Auto-filled ${written} metric${written === 1 ? "" : "s"} for week of ${latestWeek}`);
      if (errors.length > 0) toast.error(`${errors.length} failed`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setAutoFilling(false);
    }
  };

  const runSync = async (overwrite = false) => {
    setSyncing(true);
    try {
      const { data } = await apiClient.post("/sync/run", { overwrite });
      await loadAll();
      const written = data.results.filter((r) => r.written).length;
      const errors = data.results.filter((r) => r.error);
      if (written > 0) toast.success(`Synced ${written} metric${written === 1 ? "" : "s"} from external sources`);
      if (errors.length > 0) {
        toast.error(
          `${errors.length} metric${errors.length === 1 ? "" : "s"} failed: ${errors.slice(0, 2).map((e) => e.name).join(", ")}`
        );
      }
      if (written === 0 && errors.length === 0) {
        toast.info("No connected sources yet — configure them in Settings → Metrics");
      }
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 lg:p-12 ayci-fade-up">
      <PageHeader
        eyebrow="Monday Scorecard"
        title="Weekly Scorecard"
        description="The numbers your team reviews every Monday. Click a cell to enter this week's values."
        right={
          <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
            <button
              onClick={runAutoFill}
              disabled={autoFilling || loading}
              data-testid="scorecard-autofill-btn"
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md border border-[var(--ayci-border)] bg-white text-sm font-medium hover:border-[var(--ayci-accent)] hover:text-[var(--ayci-accent)] transition-colors disabled:opacity-50"
              title="Auto-compute the 6 supported metrics from Calendly, Circle, Tally and Monday for the current week"
            >
              <RefreshCw className={"w-4 h-4 " + (autoFilling ? "animate-spin" : "")} />
              {autoFilling ? "Computing…" : "Auto-fill week"}
            </button>
            <button
              onClick={() => runSync(false)}
              disabled={syncing}
              data-testid="scorecard-sync-btn"
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md border border-[var(--ayci-border)] bg-white text-sm font-medium hover:border-[var(--ayci-accent)] hover:text-[var(--ayci-accent)] transition-colors disabled:opacity-50"
              title="Pull weekly values from configured external sources"
            >
              <RefreshCw className={"w-4 h-4 " + (syncing ? "animate-spin" : "")} />
              {syncing ? "Syncing…" : "Sync"}
            </button>
            <CsvExportButton apiBase={apiClient.defaults.baseURL} />
            <SummaryRing onTrack={summary.onTrack} total={summary.withValue} pct={onTrackPct} />
          </div>
        }
      />

      <PulseCard />

      {/* Owner filter — desktop chip row (hidden on mobile, replaced by dropdown) */}
      <div className="hidden sm:flex items-center gap-2 mb-5 flex-wrap">
        <span className="text-xs text-[var(--ayci-ink-muted)] flex items-center gap-1.5">
          <Filter className="w-3.5 h-3.5" /> Filter by owner:
        </span>
        {filterOwnerId && (
          <button
            onClick={() => setFilterOwnerId(null)}
            data-testid="scorecard-clear-filter"
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-[var(--ayci-accent)] text-white hover:opacity-90"
          >
            {teamById[filterOwnerId]?.name || "—"}
            <X className="w-3 h-3" />
          </button>
        )}
        {!filterOwnerId &&
          team.map((t) => (
            <button
              key={t.id}
              onClick={() => setFilterOwnerId(t.id)}
              data-testid={`scorecard-filter-${t.id}`}
              className="text-xs px-2.5 py-1 rounded-full border border-[var(--ayci-border)] bg-white hover:border-[var(--ayci-accent)] hover:text-[var(--ayci-accent)] transition-colors"
            >
              {t.name}
            </button>
          ))}
      </div>

      {loading ? (
        <div className="text-sm text-[var(--ayci-ink-muted)]">Loading…</div>
      ) : (
        <div className="hidden sm:block bg-white rounded-lg border border-[var(--ayci-border)] shadow-sm overflow-hidden">
          <div className="overflow-x-auto ayci-scroll" data-testid="scorecard-table-wrapper">
            <table className="min-w-full text-sm border-collapse">
              <thead>
                <tr className="bg-slate-50 border-b border-[var(--ayci-border)]">
                  <th className="sticky left-0 z-20 bg-slate-50 text-left px-4 py-3 font-medium text-[var(--ayci-ink-muted)] min-w-[240px] border-r border-[var(--ayci-border)]">
                    Metric
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-[var(--ayci-ink-muted)] min-w-[120px]">Owner</th>
                  <th className="text-right px-4 py-3 font-medium text-[var(--ayci-ink-muted)] min-w-[90px]">Goal</th>
                  <th className="text-center px-3 py-3 font-medium text-[var(--ayci-ink-muted)] min-w-[90px]">Trend</th>
                  {weeks.map((w) => (
                    <th
                      key={w}
                      className={
                        "px-3 py-3 text-right font-medium text-[var(--ayci-ink-muted)] min-w-[92px] " +
                        (w === latestWeek ? "bg-slate-100" : "")
                      }
                    >
                      <div className="text-[11px] uppercase tracking-wider">w/c</div>
                      <div className="text-[12px] text-[var(--ayci-ink)]">{formatWeekLabel(w)}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {CATEGORY_ORDER.map((cat) => {
                  const items = grouped[cat] || [];
                  if (items.length === 0) return null;
                  return (
                    <Fragment key={cat}>
                      <tr className="bg-[var(--ayci-sidebar)]">
                        <td
                          colSpan={4 + weeks.length}
                          className="sticky left-0 px-4 py-2 text-[11px] uppercase tracking-[0.2em] text-white font-display font-semibold"
                        >
                          {cat}
                        </td>
                      </tr>
                      {items.map((m) => {
                        const owners = (m.owner_ids || [])
                          .map((id) => teamById[id])
                          .filter(Boolean);
                        // Trend = last 8 completed weeks (weeks[0] is already the most recent completed week)
                        const trendData = weeks.slice(0, 8).reverse().map((w) => {
                          const v = valueMap[`${m.id}|${w}`];
                          return v === undefined ? null : Number(v);
                        });
                        const cleanTrend = trendData.filter((v) => v !== null);
                        return (
                          <tr
                            key={m.id}
                            className="border-b border-[var(--ayci-border)] hover:bg-slate-50/50 group"
                            data-testid={`scorecard-row-${m.id}`}
                          >
                            <td className="sticky left-0 z-10 bg-white group-hover:bg-slate-50 px-4 py-3 font-medium text-[var(--ayci-ink)] border-r border-[var(--ayci-border)]">
                              {m.name}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex -space-x-2">
                                {owners.map((o) => (
                                  <button
                                    key={o.id}
                                    onClick={() => setFilterOwnerId(o.id)}
                                    title={o.name}
                                    data-testid={`scorecard-owner-${o.id}`}
                                  >
                                    <Avatar className="w-6 h-6 border-2 border-white">
                                      {o.avatar_url && <AvatarImage src={o.avatar_url} alt={o.name} />}
                                      <AvatarFallback className="text-[10px] bg-slate-200 text-slate-700">
                                        {o.name
                                          .split(" ")
                                          .map((p) => p[0])
                                          .slice(0, 2)
                                          .join("")}
                                      </AvatarFallback>
                                    </Avatar>
                                  </button>
                                ))}
                              </div>
                            </td>
                            <td className="px-4 py-3 text-right metric-number font-semibold text-[var(--ayci-ink)]">
                              {m.goal == null ? (
                                <span className="text-[var(--ayci-ink-muted)] font-normal text-xs italic">No target</span>
                              ) : (
                                formatValue(m.goal, m.format)
                              )}
                            </td>
                            <td className="px-3 py-3">
                              <div className="flex justify-center">
                                <Sparkline data={cleanTrend} />
                              </div>
                            </td>
                            {weeks.map((w) => {
                              const key = `${m.id}|${w}`;
                              const v = valueMap[key];
                              const isEditing =
                                editingCell &&
                                editingCell.metric_id === m.id &&
                                editingCell.week_start === w;
                              const highlight = w === latestWeek;
                              return (
                                <td
                                  key={w}
                                  className={
                                    "px-2 py-2 text-right tabular-nums " +
                                    cellClass(v, m.goal, m.goal_direction) +
                                    (highlight ? " border-l border-slate-200" : "")
                                  }
                                  onClick={() => !isEditing && startEdit(m, w)}
                                  data-testid={`cell-${m.id}-${w}`}
                                >
                                  {isEditing ? (
                                    <input
                                      autoFocus
                                      type="text"
                                      value={editingValue}
                                      onChange={(e) => setEditingValue(e.target.value)}
                                      onBlur={commitEdit}
                                      onKeyDown={onCellKey}
                                      className="w-full px-1 py-1 text-right bg-white border border-[var(--ayci-accent)] rounded outline-none metric-number"
                                      data-testid={`cell-input-${m.id}-${w}`}
                                    />
                                  ) : (
                                    <span className="metric-number font-medium cursor-text">
                                      {v === undefined ? (
                                        <span className="text-slate-300">—</span>
                                      ) : (
                                        formatValue(v, m.format)
                                      )}
                                    </span>
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Mobile-only card view (hidden on sm and up) */}
      <MobileScorecard
        grouped={grouped}
        weeks={weeks}
        valueMap={valueMap}
        teamById={teamById}
        team={team}
        filterOwnerId={filterOwnerId}
        setFilterOwnerId={setFilterOwnerId}
        startEdit={startEdit}
        editingCell={editingCell}
        editingValue={editingValue}
        setEditingValue={setEditingValue}
        commitEdit={commitEdit}
        onCellKey={onCellKey}
        loading={loading}
        CATEGORY_ORDER={CATEGORY_ORDER}
      />
    </div>
  );
}

function SummaryRing({ onTrack, total, pct }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const offset = c - (pct / 100) * c;
  return (
    <div
      className="flex items-center gap-4 bg-white border border-[var(--ayci-border)] rounded-lg px-5 py-4 shadow-sm"
      data-testid="scorecard-summary"
    >
      <div className="relative w-[68px] h-[68px] shrink-0">
        <svg width="68" height="68" className="-rotate-90">
          <circle cx="34" cy="34" r={r} stroke="#E2E8F0" strokeWidth="6" fill="none" />
          <circle
            cx="34"
            cy="34"
            r={r}
            stroke="var(--ayci-accent)"
            strokeWidth="6"
            fill="none"
            strokeDasharray={c}
            strokeDashoffset={offset}
            strokeLinecap="round"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="metric-number text-sm font-bold text-[var(--ayci-ink)]">{pct}%</span>
        </div>
      </div>
      <div className="leading-tight">
        <div className="font-display text-2xl font-bold metric-number text-[var(--ayci-ink)]">
          {onTrack}
          <span className="text-[var(--ayci-ink-muted)] font-normal"> / {total}</span>
        </div>
        <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">on track this week</div>
      </div>
    </div>
  );
}


function CsvExportButton({ apiBase }) {
  const [open, setOpen] = useState(false);
  const download = (scope) => {
    setOpen(false);
    // Use a same-origin auth-cookie GET via a hidden iframe so the file
    // download inherits the httpOnly access_token cookie. Anchor + click
    // works for cookie-authenticated downloads in Chrome/Safari/Firefox.
    const url =
      `${apiBase}/scorecard/export.csv?scope=${scope}` +
      (scope === "recent" ? "&weeks=8" : "");
    const a = document.createElement("a");
    a.href = url;
    a.rel = "noopener";
    a.click();
  };
  return (
    <div className="relative" data-testid="scorecard-csv-export">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md border border-[var(--ayci-border)] bg-white text-sm font-medium hover:border-[var(--ayci-accent)] hover:text-[var(--ayci-accent)] transition-colors"
        data-testid="scorecard-csv-btn"
        title="Export the scorecard as CSV"
      >
        <Download className="w-4 h-4" />
        CSV
        <ChevronDown className="w-3.5 h-3.5" />
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
            aria-hidden
          />
          <div
            className="absolute right-0 mt-1 w-52 bg-white border border-[var(--ayci-border)] rounded-md shadow-lg z-20 overflow-hidden"
            data-testid="scorecard-csv-menu"
          >
            <button
              onClick={() => download("recent")}
              className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50"
              data-testid="scorecard-csv-recent"
            >
              Last 8 weeks
              <div className="text-[10px] text-[var(--ayci-ink-muted)]">
                Current view
              </div>
            </button>
            <div className="border-t border-[var(--ayci-border)]" />
            <button
              onClick={() => download("year")}
              className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50"
              data-testid="scorecard-csv-year"
            >
              Full archive
              <div className="text-[10px] text-[var(--ayci-ink-muted)]">
                All weeks of the year
              </div>
            </button>
          </div>
        </>
      )}
    </div>
  );
}

