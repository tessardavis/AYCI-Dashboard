import { useEffect, useState } from "react";
import { Trophy, Award, Loader2, RefreshCw, Medal, ChevronDown, ChevronUp, TrendingUp, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import HeroBanner, { HERO_PRESETS } from "@/components/HeroBanner";

const DEFAULT_COHORT = "June '26";
const COHORT_OPTIONS = ["June '26", "Apr '26", "Feb '26", "April '25"];

const RANK_STYLES = {
  1: { ring: "ring-2 ring-amber-400", bg: "bg-gradient-to-br from-amber-100 to-yellow-50", medal: "text-amber-600" },
  2: { ring: "ring-2 ring-slate-300", bg: "bg-gradient-to-br from-slate-100 to-slate-50", medal: "text-slate-500" },
  3: { ring: "ring-2 ring-orange-300", bg: "bg-gradient-to-br from-orange-100 to-amber-50", medal: "text-orange-600" },
};

export default function CohortLeaderboard() {
  const [cohort, setCohort] = useState(DEFAULT_COHORT);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async (c = cohort) => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/leaderboard/cohort", {
        params: { cohort: c, limit: 25 },
        timeout: 90000,
      });
      setData(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load leaderboard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(cohort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cohort]);

  const entries = data?.entries || [];
  const climbers = data?.biggest_climbers || [];
  const topScore = entries[0]?.score || 1;
  const anyDelta = entries.some((e) => e.delta !== null && e.delta !== undefined);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="leaderboard-page">
      <HeroBanner
        {...HERO_PRESETS.leaderboard}
        eyebrow="Cohort ranking"
        title="Cohort Leaderboard"
        subtitle={`Top badge earners for ${cohort}. Score = Circle badges (cohort + private-tier badges excluded).`}
        testid="leaderboard-hero"
        actions={
          <div className="flex items-center gap-2">
            <select
              value={cohort}
              onChange={(e) => setCohort(e.target.value)}
              data-testid="leaderboard-cohort-select"
              className="text-sm px-3 py-2 rounded-md bg-white/95 border border-white/20 text-[var(--ayci-ink)] font-semibold focus:outline-none"
            >
              {COHORT_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => load(cohort)}
              disabled={loading}
              data-testid="leaderboard-refresh"
              className="bg-white/95 border-white/20 text-[var(--ayci-ink)] hover:bg-white"
            >
              {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
              Refresh
            </Button>
          </div>
        }
      />

      {loading && !data ? (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
          Loading leaderboard…
        </div>
      ) : entries.length === 0 ? (
        <div
          className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]"
          data-testid="leaderboard-empty"
        >
          <Trophy className="w-6 h-6 mx-auto mb-3 text-[var(--ayci-ink-muted)]" />
          No members found for <span className="font-semibold">{cohort}</span>.
        </div>
      ) : (
        <>
          {/* Podium (top 3) */}
          {entries.length >= 3 && <Podium entries={entries.slice(0, 3)} />}

          {/* Biggest climbers */}
          {climbers.length > 0 ? (
            <ClimbersSection climbers={climbers} />
          ) : !anyDelta ? (
            <div
              className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800 flex items-start gap-2"
              data-testid="leaderboard-no-history"
            >
              <TrendingUp className="w-4 h-4 shrink-0 mt-0.5" />
              <span>
                <strong>Week-over-week tracking started today.</strong> We'll
                start showing "biggest climbers" and <em>+N this week</em>{" "}
                indicators once the first snapshot is 7 days old.
              </span>
            </div>
          ) : null}

          {/* Full list */}
          <section className="bg-white border border-[var(--ayci-border)] rounded-lg overflow-hidden" data-testid="leaderboard-table">
            <div className="px-5 py-3 border-b border-[var(--ayci-border)] bg-slate-50/50 flex items-center justify-between">
              <h2 className="font-display font-semibold text-[var(--ayci-ink)]">Top 25</h2>
              <span className="text-xs text-[var(--ayci-ink-muted)]">{entries.length} ranked</span>
            </div>
            <ol className="divide-y divide-[var(--ayci-border)]">
              {entries.map((e, i) => (
                <LeaderboardRow
                  key={`${e.email || e.name}-${i + 1}`}
                  entry={e}
                  rank={i + 1}
                  topScore={topScore}
                />
              ))}
            </ol>
          </section>
        </>
      )}
    </div>
  );
}

