import { useEffect, useState } from "react";
import { Check, Lock } from "lucide-react";

import { apiClient } from "@/lib/api";

// Default 5 Circle milestone tags — used as a fallback if the settings API fails.
// The active list is loaded dynamically from /api/settings/cohort-milestones.
export const DEFAULT_COHORT_MILESTONES = [
  "USP Guru",
  "Verified Examples Badge",
  "Senior-Level Thinker",
  "Job Mastermind",
  "Authentic Self",
];

let _milestoneCache = null;

async function _loadMilestones() {
  if (_milestoneCache) return _milestoneCache;
  try {
    const { data } = await apiClient.get("/settings/cohort-milestones");
    if (Array.isArray(data?.milestones) && data.milestones.length === 5) {
      _milestoneCache = data.milestones;
      return _milestoneCache;
    }
  } catch {
    // fallback below
  }
  _milestoneCache = DEFAULT_COHORT_MILESTONES;
  return _milestoneCache;
}

export function invalidateMilestoneCache() {
  _milestoneCache = null;
}

/**
 * 5-step progress bar showing which Circle milestone tags this student
 * has earned. Driven by `circle.data.member_tags` from the unified lookup.
 * Milestone names are loaded from the admin-editable settings endpoint.
 */
export default function EngagementBar({ circle }) {
  const [milestones, setMilestones] = useState(DEFAULT_COHORT_MILESTONES);
  useEffect(() => {
    let cancelled = false;
    _loadMilestones().then((m) => {
      if (!cancelled) setMilestones(m);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const tags = circle?.data?.member_tags || [];
  const tagsLower = tags.map((t) => (t || "").toLowerCase().trim());
  const status = milestones.map((m) => ({
    name: m,
    achieved: tagsLower.includes(m.toLowerCase()),
  }));
  const achievedCount = status.filter((s) => s.achieved).length;
  const pct = Math.round((achievedCount / milestones.length) * 100);
  const noCircle = !circle?.found;

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-4 sm:p-5 shadow-sm"
      data-testid="engagement-bar"
    >
      <div className="flex items-start sm:items-center justify-between gap-3 flex-wrap mb-4">
        <div>
          <div className="text-[10px] sm:text-[11px] font-display font-semibold tracking-[0.2em] uppercase text-[var(--ayci-teal)]">
            Cohort engagement
          </div>
          <div className="text-sm text-[var(--ayci-ink-muted)] mt-0.5">
            {noCircle
              ? "No Circle account found — milestones can't be tracked."
              : `${achievedCount} of ${milestones.length} milestones earned · ${pct}%`}
          </div>
        </div>
        {!noCircle && (
          <div
            className="text-2xl font-display font-bold text-[var(--ayci-ink)]"
            data-testid="engagement-bar-percent"
          >
            {pct}%
          </div>
        )}
      </div>

      <div className="relative" aria-hidden={noCircle}>
        <div className="absolute left-3 right-3 top-3 h-0.5 bg-slate-200 rounded-full" />
        <div
          className="absolute left-3 top-3 h-0.5 bg-emerald-500 rounded-full transition-all duration-500"
          style={{
            width: `calc((100% - 24px) * ${achievedCount === 0 ? 0 : (achievedCount - 1) / (milestones.length - 1)})`,
          }}
        />

        <ol className="grid grid-cols-5 gap-1 sm:gap-3 relative">
          {status.map((s, i) => (
            <li
              key={s.name}
              className="flex flex-col items-center text-center min-w-0"
              data-testid={`milestone-${i}`}
            >
              <span
                className={
                  "w-6 h-6 sm:w-7 sm:h-7 rounded-full flex items-center justify-center border-2 transition-colors " +
                  (noCircle
                    ? "bg-slate-100 border-slate-200 text-slate-400"
                    : s.achieved
                    ? "bg-emerald-500 border-emerald-500 text-white"
                    : "bg-white border-slate-300 text-slate-400")
                }
                title={s.achieved ? "Earned" : "Not yet earned"}
              >
                {noCircle ? (
                  <Lock className="w-3 h-3" />
                ) : s.achieved ? (
                  <Check className="w-3.5 h-3.5" strokeWidth={3} />
                ) : (
                  <span className="text-[10px] font-bold">{i + 1}</span>
                )}
              </span>
              <span
                className={
                  "mt-1.5 text-[10px] sm:text-[11px] leading-tight font-semibold uppercase tracking-wider " +
                  (s.achieved && !noCircle
                    ? "text-emerald-700"
                    : "text-[var(--ayci-ink-muted)]")
                }
              >
                {s.name}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
