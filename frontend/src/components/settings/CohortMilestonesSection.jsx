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
    </div>
  );
}
