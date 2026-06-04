import { useEffect, useState } from "react";
import { Loader2, Save, RotateCcw, Tag } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DEFAULT_COHORT_MILESTONES,
  invalidateMilestoneCache,
} from "@/components/student/EngagementBar";

export default function CohortMilestonesSection({ isAdmin }) {
  const [milestones, setMilestones] = useState(["", "", "", "", ""]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/settings/cohort-milestones");
      if (Array.isArray(data?.milestones) && data.milestones.length === 5) {
        setMilestones(data.milestones);
      }
    } catch (err) {
      toast.error(
        formatApiErrorDetail(err.response?.data?.detail) ||
          "Failed to load milestones",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const update = (i, value) => {
    setMilestones((prev) => {
      const next = [...prev];
      next[i] = value;
      return next;
    });
  };

  const save = async () => {
    if (!isAdmin) return;
    if (milestones.some((m) => !m.trim())) {
      toast.error("All 5 milestone names are required");
      return;
    }
    setSaving(true);
    try {
      const { data } = await apiClient.put("/settings/cohort-milestones", {
        milestones: milestones.map((m) => m.trim()),
      });
      setMilestones(data.milestones);
      invalidateMilestoneCache();
      toast.success("Milestones updated");
    } catch (err) {
      toast.error(
        formatApiErrorDetail(err.response?.data?.detail) || "Save failed",
      );
    } finally {
      setSaving(false);
    }
  };

  const resetToDefaults = () => {
    setMilestones([...DEFAULT_COHORT_MILESTONES]);
  };

  if (loading) {
    return (
      <div
        className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]"
        data-testid="cohort-milestones-loading"
      >
        <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2 text-[var(--ayci-teal)]" />
        Loading milestones…
      </div>
    );
  }

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6 max-w-2xl"
      data-testid="cohort-milestones-section"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-lg bg-violet-50 border border-violet-200 flex items-center justify-center text-violet-700 shrink-0">
          <Tag className="w-5 h-5" />
        </div>
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Cohort engagement milestones
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5">
            The 5 Circle tags tracked in the Student Lookup engagement bar.
            Names must match Circle tags exactly (case-insensitive). Order =
            progression.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        {milestones.map((m, i) => (
          <div
            key={i}
            className="flex items-center gap-3"
            data-testid={`milestone-input-row-${i}`}
          >
            <span className="w-7 h-7 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center text-xs font-bold text-slate-600 shrink-0">
              {i + 1}
            </span>
            <Input
              value={m}
              onChange={(e) => update(i, e.target.value)}
              placeholder={DEFAULT_COHORT_MILESTONES[i]}
              disabled={!isAdmin || saving}
              className="flex-1"
              data-testid={`milestone-input-${i}`}
            />
          </div>
        ))}
      </div>

      {isAdmin ? (
        <div className="flex gap-2 mt-6 flex-wrap">
          <Button
            onClick={save}
            disabled={saving}
            data-testid="save-milestones-btn"
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Saving…
              </>
            ) : (
              <>
                <Save className="w-4 h-4 mr-2" />
                Save changes
              </>
            )}
          </Button>
          <Button
            variant="outline"
            onClick={resetToDefaults}
            disabled={saving}
            data-testid="reset-milestones-btn"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            Reset to defaults
          </Button>
        </div>
      ) : (
        <p className="text-xs text-[var(--ayci-ink-muted)] mt-4 italic">
          Admin-only — read-only view.
        </p>
      )}

      <CoachSpacesEditor isAdmin={isAdmin} />
    </div>
  );
}

function CoachSpacesEditor({ isAdmin }) {
  const [spaces, setSpaces] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/settings/coach-spaces");
      setSpaces(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load coach spaces");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (!isAdmin || !spaces) return;
    setSaving(true);
    try {
      const { data } = await apiClient.put("/settings/coach-spaces", spaces);
      setSpaces(data);
      toast.success("Coach Activity spaces updated — dashboard cache cleared");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading || !spaces) return null;

  return (
    <div
      className="mt-8 pt-6 border-t border-[var(--ayci-border)]"
      data-testid="coach-spaces-editor"
    >
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-700 shrink-0">
          <Tag className="w-5 h-5" />
        </div>
        <div>
          <h3 className="font-display font-bold text-base text-[var(--ayci-ink)]">
            Coach Activity — Circle spaces
          </h3>
          <p className="text-xs text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            The Coach Activity dashboard tracks coach engagement in these two
            Circle spaces from the cohort start date. Update when a new cohort
            spins up new spaces. Find the space ID in the Circle URL after `/c/`
            (open the space, copy the slug, then look up its numeric ID).
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl">
        <FieldRow
          label="Recorded Answer Review — space ID"
          value={spaces.recorded_answer_space_id}
          onChange={(v) =>
            setSpaces((s) => ({ ...s, recorded_answer_space_id: Number(v) || 0 }))
          }
          disabled={!isAdmin || saving}
          testid="coach-recorded-space-id"
          inputType="number"
        />
        <FieldRow
          label="Cohort start (recorded answers)"
          value={spaces.recorded_answer_start}
          onChange={(v) => setSpaces((s) => ({ ...s, recorded_answer_start: v }))}
          disabled={!isAdmin || saving}
          testid="coach-recorded-start"
          inputType="date"
        />
        <FieldRow
          label="Interview Support — space ID"
          value={spaces.interview_support_space_id}
          onChange={(v) =>
            setSpaces((s) => ({ ...s, interview_support_space_id: Number(v) || 0 }))
          }
          disabled={!isAdmin || saving}
          testid="coach-interview-space-id"
          inputType="number"
        />
        <FieldRow
          label="Cohort start (interview support)"
          value={spaces.interview_support_start}
          onChange={(v) => setSpaces((s) => ({ ...s, interview_support_start: v }))}
          disabled={!isAdmin || saving}
          testid="coach-interview-start"
          inputType="date"
        />
        <FieldRow
          label="Cohort end (recorded answers)"
          value={spaces.recorded_answer_end || ""}
          onChange={(v) => setSpaces((s) => ({ ...s, recorded_answer_end: v || null }))}
          disabled={!isAdmin || saving}
          testid="coach-recorded-end"
          inputType="date"
        />
        <FieldRow
          label="Cohort end (interview support)"
          value={spaces.interview_support_end || ""}
          onChange={(v) => setSpaces((s) => ({ ...s, interview_support_end: v || null }))}
          disabled={!isAdmin || saving}
          testid="coach-interview-end"
          inputType="date"
        />
      </div>
      <p className="mt-2 text-[11px] text-[var(--ayci-ink-muted)] max-w-prose">
        Set a cohort end date when the cohort wraps — the daily Coach SLA Digest
        will stop posting in <code>#coaching-spotlight</code> once both end dates
        are in the past. Clear the end date (delete the value) when the next
        cohort starts to resume the digest.
      </p>

      {isAdmin && (
        <div className="mt-4">
          <Button
            onClick={save}
            disabled={saving}
            data-testid="save-coach-spaces-btn"
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Saving…
              </>
            ) : (
              <>
                <Save className="w-4 h-4 mr-2" />
                Save coach spaces
              </>
            )}
          </Button>
        </div>
      )}
    </div>
  );
}

function FieldRow({ label, value, onChange, disabled, testid, inputType = "text" }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)]">
        {label}
      </span>
      <Input
        type={inputType}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        data-testid={testid}
      />
    </label>
  );
}
