import { useEffect, useState } from "react";
import { Loader2, Save, Plus, Trash2, Layers } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Per-cohort config powering the Cohort Dashboard. Each launch is a row here
// (no code change): the cohort label must match Monday's "Cohort Joined" text
// exactly, the Circle tag must match the tag on Circle exactly (e.g. some
// cohorts use "June '26", others "Apr '26"), and the two ConvertKit tag IDs +
// Intros space id come from Kit / Circle.
const BLANK = { label: "", circle_tag: "", new_tag_id: "", legacy_tag_id: "", intros_space_id: "" };

export default function CohortConfigSection({ isAdmin }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/cohorts/config");
      const arr = Object.entries(data || {}).map(([label, cfg]) => ({
        label,
        circle_tag: cfg.circle_tag ?? "",
        new_tag_id: cfg.new_tag_id ?? "",
        legacy_tag_id: cfg.legacy_tag_id ?? "",
        intros_space_id: cfg.intros_space_id ?? "",
      }));
      arr.sort((a, b) => a.label.localeCompare(b.label));
      setRows(arr.length ? arr : [{ ...BLANK }]);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load cohort config");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const update = (i, key, value) =>
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, [key]: value } : r)));
  const addRow = () => setRows((prev) => [...prev, { ...BLANK }]);
  const removeRow = (i) => setRows((prev) => prev.filter((_, idx) => idx !== i));

  const save = async () => {
    if (!isAdmin) return;
    const configs = {};
    for (const r of rows) {
      const label = (r.label || "").trim();
      if (!label) {
        toast.error("Every cohort row needs a label (match Monday's 'Cohort Joined' text)");
        return;
      }
      configs[label] = {
        circle_tag: (r.circle_tag || "").trim(),
        new_tag_id: r.new_tag_id === "" ? null : Number(r.new_tag_id),
        legacy_tag_id: r.legacy_tag_id === "" ? null : Number(r.legacy_tag_id),
        intros_space_id: r.intros_space_id === "" ? null : Number(r.intros_space_id),
      };
    }
    setSaving(true);
    try {
      await apiClient.put("/cohorts/config", { configs });
      toast.success("Cohort config saved");
      load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="mt-8 pt-6 border-t border-[var(--ayci-border)] text-center text-[var(--ayci-ink-muted)]" data-testid="cohort-config-loading">
        <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2 text-[var(--ayci-teal)]" />
        Loading cohort config…
      </div>
    );
  }

  return (
    <div className="mt-6 bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6" data-testid="cohort-config-section">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg bg-fuchsia-50 border border-fuchsia-200 flex items-center justify-center text-fuchsia-700 shrink-0">
          <Layers className="w-5 h-5" />
        </div>
        <div>
          <h3 className="font-display font-bold text-base text-[var(--ayci-ink)]">
            Cohort Dashboard - per-cohort config
          </h3>
          <p className="text-xs text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            Powers the Cohort Dashboard's New/Legacy split, Circle join-rate and
            intros stats. Add a row each launch - no deploy needed.
            <br />
            <strong>Label</strong>: exact Monday "Cohort Joined" text (e.g. <code>June 26</code>).{" "}
            <strong>Circle tag</strong>: exact tag on Circle (e.g. <code>June '26</code> - note some cohorts use the full month).{" "}
            <strong>New / Legacy</strong>: ConvertKit tag IDs.{" "}
            <strong>Intros space</strong>: Circle "Introduce Yourself" space id.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        {rows.map((r, i) => (
          <div
            key={i}
            className="grid grid-cols-1 sm:grid-cols-[1.3fr_1fr_1fr_1fr_1fr_auto] gap-2 items-end border border-[var(--ayci-border)] rounded-lg p-3 bg-slate-50/60"
            data-testid={`cohort-config-row-${i}`}
          >
            <Field label="Cohort label" value={r.label} onChange={(v) => update(i, "label", v)} disabled={!isAdmin || saving} placeholder="June 26" />
            <Field label="Circle tag" value={r.circle_tag} onChange={(v) => update(i, "circle_tag", v)} disabled={!isAdmin || saving} placeholder="June '26" />
            <Field label="New tag ID" value={r.new_tag_id} onChange={(v) => update(i, "new_tag_id", v)} disabled={!isAdmin || saving} placeholder="19550942" inputMode="numeric" />
            <Field label="Legacy tag ID" value={r.legacy_tag_id} onChange={(v) => update(i, "legacy_tag_id", v)} disabled={!isAdmin || saving} placeholder="19550968" inputMode="numeric" />
            <Field label="Intros space ID" value={r.intros_space_id} onChange={(v) => update(i, "intros_space_id", v)} disabled={!isAdmin || saving} placeholder="2647286" inputMode="numeric" />
            {isAdmin && (
              <button
                type="button"
                onClick={() => removeRow(i)}
                disabled={saving}
                className="h-9 px-2 text-red-600 hover:bg-red-50 rounded-md shrink-0"
                title="Remove this cohort"
                data-testid={`cohort-config-remove-${i}`}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        ))}
      </div>

      {isAdmin ? (
        <div className="flex gap-2 mt-4 flex-wrap">
          <Button onClick={save} disabled={saving} data-testid="save-cohort-config-btn">
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Saving…
              </>
            ) : (
              <>
                <Save className="w-4 h-4 mr-2" />
                Save cohort config
              </>
            )}
          </Button>
          <Button variant="outline" onClick={addRow} disabled={saving} data-testid="add-cohort-config-btn">
            <Plus className="w-4 h-4 mr-2" />
            Add cohort
          </Button>
        </div>
      ) : (
        <p className="text-xs text-[var(--ayci-ink-muted)] mt-4 italic">Admin-only - read-only view.</p>
      )}
    </div>
  );
}

function Field({ label, value, onChange, disabled, placeholder, inputMode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)]">
        {label}
      </span>
      <Input
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        inputMode={inputMode}
      />
    </label>
  );
}
