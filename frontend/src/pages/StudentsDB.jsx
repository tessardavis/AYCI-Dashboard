/* Students (academy_members mirror) — the editable replacement for the
 * Monday Academy Members board.
 *
 * Reads from db.academy_members which is kept fresh by the 15-min Monday
 * sync. Edits write back to the same row and pin the changed fields so
 * the next sync doesn't overwrite (see dashboard_edited_fields in the
 * backend).
 */
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Loader2, Search, X, Save, RefreshCw } from "lucide-react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const EDITABLE_FIELDS = [
  { key: "name",           label: "Name" },
  { key: "first_name",     label: "First name" },
  { key: "surname",        label: "Surname" },
  { key: "email",          label: "Email" },
  { key: "circle_email",   label: "Circle email" },
  { key: "tier",           label: "Tier" },
  { key: "cohort_joined",  label: "Cohort joined" },
  { key: "interview_date", label: "Interview date" },
  { key: "speciality",     label: "Speciality" },
  { key: "hospital",       label: "Hospital" },
  { key: "interview_type", label: "Interview type" },
  { key: "private_chat_url", label: "Private chat URL" },
  { key: "video_allowance", label: "Video allowance", type: "number" },
];

function formatDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return iso;
  }
}

export default function StudentsDB() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [tierFilter, setTierFilter] = useState("");
  const [cohortFilter, setCohortFilter] = useState("");
  const [hasInterviewOnly, setHasInterviewOnly] = useState(false);
  const [needsSetupOnly, setNeedsSetupOnly] = useState(false);
  const [mismatchOnly, setMismatchOnly] = useState(false);
  const [visibleCount, setVisibleCount] = useState(100);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    setRefreshing(true);
    try {
      const { data } = await apiClient.get("/students-db", { params: { limit: 10000 } });
      setRows(data.items || []);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load students");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Derive filter dropdown options from the loaded data
  const { tierOptions, cohortOptions } = useMemo(() => {
    const tiers = new Set();
    const cohorts = new Set();
    for (const r of rows) {
      if (r.tier) tiers.add(r.tier);
      if (r.cohort_joined) cohorts.add(r.cohort_joined);
    }
    return {
      tierOptions: [...tiers].sort(),
      cohortOptions: [...cohorts].sort(),
    };
  }, [rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (tierFilter && r.tier !== tierFilter) return false;
      if (cohortFilter && r.cohort_joined !== cohortFilter) return false;
      if (hasInterviewOnly && !r.interview_date) return false;
      if (needsSetupOnly && !r.needs_setup) return false;
      if (mismatchOnly && r.allowance_flag !== "mismatch") return false;
      if (q) {
        const hay = `${r.name || ""} ${r.email || ""} ${r.first_name || ""} ${r.surname || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [rows, search, tierFilter, cohortFilter, hasInterviewOnly, needsSetupOnly, mismatchOnly]);

  // Reset the visible window whenever the filter/search changes, so a new
  // query shows from the top (and keeps the DOM light).
  useEffect(() => { setVisibleCount(100); }, [search, tierFilter, cohortFilter, hasInterviewOnly, needsSetupOnly, mismatchOnly]);

  const needsSetupCount = useMemo(() => rows.filter((r) => r.needs_setup).length, [rows]);
  const allowanceMissing = useMemo(() => rows.filter((r) => r.allowance_flag === "missing").length, [rows]);
  const allowanceMismatch = useMemo(() => rows.filter((r) => r.allowance_flag === "mismatch").length, [rows]);
  const [applyingAllow, setApplyingAllow] = useState(false);

  const applyAllowances = async () => {
    if (!window.confirm(`Set the expected video allowance on ${allowanceMissing} student(s) who are missing it? (Mismatches are left for you to review.)`)) return;
    setApplyingAllow(true);
    try {
      const { data } = await apiClient.post("/students-db/apply-expected-allowances");
      toast.success(`Set allowance on ${data.set} student${data.set === 1 ? "" : "s"}`);
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to apply allowances");
    } finally {
      setApplyingAllow(false);
    }
  };

  const [revertingAllow, setRevertingAllow] = useState(false);
  const revertAllowances = async () => {
    if (!window.confirm("Undo the recent allowance fill? This clears the auto-set allowances back to empty (only the ones you just applied).")) return;
    setRevertingAllow(true);
    try {
      const { data } = await apiClient.post("/students-db/revert-applied-allowances");
      toast.success(`Reverted ${data.reverted} allowance${data.reverted === 1 ? "" : "s"} back to empty`);
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to undo");
    } finally {
      setRevertingAllow(false);
    }
  };

  const onSaved = (updated) => {
    setRows((prev) => prev.map((r) => (r._id === updated._id ? { ...r, ...updated } : r)));
    setEditing(null);
    toast.success("Saved");
  };

  return (
    <div className="p-4 lg:p-10 max-w-[1700px] mx-auto">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div>
          <h1 className="font-display text-2xl lg:text-3xl font-extrabold tracking-tight text-[var(--ayci-ink)]">
            Students
          </h1>
          <p className="text-xs text-[var(--ayci-ink-muted)] mt-1">
            Editable copy of the Academy Members board. Edits made here override the 15-min Monday sync.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {allowanceMissing > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={applyAllowances}
              disabled={applyingAllow}
              className="border-amber-300 text-amber-800 hover:bg-amber-50"
              title="Set the expected video allowance on students who are missing it"
            >
              {applyingAllow ? <Loader2 className="w-4 h-4 animate-spin" /> : <span>⚡</span>}
              <span className="ml-2">Set {allowanceMissing} missing allowance{allowanceMissing === 1 ? "" : "s"}</span>
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={revertAllowances}
            disabled={revertingAllow}
            title="Undo a recent 'set missing allowances' — clears the just-applied allowances back to empty"
          >
            {revertingAllow ? <Loader2 className="w-4 h-4 animate-spin" /> : <span>↩</span>}
            <span className="ml-2">Undo allowance fill</span>
          </Button>
          <Button variant="outline" size="sm" onClick={load} disabled={refreshing}>
            {refreshing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            <span className="ml-2">Refresh</span>
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--ayci-ink-muted)]" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name or email…"
            className="pl-8"
          />
        </div>
        <select
          value={tierFilter}
          onChange={(e) => setTierFilter(e.target.value)}
          className="px-2 py-1.5 border border-slate-200 rounded text-sm bg-white"
        >
          <option value="">All tiers</option>
          {tierOptions.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select
          value={cohortFilter}
          onChange={(e) => setCohortFilter(e.target.value)}
          className="px-2 py-1.5 border border-slate-200 rounded text-sm bg-white"
        >
          <option value="">All cohorts</option>
          {cohortOptions.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <label className="text-xs text-[var(--ayci-ink-muted)] flex items-center gap-1.5 px-2 py-1.5">
          <input
            type="checkbox"
            checked={hasInterviewOnly}
            onChange={(e) => setHasInterviewOnly(e.target.checked)}
          />
          Has interview date
        </label>
        <label
          className={`text-xs flex items-center gap-1.5 px-2 py-1.5 rounded ${needsSetupOnly ? "bg-amber-50 text-amber-800" : "text-[var(--ayci-ink-muted)]"}`}
          title="Private-tier or Boost & Go students with no private chat link yet"
        >
          <input
            type="checkbox"
            checked={needsSetupOnly}
            onChange={(e) => setNeedsSetupOnly(e.target.checked)}
          />
          ⚠ Needs setup{needsSetupCount ? ` (${needsSetupCount})` : ""}
        </label>
        {allowanceMismatch > 0 && (
          <label className={`text-xs flex items-center gap-1.5 px-2 py-1.5 rounded ${mismatchOnly ? "bg-red-50 text-red-700" : "text-[var(--ayci-ink-muted)]"}`}
                 title="Students whose video allowance differs from the expected value — review each">
            <input type="checkbox" checked={mismatchOnly} onChange={(e) => setMismatchOnly(e.target.checked)} />
            Allowance mismatch ({allowanceMismatch})
          </label>
        )}
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
          No students match the current filters.
        </div>
      ) : (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] border-b border-[var(--ayci-border)]">
                <th className="px-3 py-2 font-semibold">Name</th>
                <th className="px-3 py-2 font-semibold">Email</th>
                <th className="px-3 py-2 font-semibold">Tier</th>
                <th className="px-3 py-2 font-semibold">Cohort</th>
                <th className="px-3 py-2 font-semibold">Interview</th>
                <th className="px-3 py-2 font-semibold">Speciality</th>
                <th className="px-3 py-2 font-semibold">Videos</th>
                <th className="px-3 py-2 font-semibold w-16"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, visibleCount).map((r) => (
                <tr
                  key={r._id}
                  className="border-b border-slate-100 hover:bg-slate-50/40 cursor-pointer"
                  onClick={() => setEditing(r)}
                >
                  <td className="px-3 py-2 font-semibold text-[var(--ayci-ink)]">
                    {r.name || "—"}
                    {r.needs_setup && (
                      <span
                        className="ml-2 inline-block text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 align-middle"
                        title="No private chat link yet — needs setting up"
                      >
                        ⚠ Setup
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-[12px] text-[var(--ayci-ink-muted)]">{r.email || "—"}</td>
                  <td className="px-3 py-2 text-[12px]">
                    {r.tier || "—"}
                    {r.boost_and_go && /b&g/i.test(r.boost_and_go) && (
                      <span className="ml-1 text-[10px] text-violet-700">· B&amp;G</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-[12px]">{r.cohort_joined || "—"}</td>
                  <td className="px-3 py-2 text-[12px]">{formatDate(r.interview_date)}</td>
                  <td className="px-3 py-2 text-[12px]">{r.speciality || "—"}</td>
                  <td className="px-3 py-2 text-[12px]">
                    {r.video_allowance_expected == null ? (
                      <span className="text-slate-400">—</span>
                    ) : r.allowance_flag === "ok" ? (
                      <span className="text-emerald-700">{r.video_allowance}</span>
                    ) : r.allowance_flag === "missing" ? (
                      <span className="text-amber-700" title={`Should be ${r.video_allowance_expected}`}>— / {r.video_allowance_expected}</span>
                    ) : (
                      <span className="text-red-600 font-semibold" title={`Expected ${r.video_allowance_expected}`}>
                        {r.video_allowance} / {r.video_allowance_expected}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setEditing(r); }}
                      className="text-xs px-2 py-0.5 rounded border border-slate-200 hover:bg-slate-100 font-semibold text-slate-700"
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length > visibleCount && (
            <div className="px-3 py-2 flex items-center justify-between gap-3 border-t border-slate-100">
              <span className="text-[11px] text-[var(--ayci-ink-muted)] italic">
                Showing {visibleCount} of {filtered.length} matches — search/filter to narrow, or load more.
              </span>
              <button
                type="button"
                onClick={() => setVisibleCount((n) => n + 100)}
                className="text-xs px-2 py-0.5 rounded border border-slate-200 hover:bg-slate-100 font-semibold text-slate-700"
              >
                Load 100 more
              </button>
            </div>
          )}
        </div>
      )}

      {editing && (
        <EditModal
          row={editing}
          onClose={() => setEditing(null)}
          onSaved={onSaved}
        />
      )}
    </div>
  );
}

function EditModal({ row, onClose, onSaved }) {
  const [form, setForm] = useState(() => {
    const initial = {};
    for (const f of EDITABLE_FIELDS) {
      initial[f.key] = row[f.key] || "";
    }
    return initial;
  });
  const [saving, setSaving] = useState(false);

  const setField = (k, v) => setForm((prev) => ({ ...prev, [k]: v }));

  const protectedFields = new Set(row.dashboard_edited_fields || []);

  const save = async () => {
    setSaving(true);
    try {
      // Send only fields that changed from the original row.
      const patch = {};
      for (const f of EDITABLE_FIELDS) {
        const v = form[f.key];
        const orig = row[f.key] || "";
        if ((v || "") !== (orig || "")) {
          patch[f.key] = v || null;
        }
      }
      if (Object.keys(patch).length === 0) {
        toast.info("No changes to save");
        setSaving(false);
        return;
      }
      const { data } = await apiClient.patch(`/students-db/${row._id}`, patch);
      onSaved(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div
        className="bg-white rounded-lg max-w-2xl w-full mt-10 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-slate-200 flex items-start justify-between gap-3">
          <div>
            <div className="font-display text-lg font-extrabold text-[var(--ayci-ink)]">
              {row.name || row.email || "Student"}
            </div>
            <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-0.5">
              {row.email}{row.url ? " · " : ""}
              {row.url && (
                <a href={row.url} target="_blank" rel="noreferrer" className="text-sky-700 hover:underline">
                  Open on Monday
                </a>
              )}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          {EDITABLE_FIELDS.map((f) => (
            <div key={f.key}>
              <label className="text-[10px] uppercase tracking-wider font-bold text-[var(--ayci-ink-muted)] mb-1 flex items-center gap-1">
                {f.label}
                {protectedFields.has(f.key) && (
                  <span className="text-[9px] font-semibold uppercase tracking-wider px-1 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-200" title="This field has been dashboard-edited. The next Monday sync will not overwrite it.">
                    pinned
                  </span>
                )}
              </label>
              <Input
                type={f.type || (f.key === "interview_date" ? "date" : "text")}
                value={form[f.key] ?? ""}
                onChange={(e) => setField(f.key, e.target.value)}
                className="text-sm"
              />
            </div>
          ))}
        </div>

        {protectedFields.size > 0 && (
          <div className="px-4 pb-2 text-[11px] text-[var(--ayci-ink-muted)]">
            <strong>Pinned</strong> fields override the Monday sync. Changes you make here stay even when Monday is updated.
          </div>
        )}

        <div className="p-4 pt-2 flex justify-end gap-2 border-t border-slate-100">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={save} disabled={saving}>
            {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}
