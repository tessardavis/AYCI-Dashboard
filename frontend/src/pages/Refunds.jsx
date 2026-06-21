/**
 * Refunds board — Coralie's view of every refund (sourced from Stripe via
 * Zapier) plus the reason/category/status she manages. Read+edit; the
 * underlying records are created by POST /api/refunds/ingest.
 */
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Loader2, RefreshCw, Search, Trash2, DownloadCloud } from "lucide-react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { readCache, writeCache } from "@/lib/swrCache";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";

const STATUSES = ["requested", "approved", "processed", "declined"];

// Coralie's reason taxonomy. Free-text under the hood, so this can grow
// without a migration — these are just the quick-pick options.
const CATEGORIES = [
  "Changed mind",
  "Dissatisfied / not as expected",
  "Duplicate / accidental",
  "Financial hardship",
  "Cooling-off / policy",
  "Wrong product / tier",
  "Chargeback / dispute",
  "Other",
];

const STATUS_STYLES = {
  requested: "bg-amber-100 text-amber-800",
  approved: "bg-sky-100 text-sky-800",
  processed: "bg-emerald-100 text-emerald-800",
  declined: "bg-slate-200 text-slate-600",
};

function fmtMoney(amount, currency) {
  if (amount == null || amount === "") return "—";
  const sym = (currency || "gbp").toLowerCase() === "gbp" ? "£"
    : (currency || "").toLowerCase() === "usd" ? "$"
    : (currency || "").toLowerCase() === "eur" ? "€" : "";
  return `${sym}${Number(amount).toFixed(2)}`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function Refunds() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  // Stale-while-revalidate: paint last-loaded board instantly, refresh in bg.
  const [rows, setRows] = useState(() => readCache("refunds")?.data?.items || []);
  const [summary, setSummary] = useState(() => readCache("refunds")?.data?.summary || null);
  const [loading, setLoading] = useState(() => !readCache("refunds"));
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [needsReasonOnly, setNeedsReasonOnly] = useState(false);
  const [backfilling, setBackfilling] = useState(false);

  const load = async (isRefresh) => {
    isRefresh ? setRefreshing(true) : setLoading(true);
    try {
      const [list, sum] = await Promise.all([
        apiClient.get("/refunds", { params: { limit: 5000 } }),
        apiClient.get("/refunds/summary"),
      ]);
      const items = list.data.items || [];
      const summaryData = sum.data || null;
      setRows(items);
      setSummary(summaryData);
      writeCache("refunds", { items, summary: summaryData });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load refunds");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // Cache hit → background refresh (keep showing cached rows); cold → blocking.
  useEffect(() => { load(readCache("refunds") != null); }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (statusFilter && (r.status || "processed") !== statusFilter) return false;
      if (categoryFilter && (r.reason_category || "") !== categoryFilter) return false;
      if (needsReasonOnly && (r.reason_category || "").trim()) return false;
      if (q) {
        const hay = `${r.student_name || ""} ${r.student_email || ""} ${r.reason_notes || ""} ${r.stripe_refund_id || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [rows, search, statusFilter, categoryFilter, needsReasonOnly]);

  const patchRefund = async (id, fields) => {
    // Optimistic — revert on failure.
    const before = rows.find((r) => r.id === id);
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...fields } : r)));
    try {
      await apiClient.patch(`/refunds/${id}`, fields);
      // Keep the summary chips honest after a category/status change.
      apiClient.get("/refunds/summary").then(({ data }) => setSummary(data)).catch(() => {});
    } catch (e) {
      setRows((prev) => prev.map((r) => (r.id === id ? before : r)));
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Update failed");
    }
  };

  const backfill = async () => {
    if (!window.confirm("Pull all historical refunds from Stripe into the board? This is safe to run repeatedly — it won't create duplicates.")) return;
    setBackfilling(true);
    try {
      const { data } = await apiClient.post("/refunds/backfill-from-stripe");
      toast.success(`Backfill done — ${data.created} new, ${data.updated} updated, ${data.matched_student} matched to a student (${data.fetched} from Stripe).`);
      await load(true);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Backfill failed");
    } finally {
      setBackfilling(false);
    }
  };

  const editNotes = (r) => {
    const next = window.prompt("Refund notes", r.reason_notes || "");
    if (next === null) return;
    patchRefund(r.id, { reason_notes: next.trim() || null });
  };

  const removeRefund = async (r) => {
    if (!window.confirm(`Delete this refund record for ${r.student_name || r.student_email || "this student"}? This only removes it from the board, not from Stripe.`)) return;
    try {
      await apiClient.delete(`/refunds/${r.id}`);
      setRows((prev) => prev.filter((x) => x.id !== r.id));
      toast.success("Refund deleted");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Delete failed");
    }
  };

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--ayci-ink)]">Refunds</h1>
          <p className="text-sm text-[var(--ayci-ink-muted)]">
            Sourced from Stripe. Add the reason &amp; status for each.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && (
            <button
              type="button"
              onClick={backfill}
              disabled={backfilling}
              className="text-sm flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--ayci-border)] hover:bg-slate-50 disabled:opacity-60"
              title="Pull all historical refunds from Stripe (idempotent)"
            >
              {backfilling ? <Loader2 className="w-4 h-4 animate-spin" /> : <DownloadCloud className="w-4 h-4" />}
              Backfill from Stripe
            </button>
          )}
          <button
            type="button"
            onClick={() => load(true)}
            className="text-sm flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--ayci-border)] hover:bg-slate-50"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
      </div>

      {/* Summary chips */}
      {summary && (
        <div className="flex flex-wrap gap-3 mb-4">
          <div className="bg-white border border-[var(--ayci-border)] rounded-lg px-4 py-2">
            <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">Total refunds</div>
            <div className="text-lg font-bold text-[var(--ayci-ink)]">{summary.total_count}</div>
          </div>
          <div className="bg-white border border-[var(--ayci-border)] rounded-lg px-4 py-2">
            <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">Total amount</div>
            <div className="text-lg font-bold text-[var(--ayci-ink)]">{fmtMoney(summary.total_amount, summary.currency)}</div>
          </div>
          {summary.needs_reason > 0 && (
            <button
              type="button"
              onClick={() => setNeedsReasonOnly((v) => !v)}
              className={`rounded-lg px-4 py-2 border text-left ${needsReasonOnly ? "bg-amber-50 border-amber-200" : "bg-white border-[var(--ayci-border)]"}`}
            >
              <div className="text-[10px] uppercase tracking-wider text-amber-700">Needs a reason</div>
              <div className="text-lg font-bold text-amber-800">{summary.needs_reason}</div>
            </button>
          )}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, email, notes…"
            className="pl-8 w-64"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-2 py-1.5 border border-slate-200 rounded text-sm bg-white"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="px-2 py-1.5 border border-slate-200 rounded text-sm bg-white"
        >
          <option value="">All reasons</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <span className="text-xs text-[var(--ayci-ink-muted)] ml-auto">
          {filtered.length} / {rows.length}
        </span>
      </div>

      {loading ? (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-12 text-center text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
          Loading…
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-12 text-center text-[var(--ayci-ink-muted)] italic">
          {rows.length === 0 ? "No refunds recorded yet." : "No refunds match the current filters."}
        </div>
      ) : (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] border-b border-[var(--ayci-border)]">
                <th className="px-3 py-2 font-semibold">Student</th>
                <th className="px-3 py-2 font-semibold">Tier</th>
                <th className="px-3 py-2 font-semibold">Cohort</th>
                <th className="px-3 py-2 font-semibold">Amount</th>
                <th className="px-3 py-2 font-semibold">Date</th>
                <th className="px-3 py-2 font-semibold">Reason</th>
                <th className="px-3 py-2 font-semibold">Notes</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 font-semibold w-10"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50/40 align-top">
                  <td className="px-3 py-2">
                    <div className="font-semibold text-[var(--ayci-ink)]">{r.student_name || "—"}</div>
                    <div className="text-[11px] text-[var(--ayci-ink-muted)]">{r.student_email || "—"}</div>
                  </td>
                  <td className="px-3 py-2 text-[12px]">{r.tier || "—"}</td>
                  <td className="px-3 py-2 text-[12px]">{r.cohort || "—"}</td>
                  <td className="px-3 py-2 text-[12px] font-semibold whitespace-nowrap">{fmtMoney(r.amount, r.currency)}</td>
                  <td className="px-3 py-2 text-[12px] whitespace-nowrap">{fmtDate(r.refunded_at)}</td>
                  <td className="px-3 py-2">
                    <select
                      value={CATEGORIES.includes(r.reason_category) ? r.reason_category : (r.reason_category ? "__other" : "")}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === "__other") {
                          const custom = window.prompt("Custom reason category", r.reason_category || "");
                          if (custom === null) return;
                          patchRefund(r.id, { reason_category: custom.trim() || null });
                        } else {
                          patchRefund(r.id, { reason_category: v || null });
                        }
                      }}
                      className={`text-[12px] px-1.5 py-1 border rounded bg-white ${(r.reason_category || "").trim() ? "border-slate-200" : "border-amber-300 bg-amber-50"}`}
                    >
                      <option value="">— set reason —</option>
                      {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                      {r.reason_category && !CATEGORIES.includes(r.reason_category) && (
                        <option value="__other">{r.reason_category} (custom)</option>
                      )}
                      <option value="__other">+ custom…</option>
                    </select>
                  </td>
                  <td className="px-3 py-2 text-[12px] max-w-[220px]">
                    <button
                      type="button"
                      onClick={() => editNotes(r)}
                      className="text-left hover:underline text-slate-600"
                      title="Click to edit notes"
                    >
                      {r.reason_notes ? r.reason_notes : <span className="text-slate-400 italic">add notes…</span>}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <select
                      value={r.status || "processed"}
                      onChange={(e) => patchRefund(r.id, { status: e.target.value })}
                      className={`text-[11px] font-semibold px-1.5 py-1 rounded border-0 ${STATUS_STYLES[r.status || "processed"] || "bg-slate-100"}`}
                    >
                      {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => removeRefund(r)}
                      className="text-slate-400 hover:text-rose-600"
                      title="Delete refund record"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
