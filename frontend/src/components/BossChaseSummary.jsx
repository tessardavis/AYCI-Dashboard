import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { Award } from "lucide-react";

import { apiClient } from "@/lib/api";

// "Bosses to chase" widget for the Boss Badge & testimonials process. Baseline is
// every Boss; we'd like each to do two INDEPENDENT things - share a win AND record
// a testimonial. Shows the two gaps per Boss and, for the dashboard-driven
// testimonial chase, how many reminder DMs have gone out - with a Stop control
// (the "Replied" rule) so Coralie can end a chase by hand. Hides itself on error.
function needLabel(b) {
  const parts = [];
  if (b.needs_win) parts.push("share their win");
  if (b.needs_testimonial) parts.push("record a testimonial");
  return parts.length ? "needs to " + parts.join(" + ") : "done both";
}

export default function BossChaseSummary({ className = "" }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(null);
  const [backfill, setBackfill] = useState(null); // status message

  const load = useCallback(() => {
    apiClient.get("/students-db/bosses").then(({ data }) => setData(data)).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  const chaseAction = async (id, verb) => {
    setBusy(id);
    try {
      await apiClient.post(`/students-db/${id}/testimonial-chase/${verb}`);
      load();
    } catch (e) {
      // best-effort; leave the row as-is on failure
    } finally {
      setBusy(null);
    }
  };

  const runBackfill = async () => {
    if (!window.confirm("Backfill Boss badges from the Circle 'Boss' tag (no chase) and import recorded testimonials from Calendly? Safe to run once.")) return;
    setBackfill("running");
    try {
      await apiClient.post("/admin/boss/backfill");
    } catch (e) {
      setBackfill("failed (admins only) - " + (e.response?.status === 403 ? "needs an admin login" : "see logs"));
      return;
    }
    // Poll the status doc so we can see the actual result (counts + diagnostics).
    for (let i = 0; i < 24; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const { data } = await apiClient.get("/admin/boss/backfill/status");
        if (data.state === "done") {
          const b = data.result?.badges || {};
          const t = data.result?.testimonials || {};
          setBackfill(
            `Done. Badges: found ${b.boss_emails ?? "?"} Boss-tagged, set ${b.set ?? 0}, already ${b.already ?? 0}, not-found ${b.not_found ?? 0}. ` +
            `Testimonials: ${JSON.stringify(t)}` +
            (data.result?.testimonials_error ? ` ERROR: ${data.result.testimonials_error}` : "")
          );
          load();
          return;
        }
      } catch { /* keep polling */ }
    }
    setBackfill("still running - refresh in a minute.");
  };

  const rescanWins = async () => {
    setBackfill("running");
    try {
      await apiClient.post("/admin/boss-journey/scan");
      setBackfill("Rescanning the Share Your Wins channel (~1-2 min)… refresh shortly to see updated wins.");
      setTimeout(load, 90000);
    } catch (e) {
      setBackfill("rescan failed (admins only)");
    }
  };

  if (!data) return null;
  const c = data.counts || {};
  // Only the actionable list: recently-marked or actively-chased Bosses. The
  // historical backfill (hundreds) stays in the total count but isn't dumped here.
  const toChase = (data.bosses || []).filter((b) => !b.complete && b.chaseable);

  return (
    <div className={"rounded-lg border border-[var(--ayci-border)] bg-white p-4 " + className} data-testid="boss-chase-summary">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
          <Award className="w-3.5 h-3.5" /> Bosses to chase
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={rescanWins}
            disabled={backfill === "running"}
            className="text-[10px] px-2 py-0.5 rounded border border-[var(--ayci-border)] text-[var(--ayci-ink-muted)] hover:bg-slate-50 disabled:opacity-50"
            title="Re-scan the Share Your Wins channel now and update who's shared + the totals"
          >
            Rescan wins
          </button>
          <button
            type="button"
            onClick={runBackfill}
            disabled={backfill === "running"}
            className="text-[10px] px-2 py-0.5 rounded border border-[var(--ayci-border)] text-[var(--ayci-ink-muted)] hover:bg-slate-50 disabled:opacity-50"
            title="One-off: set Boss badges from the Circle tag (no chase) + import recorded testimonials from Calendly"
          >
            {backfill === "running" ? "Backfilling…" : "Backfill history"}
          </button>
        </div>
      </div>
      {backfill && backfill !== "running" && (
        <div className="text-[11px] text-[var(--ayci-ink-muted)] mb-2">{backfill}</div>
      )}
      <div className="flex flex-wrap gap-2 items-center mb-2">
        <span className="text-sm mr-1"><strong className="text-lg text-[var(--ayci-ink)]">{c.to_chase ?? toChase.length}</strong> to chase</span>
        <span className="text-xs text-[var(--ayci-ink-muted)] mr-1">of {c.total ?? 0} Bosses</span>
        <span className="text-xs px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">No win yet: <strong>{c.needs_win ?? 0}</strong></span>
        <span className="text-xs px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">No testimonial yet: <strong>{c.needs_testimonial ?? 0}</strong></span>
        <span className="text-xs px-2 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700">Did both: <strong>{c.complete ?? 0}</strong></span>
      </div>
      <div className="flex flex-wrap gap-2 items-center mb-2 text-xs text-[var(--ayci-ink-muted)]">
        <span className="uppercase tracking-wider text-[10px]">Across all {c.total ?? 0} Bosses:</span>
        <span className="px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">Wins shared: <strong>{c.wins_shared ?? 0}</strong></span>
        <span className="px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">Testimonials booked: <strong>{c.testimonials_booked ?? 0}</strong></span>
        <span className="px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">Recorded: <strong>{c.testimonials_recorded ?? 0}</strong></span>
      </div>
      {c.wins_total_posts != null && (
        <div className="flex flex-wrap gap-2 items-center mb-2 text-xs text-[var(--ayci-ink-muted)]">
          <span className="uppercase tracking-wider text-[10px]">Share Your Wins channel (everyone):</span>
          <span className="px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">Total win posts: <strong>{c.wins_total_posts}</strong></span>
          {c.wins_unique_sharers != null && (
            <span className="px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">People who shared: <strong>{c.wins_unique_sharers}</strong></span>
          )}
        </div>
      )}
      {toChase.length === 0 ? (
        <span className="text-xs text-[var(--ayci-ink-muted)]">Nothing to chase - every Boss is complete (or there are none yet).</span>
      ) : (
        <ul className="space-y-1 max-h-72 overflow-y-auto">
          {toChase.map((b) => (
            <li key={b.id} className="flex items-center justify-between gap-3 text-sm">
              <Link
                to={`/students?${b.email ? `email=${encodeURIComponent(b.email)}` : `name=${encodeURIComponent(b.name || "")}`}`}
                className="text-[var(--ayci-teal)] hover:underline truncate"
              >
                {b.name || b.email || "(unnamed)"}
              </Link>
              <span className="flex items-center gap-2 shrink-0">
                {b.chase_active && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-sky-50 border border-sky-200 text-sky-700" title="Testimonial reminder DMs sent so far">
                    chasing {b.chase_step ?? 0}/4
                  </span>
                )}
                {b.chase_stopped_reason === "replied" && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 border border-[var(--ayci-border)] text-[var(--ayci-ink-muted)]">replied</span>
                )}
                <span className="text-[11px] text-[var(--ayci-ink-muted)]">{needLabel(b)}</span>
                {b.chase_active ? (
                  <button
                    type="button"
                    onClick={() => chaseAction(b.id, "stop")}
                    disabled={busy === b.id}
                    className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--ayci-border)] text-[var(--ayci-ink-muted)] hover:bg-slate-50 disabled:opacity-50"
                    title="Stop the reminder DMs (they replied / handled manually)"
                  >
                    {busy === b.id ? "…" : "Stop"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => chaseAction(b.id, "start")}
                    disabled={busy === b.id}
                    className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--ayci-teal)]/40 text-[var(--ayci-teal)] hover:bg-teal-50 disabled:opacity-50"
                    title="Start the testimonial reminder DMs for this Boss"
                  >
                    {busy === b.id ? "…" : "Start chase"}
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