function LeaderboardRow({ entry, rank, topScore }) {
  const [open, setOpen] = useState(false);
  const e = entry;
  const pct = Math.max(6, Math.round((e.score / topScore) * 100));
  const rankStyle = RANK_STYLES[rank];
  const hasDelta = e.delta !== null && e.delta !== undefined;
  return (
    <li data-testid={`leaderboard-row-${rank}`}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-3 flex items-center gap-4 hover:bg-slate-50/50 text-left"
        aria-expanded={open}
        data-testid={`leaderboard-row-${rank}-toggle`}
      >
        <div className="flex items-center justify-center w-10 shrink-0">
          {rankStyle ? (
            <div
              className={`inline-flex items-center justify-center w-9 h-9 rounded-full ${rankStyle.bg} ${rankStyle.ring}`}
            >
              <Medal className={`w-5 h-5 ${rankStyle.medal}`} />
            </div>
          ) : (
            <span className="text-sm font-semibold text-[var(--ayci-ink-muted)] tabular-nums">
              {rank}
            </span>
          )}
        </div>
        {e.avatar_url ? (
          <img
            src={e.avatar_url}
            alt=""
            className="w-8 h-8 rounded-full object-cover shrink-0 border border-[var(--ayci-border)]"
          />
        ) : (
          <div className="w-8 h-8 rounded-full bg-slate-100 border border-[var(--ayci-border)] flex items-center justify-center text-xs font-semibold text-[var(--ayci-ink-muted)] shrink-0">
            {(e.name || "?").split(" ").map((p) => p[0]).filter(Boolean).slice(0, 2).join("")}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-[var(--ayci-ink)] truncate">{e.name || "(no name)"}</span>
            {hasDelta && e.delta > 0 && (
              <span
                className="inline-flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200 tabular-nums"
                title={`Earned ${e.delta} new badge${e.delta === 1 ? "" : "s"} since ${e.delta_snapshot_date}`}
                data-testid={`leaderboard-delta-${rank}`}
              >
                <TrendingUp className="w-3 h-3" />+{e.delta}
              </span>
            )}
            {hasDelta && e.delta === 0 && (
              <span className="text-[10px] text-[var(--ayci-ink-muted)] tabular-nums">· no change</span>
            )}
          </div>
          {e.email && (
            <div className="text-[11px] text-[var(--ayci-ink-muted)] truncate">{e.email}</div>
          )}
        </div>
        <div className="flex-1 max-w-[280px] hidden sm:block">
          <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-amber-400 to-orange-500"
              style={{ width: `${pct}%`, transition: "width 600ms ease-out" }}
            />
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="inline-flex items-center gap-1 text-base font-display font-bold text-[var(--ayci-ink)] tabular-nums">
            <Award className="w-4 h-4 text-amber-500" />
            {e.score}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
            badge{e.score === 1 ? "" : "s"}
          </div>
        </div>
        <div className="shrink-0 text-[var(--ayci-ink-muted)]">
          {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </div>
      </button>
      {open && (
        <div
          className="px-5 pb-4 pl-[72px] bg-slate-50/30"
          data-testid={`leaderboard-row-${rank}-badges`}
        >
          {(e.badges || []).length === 0 ? (
            <div className="text-xs text-[var(--ayci-ink-muted)] italic py-1">No badges yet.</div>
          ) : (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {e.badges.map((b) => {
                const isNew = (e.new_badges || []).includes(b);
                return (
                  <span
                    key={b}
                    className={
                      "inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-full border " +
                      (isNew
                        ? "bg-emerald-100 text-emerald-800 border-emerald-300"
                        : "bg-amber-50 text-amber-800 border-amber-200")
                    }
                    title={isNew ? "Earned in the last 7 days" : undefined}
                  >
                    {isNew && <Sparkles className="w-3 h-3" />}
                    <Award className="w-3 h-3" />
                    {b}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function ClimbersSection({ climbers }) {
  return (
    <section
      className="bg-gradient-to-br from-emerald-50 via-teal-50 to-sky-50 border border-emerald-200 rounded-lg p-5"
      data-testid="leaderboard-climbers"
    >
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp className="w-5 h-5 text-emerald-700" />
        <h2 className="font-display font-bold text-[var(--ayci-ink)]">Biggest climbers this week</h2>
        <span className="text-xs text-[var(--ayci-ink-muted)]">
          · gained the most new badges in the last 7 days
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {climbers.map((c, i) => (
          <div
            key={c.email || c.name}
            className="bg-white border border-emerald-200 rounded-md p-3 flex items-center gap-3"
            data-testid={`leaderboard-climber-${i + 1}`}
          >
            <div className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-emerald-100 text-emerald-800 text-xs font-bold shrink-0">
              {i + 1}
            </div>
            {c.avatar_url ? (
              <img
                src={c.avatar_url}
                alt=""
                className="w-9 h-9 rounded-full object-cover border border-[var(--ayci-border)] shrink-0"
              />
            ) : (
              <div className="w-9 h-9 rounded-full bg-slate-100 border border-[var(--ayci-border)] flex items-center justify-center text-xs font-semibold text-[var(--ayci-ink-muted)] shrink-0">
                {(c.name || "?").split(" ").map((p) => p[0]).filter(Boolean).slice(0, 2).join("")}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="font-semibold text-[var(--ayci-ink)] truncate">{c.name || "(no name)"}</div>
              <div className="text-[11px] text-[var(--ayci-ink-muted)] truncate">
                {c.new_badges?.length > 0
                  ? `New: ${c.new_badges.slice(0, 3).join(", ")}${
                      c.new_badges.length > 3 ? `, +${c.new_badges.length - 3}` : ""
                    }`
                  : "new badges"}
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="inline-flex items-center gap-0.5 text-sm font-bold text-emerald-700 tabular-nums">
                <TrendingUp className="w-3.5 h-3.5" />+{c.delta}
              </div>
              <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] tabular-nums">
                {c.prev_score} → {c.current_score}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Podium({ entries }) {
  const [first, second, third] = entries;
  const order = [second, first, third]; // visually centre 1st
  const heights = { 1: "h-32", 2: "h-24", 3: "h-20" };
  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 flex items-end justify-center gap-3 sm:gap-6"
      data-testid="leaderboard-podium"
    >
      {order.map((e, i) => {
        const rank = [2, 1, 3][i];
        const style = RANK_STYLES[rank];
        return (
          <div key={rank} className="flex flex-col items-center gap-2 w-1/3 max-w-[200px]">
            {e.avatar_url ? (
              <img
                src={e.avatar_url}
                alt=""
                className={`w-16 h-16 rounded-full object-cover border border-[var(--ayci-border)] ${style.ring}`}
              />
            ) : (
              <div
                className={`w-16 h-16 rounded-full ${style.bg} ${style.ring} flex items-center justify-center text-lg font-semibold text-[var(--ayci-ink)]`}
              >
                {(e.name || "?").split(" ").map((p) => p[0]).filter(Boolean).slice(0, 2).join("")}
              </div>
            )}
            <div className="text-center min-w-0 w-full">
              <div className="font-semibold text-[var(--ayci-ink)] text-sm truncate">{e.name}</div>
              <div className="inline-flex items-center gap-1 text-xs font-bold text-amber-700 mt-0.5">
                <Award className="w-3 h-3 fill-current" />
                {e.score} badges
              </div>
            </div>
            <div
              className={`w-full ${heights[rank]} ${style.bg} rounded-t-md flex items-start justify-center pt-2 ${style.ring}`}
            >
              <Medal className={`w-6 h-6 ${style.medal}`} />
            </div>
          </div>
        );
      })}
    </section>
  );
}
