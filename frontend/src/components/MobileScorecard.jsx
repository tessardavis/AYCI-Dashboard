/**
 * Mobile-only Weekly Scorecard view (shown on `<sm` viewports, hidden on
 * tablet/desktop where the table is shown). Cards are grouped by category
 * matching the desktop table. Each card collapses to "this week" by default
 * and expands tap-by-tap to show every visible week — and any week is
 * editable in the same way (reuses startEdit / commitEdit / etc.).
 */
import { useState } from "react";
import { ChevronDown, Filter as FilterIcon, X } from "lucide-react";

import { formatValue, formatWeekLabel, isOnTrack } from "@/lib/format";
import Sparkline from "@/components/Sparkline";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";

export default function MobileScorecard({
  grouped,
  weeks,                        // newest-first
  valueMap,
  teamById,
  team,
  filterOwnerId,
  setFilterOwnerId,
  startEdit,
  editingCell,
  editingValue,
  setEditingValue,
  commitEdit,
  onCellKey,
  loading,
  CATEGORY_ORDER,
}) {
  const latest = weeks[0];

  return (
    <div className="space-y-5 sm:hidden" data-testid="scorecard-mobile">
      {/* Owner filter — collapsed into a disclosure on mobile (option 4b) */}
      <OwnerFilter
        team={team}
        filterOwnerId={filterOwnerId}
        setFilterOwnerId={setFilterOwnerId}
        teamById={teamById}
      />

      {loading ? (
        <div className="text-sm text-[var(--ayci-ink-muted)]">Loading…</div>
      ) : (
        CATEGORY_ORDER.filter((c) => grouped[c]?.length > 0).map((cat) => (
          <section key={cat} data-testid={`scorecard-mobile-section-${cat}`}>
            <h2 className="text-[10px] uppercase tracking-widest font-display font-bold text-[var(--ayci-ink-muted)] mb-2 px-1">
              {cat}
            </h2>
            <div className="space-y-2">
              {grouped[cat].map((m) => (
                <MetricCard
                  key={m.id}
                  metric={m}
                  weeks={weeks}
                  latest={latest}
                  valueMap={valueMap}
                  teamById={teamById}
                  startEdit={startEdit}
                  editingCell={editingCell}
                  editingValue={editingValue}
                  setEditingValue={setEditingValue}
                  commitEdit={commitEdit}
                  onCellKey={onCellKey}
                />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

// ---- Owner filter as a "Filter" dropdown -----------------------------------

function OwnerFilter({ team, filterOwnerId, setFilterOwnerId, teamById }) {
  const [open, setOpen] = useState(false);
  const active = filterOwnerId ? teamById[filterOwnerId]?.name : null;
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        data-testid="scorecard-mobile-filter-toggle"
        className="w-full flex items-center justify-between bg-white border border-[var(--ayci-border)] rounded-md px-3 py-2 text-sm shadow-sm"
      >
        <span className="flex items-center gap-1.5">
          <FilterIcon className="w-3.5 h-3.5 text-[var(--ayci-ink-muted)]" />
          <span className="text-[var(--ayci-ink-muted)] text-xs">
            Filter by owner
          </span>
          {active && (
            <span className="ml-1 inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-[var(--ayci-accent)] text-white">
              {active}
            </span>
          )}
        </span>
        <ChevronDown
          className={`w-4 h-4 text-[var(--ayci-ink-muted)] transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div
          className="absolute z-30 mt-1 w-full bg-white border border-[var(--ayci-border)] rounded-md shadow-lg py-1 max-h-60 overflow-y-auto"
          data-testid="scorecard-mobile-filter-menu"
        >
          <button
            onClick={() => { setFilterOwnerId(null); setOpen(false); }}
            className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex items-center justify-between"
            data-testid="scorecard-mobile-filter-clear"
          >
            <span>All owners</span>
            {!filterOwnerId && <X className="w-3 h-3 text-[var(--ayci-accent)]" />}
          </button>
          {team.map((t) => (
            <button
              key={t.id}
              onClick={() => { setFilterOwnerId(t.id); setOpen(false); }}
              className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex items-center justify-between"
              data-testid={`scorecard-mobile-filter-${t.id}`}
            >
              <span>{t.name}</span>
              {filterOwnerId === t.id && (
                <span className="text-[10px] uppercase tracking-wider text-[var(--ayci-accent)] font-display font-semibold">
                  Active
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- Metric card -----------------------------------------------------------

function MetricCard({
  metric,
  weeks,
  latest,
  valueMap,
  teamById,
  startEdit,
  editingCell,
  editingValue,
  setEditingValue,
  commitEdit,
  onCellKey,
}) {
  const [expanded, setExpanded] = useState(false);
  const latestVal = valueMap[`${metric.id}|${latest}`];
  const track = isOnTrack(latestVal, metric.goal, metric.goal_direction);
  const owners = (metric.owner_ids || [])
    .map((id) => teamById[id])
    .filter(Boolean);

  // Sparkline data — chronological
  const series = weeks
    .slice()
    .reverse()
    .map((w) => valueMap[`${metric.id}|${w}`])
    .map((v) => (v === undefined || v === null ? null : Number(v)));

  // Tone for headline value
  const toneCls =
    track === null
      ? "text-[var(--ayci-ink)] bg-slate-50 border-slate-200"
      : track
      ? "text-[var(--ayci-success-ink)] bg-[var(--ayci-success-bg)] border-emerald-200"
      : "text-[var(--ayci-danger-ink)] bg-[var(--ayci-danger-bg)] border-rose-200";

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm overflow-hidden"
      data-testid={`scorecard-mobile-metric-${metric.id}`}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-4 py-3"
        aria-expanded={expanded}
      >
        <div className="flex items-start gap-3">
          {/* Owner avatars */}
          <div className="flex -space-x-1.5 shrink-0 pt-0.5">
            {owners.length === 0 ? (
              <div className="w-7 h-7 rounded-full bg-slate-100 border-2 border-white" />
            ) : (
              owners.slice(0, 2).map((o) => (
                <Avatar key={o.id} className="w-7 h-7 border-2 border-white">
                  {o.avatar_url ? (
                    <AvatarImage src={o.avatar_url} alt={o.name} />
                  ) : (
                    <AvatarFallback className="text-[10px] bg-slate-200 text-slate-600">
                      {(o.name || "?").slice(0, 2).toUpperCase()}
                    </AvatarFallback>
                  )}
                </Avatar>
              ))
            )}
          </div>

          <div className="flex-1 min-w-0">
            <div className="font-medium text-sm text-[var(--ayci-ink)] truncate">
              {metric.name}
            </div>
            <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-0.5">
              {metric.goal == null ? (
                <span className="italic opacity-70">No target</span>
              ) : (
                <>
                  Goal {formatValue(metric.goal, metric.format)}
                  {metric.goal_direction === "below" ? " or below" : " or above"}
                </>
              )}
            </div>
          </div>

          {/* This week's value */}
          <div className="text-right shrink-0">
            <span
              className={`inline-block min-w-[3.5rem] text-right text-sm font-display font-semibold tabular-nums px-2.5 py-1 rounded-md border ${toneCls}`}
            >
              {latestVal !== undefined ? formatValue(latestVal, metric.format) : "—"}
            </span>
            <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5">
              W/C {formatWeekLabel(latest)}
            </div>
          </div>

          <ChevronDown
            className={`w-4 h-4 text-[var(--ayci-ink-muted)] transition-transform mt-1 shrink-0 ${expanded ? "rotate-180" : ""}`}
          />
        </div>

        {/* Sparkline */}
        {series.some((v) => v !== null) && (
          <div className="mt-2 h-8">
            <Sparkline data={series} />
          </div>
        )}
      </button>

      {expanded && (
        <div className="border-t border-[var(--ayci-border)] bg-slate-50/50">
          <ul className="divide-y divide-[var(--ayci-border)]">
            {weeks.map((w) => {
              const val = valueMap[`${metric.id}|${w}`];
              const isEditing =
                editingCell?.metric_id === metric.id && editingCell?.week_start === w;
              const t = isOnTrack(val, metric.goal, metric.goal_direction);
              const tone =
                t === null
                  ? "text-[var(--ayci-ink-muted)]"
                  : t
                  ? "text-[var(--ayci-success-ink)]"
                  : "text-[var(--ayci-danger-ink)]";
              return (
                <li
                  key={w}
                  className="flex items-center justify-between px-4 py-2.5 text-sm"
                  data-testid={`scorecard-mobile-row-${metric.id}-${w}`}
                >
                  <span className="text-[var(--ayci-ink-muted)] text-xs">
                    W/C {formatWeekLabel(w)}
                  </span>
                  {isEditing ? (
                    <input
                      autoFocus
                      type="text"
                      inputMode="decimal"
                      value={editingValue}
                      onChange={(e) => setEditingValue(e.target.value)}
                      onBlur={commitEdit}
                      onKeyDown={onCellKey}
                      className="w-24 text-right border border-[var(--ayci-accent)] rounded px-2 py-1 text-sm font-display font-semibold focus:outline-none"
                      data-testid={`scorecard-mobile-input-${metric.id}-${w}`}
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); startEdit(metric, w); }}
                      className={`min-w-[3.5rem] text-right font-display font-semibold tabular-nums ${tone} hover:underline`}
                      data-testid={`scorecard-mobile-cell-${metric.id}-${w}`}
                    >
                      {val !== undefined ? formatValue(val, metric.format) : "—"}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
