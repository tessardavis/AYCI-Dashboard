import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { Award } from "lucide-react";

import { apiClient } from "@/lib/api";

// "Bosses to chase" widget for the Boss Badge & testimonials process. Shows where
// each Boss is stuck in the journey (win shared -> booked -> recorded) and, for
// the dashboard-driven testimonial chase, how many reminder DMs have gone out -
// with a Stop control (the "Replied" rule) so Coralie can end a chase by hand.
// Hides itself on error.
const STUCK_LABEL = {
  win: "needs to share their win",
  booking: "needs to book the testimonial call",
  recording: "booked - awaiting the recording",
};

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
      setBackfill("started - this runs in the background (~1-2 min). Refresh to see updated counts.");
    } catch (e) {
      setBackfill("failed (admins only) - " + (e.response?.status === 403 ? "needs an admin login" : "see logs"));
    }
  };

  if (!data) return null;
  const c = data.counts || {};
  const toChase = (data.bosses || []).filter((b) => !b.complete);

  return (
    <div className={"rounded-lg border border-[var(--ayci-border)] bg-white p-4 " + className} data-testid="boss-chase-summary">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
          <Award className="w-3.5 h-3.5" /> Bosses to chase
        </div>
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
      {backfill && backfill !== "running" && (
        <div className="text-[11px] text-[var(--ayci-ink-muted)] mb-2">{backfill}</div>
      )}
      <div className="flex flex-wrap gap-2 items-center mb-2">
        <span className="text-sm mr-1"><strong className="text-lg text-[var(--ayci-ink)]">{c.total ?? 0}</strong> Bosses</span>
        <span className="text-xs px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">No win yet: <strong>{c.win ?? 0}</strong></span>
        <span className="text-xs px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">Not booked: <strong>{c.booking ?? 0}</strong></span>
        <span className="text-xs px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">Awaiting recording: <strong>{c.recording ?? 0}</strong></span>
        <span className="text-xs px-2 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700">Complete: <strong>{c.complete ?? 0}</strong></span>
      </div>
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
                <span className="text-[11px] text-[var(--ayci-ink-muted)]">{STUCK_LABEL[b.stuck] || b.stuck}</span>
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
