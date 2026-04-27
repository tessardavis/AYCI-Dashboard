import { useEffect, useMemo, useState } from "react";
import { Loader2, AlertTriangle, RefreshCw, Search, ArrowUpDown, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import HeroBanner, { HERO_PRESETS } from "@/components/HeroBanner";

const fmtGbp = (v) =>
  `£${Number(v || 0).toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;

const RISK_TONE = {
  dormant: "bg-amber-50 text-amber-700 border-amber-200",
  never_logged_in: "bg-rose-50 text-rose-700 border-rose-200",
  no_circle_account: "bg-slate-100 text-slate-700 border-slate-200",
};

const RISK_LABEL = {
  dormant: "Dormant on Circle",
  never_logged_in: "Never logged in",
  no_circle_account: "No Circle account",
};

const fmtRelativeDays = (days) => {
  if (days === null || days === undefined) return "—";
  if (days === 0) return "Today";
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  if (days < 365) return `${Math.round(days / 30)} months ago`;
  return `${(days / 365).toFixed(1)}y ago`;
};

const fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "2-digit",
    });
  } catch {
    return "—";
  }
};

export default function StudentsAtRisk() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState(""); // search
  const [riskFilter, setRiskFilter] = useState("all");
  const [sortKey, setSortKey] = useState("lifetime_gbp"); // lifetime_gbp | days_dormant | name
  const [sortDir, setSortDir] = useState("desc");

  const fetchData = async (refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    try {
      const { data } = await apiClient.get("/students/at-risk", {
        params: refresh ? { refresh: true } : {},
        timeout: 30000,
      });
      setData(data);
      if (refresh) {
        if (data.computing) {
          toast("Refresh queued — full Stripe scan takes 3–5 min. Reload soon.");
        } else {
          toast.success("At-risk list refreshed");
        }
      }
    } catch (err) {
      toast.error(
        formatApiErrorDetail(err.response?.data?.detail) || "Failed to load at-risk list",
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData(false);
  }, []);

  const filtered = useMemo(() => {
    if (!data?.students) return [];
    let rows = [...data.students];
    if (riskFilter !== "all") {
      rows = rows.filter((s) => s.risk_status === riskFilter);
    }
    if (filter.trim()) {
      const q = filter.toLowerCase();
      rows = rows.filter(
        (s) =>
          (s.name || "").toLowerCase().includes(q) ||
          (s.email || "").toLowerCase().includes(q),
      );
    }
    rows.sort((a, b) => {
      let av = a[sortKey];
      let bv = b[sortKey];
      if (sortKey === "name") {
        av = (a.name || a.email || "").toLowerCase();
        bv = (b.name || b.email || "").toLowerCase();
      }
      if (av === null || av === undefined) av = sortDir === "asc" ? Infinity : -Infinity;
      if (bv === null || bv === undefined) bv = sortDir === "asc" ? Infinity : -Infinity;
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return rows;
  }, [data, filter, riskFilter, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  };

  if (loading) {
    return (
      <div className="p-8" data-testid="at-risk-page">
        <div className="flex items-center gap-2 text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading at-risk list…
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6" data-testid="at-risk-page">
      <HeroBanner
        {...HERO_PRESETS.at_risk}
        eyebrow="Retention"
        title="Students at risk"
        subtitle={`High-spend students (lifetime spend ≥ ${fmtGbp(data?.min_spend_gbp || 1000)} over the last 365 days) who haven't been on Circle in the last ${data?.dormant_days || 30} days, or never logged in.`}
        testid="at-risk-hero"
        actions={
          <button
            onClick={() => fetchData(true)}
            disabled={refreshing}
            className="text-sm bg-white/95 border border-white/20 rounded-lg px-4 py-2 hover:bg-white disabled:opacity-50 flex items-center gap-2 h-10 text-[var(--ayci-ink)]"
            data-testid="at-risk-refresh-btn"
          >
            {refreshing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            Refresh
          </button>
        }
      />

      {data?.computing && (
        <div
          className="bg-sky-50 border border-sky-200 rounded-lg p-4 text-sm text-sky-800"
          data-testid="at-risk-computing-banner"
        >
          <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
          First-time scan in progress. This pulls a year of Stripe charges and takes
          ~3–5 minutes. Refresh this page in a few minutes.
        </div>
      )}

      {data?.stale && !data?.computing && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800">
          Showing stale cache — a refresh is running in the background.
        </div>
      )}

      {/* Summary tiles */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <SummaryTile
          label="Total at risk"
          value={data?.total_at_risk || 0}
          tone="rose"
          testid="at-risk-tile-total"
        />
        <SummaryTile
          label="Dormant > 30 days"
          value={data?.counts?.dormant || 0}
          tone="amber"
          testid="at-risk-tile-dormant"
        />
        <SummaryTile
          label="Never logged in"
          value={data?.counts?.never_logged_in || 0}
          tone="rose"
          testid="at-risk-tile-never"
        />
        <SummaryTile
          label="No Circle account"
          value={data?.counts?.no_circle_account || 0}
          tone="slate"
          testid="at-risk-tile-no-account"
        />
      </div>

      {/* Filters */}
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--ayci-ink-muted)]" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search name or email…"
            className="w-full pl-9 pr-3 py-2 text-sm border border-[var(--ayci-border)] rounded-md focus:outline-none focus:border-[var(--ayci-teal)]"
            data-testid="at-risk-search-input"
          />
        </div>
        <div className="flex items-center gap-1 text-xs">
          {[
            { id: "all", label: "All" },
            { id: "dormant", label: "Dormant" },
            { id: "never_logged_in", label: "Never logged in" },
            { id: "no_circle_account", label: "No account" },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => setRiskFilter(t.id)}
              className={`px-3 py-1.5 rounded-md border transition-colors ${
                riskFilter === t.id
                  ? "bg-[var(--ayci-teal)] text-white border-[var(--ayci-teal)]"
                  : "bg-white border-[var(--ayci-border)] hover:bg-slate-50"
              }`}
              data-testid={`at-risk-filter-${t.id}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg overflow-hidden">
        <table className="w-full text-sm" data-testid="at-risk-table">
          <thead className="bg-slate-50 border-b border-[var(--ayci-border)]">
            <tr className="text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
              <th className="text-left p-3">
                <button
                  onClick={() => toggleSort("name")}
                  className="flex items-center gap-1 hover:text-[var(--ayci-ink)]"
                >
                  Student <ArrowUpDown className="w-3 h-3" />
                </button>
              </th>
              <th className="text-right p-3">
                <button
                  onClick={() => toggleSort("lifetime_gbp")}
                  className="flex items-center gap-1 hover:text-[var(--ayci-ink)] ml-auto"
                >
                  Lifetime <ArrowUpDown className="w-3 h-3" />
                </button>
              </th>
              <th className="text-left p-3">Last Stripe</th>
              <th className="text-left p-3">
                <button
                  onClick={() => toggleSort("days_dormant")}
                  className="flex items-center gap-1 hover:text-[var(--ayci-ink)]"
                >
                  Last on Circle <ArrowUpDown className="w-3 h-3" />
                </button>
              </th>
              <th className="text-left p-3">Risk</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="p-8 text-center text-[var(--ayci-ink-muted)] italic"
                >
                  {data?.total_at_risk === 0
                    ? "Nobody at risk right now — nice."
                    : "No students match these filters."}
                </td>
              </tr>
            )}
            {filtered.map((s) => (
              <tr
                key={s.stripe_customer_id}
                className="border-b border-[var(--ayci-border)] last:border-b-0 hover:bg-slate-50 transition-colors"
                data-testid={`at-risk-row-${s.stripe_customer_id}`}
              >
                <td className="p-3">
                  <div className="flex items-center gap-2">
                    {s.circle_avatar_url ? (
                      <img
                        src={s.circle_avatar_url}
                        alt=""
                        className="w-7 h-7 rounded-full object-cover bg-slate-200"
                      />
                    ) : (
                      <div className="w-7 h-7 rounded-full bg-slate-200 text-[10px] flex items-center justify-center text-slate-500 font-bold">
                        {(s.name || s.email || "?").slice(0, 1).toUpperCase()}
                      </div>
                    )}
                    <div>
                      <div className="font-medium text-[var(--ayci-ink)]">
                        {s.name || "—"}
                      </div>
                      <div className="text-xs text-[var(--ayci-ink-muted)]">
                        {s.email || "—"}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="p-3 text-right font-display font-bold text-[var(--ayci-ink)]">
                  {fmtGbp(s.lifetime_gbp)}
                  <div className="text-[10px] font-normal text-[var(--ayci-ink-muted)]">
                    {s.charge_count} charge{s.charge_count !== 1 ? "s" : ""}
                  </div>
                </td>
                <td className="p-3 text-xs text-[var(--ayci-ink-muted)]">
                  {fmtDate(s.last_charge_at)}
                </td>
                <td className="p-3 text-xs text-[var(--ayci-ink-muted)]">
                  {s.circle_last_seen_at ? (
                    <>
                      {fmtRelativeDays(s.days_dormant)}
                      <div className="text-[10px]">{fmtDate(s.circle_last_seen_at)}</div>
                    </>
                  ) : (
                    <span className="italic">—</span>
                  )}
                </td>
                <td className="p-3">
                  <span
                    className={`inline-block text-[10px] uppercase tracking-wider font-bold px-2 py-1 rounded-full border ${RISK_TONE[s.risk_status]}`}
                  >
                    {RISK_LABEL[s.risk_status] || s.risk_status}
                  </span>
                </td>
                <td className="p-3 text-right">
                  {s.email && (
                    <Link
                      to={`/students?email=${encodeURIComponent(s.email)}`}
                      className="text-xs text-[var(--ayci-teal)] hover:underline inline-flex items-center gap-1"
                      data-testid={`at-risk-row-lookup-${s.stripe_customer_id}`}
                    >
                      Open <ExternalLink className="w-3 h-3" />
                    </Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-[var(--ayci-ink-muted)]">
        Refreshed:{" "}
        {data?.computed_at
          ? new Date(data.computed_at).toLocaleString("en-GB")
          : "—"}{" "}
        · Cached for {24} h · Auto-refresh daily at 05:15 London.
      </div>
    </div>
  );
}

function SummaryTile({ label, value, tone, testid }) {
  const TONES = {
    rose: "bg-rose-50 text-rose-700 border-rose-200",
    amber: "bg-amber-50 text-amber-700 border-amber-200",
    slate: "bg-slate-50 text-slate-700 border-slate-200",
  };
  return (
    <div
      className={`border rounded-lg p-4 ${TONES[tone] || TONES.slate}`}
      data-testid={testid}
    >
      <div className="text-[10px] uppercase tracking-wider opacity-80">{label}</div>
      <div className="font-display font-bold text-3xl mt-1">{value}</div>
    </div>
  );
}
