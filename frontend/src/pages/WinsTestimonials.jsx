import { useState, useEffect, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { Award, RefreshCw, Search } from "lucide-react";

import { apiClient } from "@/lib/api";

// Coralie's Wins & Testimonials board: every Boss with where they are in the
// journey (win shared -> testimonial booked -> recorded), the channel-wide win
// totals, and per-Boss chase controls. Data comes from /students-db/bosses.
const FILTERS = [
  { key: "chase", label: "To chase" },
  { key: "win", label: "Needs to share win" },
  { key: "booking", label: "Needs to book" },
  { key: "recording", label: "Awaiting recording" },
  { key: "complete", label: "Complete" },
  { key: "all", label: "All Bosses" },
];

function Tick({ on, label }) {
  return on
    ? <span className="text-emerald-600" title={label}>✓</span>
    : <span className="text-slate-300" title={"not " + label}>–</span>;
}

export default function WinsTestimonials() {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("chase");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    apiClient.get("/students-db/bosses").then(({ data }) => setData(data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const chaseAction = async (id, verb) => {
    setBusy(id);
    try { await apiClient.post(`/students-db/${id}/testimonial-chase/${verb}`); load(); }
    catch { /* best effort */ } finally { setBusy(null); }
  };

  const rescanWins = async () => {
    setNote("Rescanning the Share Your Wins channel (~1-2 min)…");
    try {
      await apiClient.post("/admin/boss-journey/scan");
      setTimeout(() => { load(); setNote("Wins rescanned - refreshed."); }, 90000);
    } catch { setNote("Rescan failed (admins only)."); }
  };

  const c = data?.counts || {};
  const bosses = data?.bosses || [];

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return bosses.filter((b) => {
      if (s && !`${b.name || ""} ${b.email || ""}`.toLowerCase().includes(s)) return false;
      if (filter === "all") return true;
      if (filter === "complete") return b.complete;
      if (filter === "chase") return b.chaseable && !b.complete;
      return b.stuck === filter; // win / booking / recording
    });
  }, [bosses, filter, q]);

  if (!data) {
    return <div className="p-8 text-[var(--ayci-ink-muted)]">Loading…</div>;
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="wins-testimonials-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[11px] font-display font-semibold tracking-[0.25em] uppercase text-[var(--ayci-teal)]">Team</div>
          <h1 className="text-4xl font-display font-bold text-[var(--ayci-ink)] mt-1 flex items-center gap-2">
            <Award className="w-8 h-8 text-[var(--ayci-teal)]" /> Wins &amp; Testimonials
          </h1>
          <p className="text-[var(--ayci-ink-muted)] text-sm mt-1 max-w-2xl">
            Every Boss (substantive job) and where they are: shared their win → booked a testimonial → recorded it.
          </p>
        </div>
        <button
          type="button"
          onClick={rescanWins}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--ayci-border)] bg-white text-sm text-[var(--ayci-ink)] hover:bg-slate-50"
          title="Re-read the Share Your Wins channel and update who's shared + the totals"
        >
          <RefreshCw className="w-4 h-4" /> Rescan wins
        </button>
      </div>
      {note && <div className="text-xs text-[var(--ayci-ink-muted)]">{note}</div>}

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: "Bosses", value: c.total },
          { label: "Wins shared (Bosses)", value: c.wins_shared },
          { label: "Testimonials booked", value: c.testimonials_booked },
          { label: "Recorded", value: c.testimonials_recorded },
          { label: "Complete", value: c.complete, tone: "emerald" },
          { label: "To chase", value: c.to_chase, tone: "amber" },
        ].map((s) => (
          <div key={s.label} className={"rounded-lg border p-3 " + (s.tone === "emerald" ? "border-emerald-200 bg-emerald-50/50" : s.tone === "amber" ? "border-amber-200 bg-amber-50/50" : "border-[var(--ayci-border)] bg-white")}>
            <div className="text-2xl font-display font-bold text-[var(--ayci-ink)]">{s.value ?? 0}</div>
            <div className="text-[11px] text-[var(--ayci-ink-muted)] leading-tight">{s.label}</div>
          </div>
        ))}
      </div>
      {c.wins_total_posts != null && (
        <div className="text-xs text-[var(--ayci-ink-muted)]">
          Share Your Wins channel (everyone): <strong>{c.wins_total_posts}</strong> total win posts
          {c.wins_unique_sharers != null && <> from <strong>{c.wins_unique_sharers}</strong> people</>}.
        </div>
      )}

      {/* Filters + search */}
      <div className="flex flex-wrap gap-2 items-center">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={"px-3 py-1.5 rounded-full text-sm border " + (filter === f.key ? "bg-[var(--ayci-teal)] text-white border-transparent" : "bg-white border-[var(--ayci-border)] text-[var(--ayci-ink)] hover:bg-slate-50")}
          >
            {f.label}
          </button>
        ))}
        <div className="relative ml-auto">
          <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-[var(--ayci-ink-muted)]" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name / email…"
            className="pl-8 pr-3 py-1.5 border border-[var(--ayci-border)] rounded text-sm w-64"
          />
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-[var(--ayci-border)] rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)] border-b border-[var(--ayci-border)]">
                <th className="px-4 py-3">Boss</th>
                <th className="px-3 py-3 text-center">Win shared</th>
                <th className="px-3 py-3">Testimonial</th>
                <th className="px-3 py-3">Chase</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-6 text-center text-[var(--ayci-ink-muted)]">No Bosses in this view.</td></tr>
              ) : rows.map((b) => (
                <tr key={b.id} className="border-b border-[var(--ayci-border)] last:border-0">
                  <td className="px-4 py-3">
                    <Link to={`/students?${b.email ? `email=${encodeURIComponent(b.email)}` : `name=${encodeURIComponent(b.name || "")}`}`} className="text-[var(--ayci-teal)] hover:underline">
                      {b.name || b.email || "(unnamed)"}
                    </Link>
                    <div className="text-[11px] text-[var(--ayci-ink-muted)]">{b.email}</div>
                  </td>
                  <td className="px-3 py-3 text-center"><Tick on={b.win_shared} label="win shared" /></td>
                  <td className="px-3 py-3">
                    {b.testimonial_recorded ? (
                      <span className="text-emerald-700">Recorded</span>
                    ) : b.testimonial_booked ? (
                      <span className="text-sky-700">Booked{b.testimonial_booked_date ? ` · ${b.testimonial_booked_date}` : ""}</span>
                    ) : (
                      <span className="text-[var(--ayci-ink-muted)]">–</span>
                    )}
                    {b.testimonial_coach && <span className="text-[11px] text-[var(--ayci-ink-muted)]"> · {b.testimonial_coach}</span>}
                  </td>
                  <td className="px-3 py-3">
                    {b.chase_active
                      ? <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-sky-50 border border-sky-200 text-sky-700">chasing {b.chase_step ?? 0}/4</span>
                      : b.chase_stopped_reason
                        ? <span className="text-[11px] text-[var(--ayci-ink-muted)]">{b.chase_stopped_reason}</span>
                        : <span className="text-[11px] text-[var(--ayci-ink-muted)]">–</span>}
                  </td>
                  <td className="px-3 py-3 text-right">
                    {!b.complete && (b.chase_active ? (
                      <button type="button" onClick={() => chaseAction(b.id, "stop")} disabled={busy === b.id}
                        className="text-[11px] px-2 py-1 rounded border border-[var(--ayci-border)] text-[var(--ayci-ink-muted)] hover:bg-slate-50 disabled:opacity-50">
                        {busy === b.id ? "…" : "Stop"}
                      </button>
                    ) : (
                      <button type="button" onClick={() => chaseAction(b.id, "start")} disabled={busy === b.id}
                        className="text-[11px] px-2 py-1 rounded border border-[var(--ayci-teal)]/40 text-[var(--ayci-teal)] hover:bg-teal-50 disabled:opacity-50">
                        {busy === b.id ? "…" : "Start chase"}
                      </button>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="text-[11px] text-[var(--ayci-ink-muted)]">Showing {rows.length} of {c.total ?? 0} Bosses.</div>
    </div>
  );
}
