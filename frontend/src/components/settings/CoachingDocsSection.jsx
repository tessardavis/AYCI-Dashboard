import { useState } from "react";
import { FileText, Loader2 } from "lucide-react";

import { apiClient, formatApiErrorDetail } from "@/lib/api";

// Admin tool: ensure every private-tier student has a correctly-named coaching doc.
// Preview is read-only (shows the plan); Run writes (create/adopt/rename) - fuzzy
// matches are left flagged for manual review, never auto-touched.
export default function CoachingDocsSection({ isAdmin }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  if (!isAdmin) return null;

  const preview = async () => {
    setBusy(true);
    setNote("Scanning private-tier students + the Drive folder…");
    try {
      const { data } = await apiClient.post("/admin/coaching-docs/ensure?dry_run=true", {}, { timeout: 60000 });
      setResult(data);
      setNote("Preview only - nothing was changed.");
    } catch (e) {
      setNote("Preview failed: " + (formatApiErrorDetail(e.response?.data?.detail) || e.message));
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    if (!window.confirm("Create/adopt/rename coaching docs for real? Uncertain (fuzzy) matches are left for you to review - not touched.")) return;
    setBusy(true);
    setNote("Running backfill in the background…");
    try {
      await apiClient.post("/admin/coaching-docs/ensure?dry_run=false", {}, { timeout: 30000 });
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const { data } = await apiClient.get("/admin/coaching-docs/ensure/status");
        if (data.state === "done") { setResult(data.result); setNote("Backfill complete."); return; }
        if (data.state === "error") { setNote("Backfill error: " + data.error); return; }
      }
      setNote("Still running - check back shortly.");
    } catch (e) {
      setNote("Backfill failed: " + (formatApiErrorDetail(e.response?.data?.detail) || e.message));
    } finally {
      setBusy(false);
    }
  };

  const c = result?.counts || {};
  const flagged = result?.flagged || [];

  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6 mt-4" data-testid="coaching-docs-section">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg bg-teal-50 border border-teal-200 flex items-center justify-center text-teal-700 shrink-0">
          <FileText className="w-5 h-5" />
        </div>
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">Private-tier coaching docs</h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-1 max-w-2xl">
            Ensures every private-tier student has a Google Doc (named <em>Name - Specialty - Type - Date</em>)
            for coaches to keep call notes in. <strong>Preview</strong> is read-only; <strong>Run</strong> creates missing
            docs, adopts + renames confident matches, and flags uncertain ones for you to check.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button type="button" onClick={preview} disabled={busy}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--ayci-border)] bg-white text-sm hover:bg-slate-50 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : null} Preview (read-only)
        </button>
        <button type="button" onClick={run} disabled={busy}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--ayci-teal)] text-white text-sm hover:opacity-90 disabled:opacity-50">
          Run backfill
        </button>
      </div>
      {note && <div className="text-xs text-[var(--ayci-ink-muted)] mt-2">{note}</div>}

      {result && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">Scanned: <strong>{result.scanned ?? 0}</strong></span>
            <span className="px-2 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700">Create: <strong>{c.created ?? 0}</strong></span>
            <span className="px-2 py-1 rounded-full bg-sky-50 border border-sky-200 text-sky-700">Adopt+rename: <strong>{c.adopted ?? 0}</strong></span>
            <span className="px-2 py-1 rounded-full bg-sky-50 border border-sky-200 text-sky-700">Rename: <strong>{c.renamed ?? 0}</strong></span>
            <span className="px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">Already OK: <strong>{c.ok ?? 0}</strong></span>
            <span className="px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700">Flagged: <strong>{c.flagged ?? 0}</strong></span>
            {c.errors ? <span className="px-2 py-1 rounded-full bg-rose-50 border border-rose-200 text-rose-700">Errors: <strong>{c.errors}</strong></span> : null}
          </div>
          {flagged.length > 0 && (
            <div className="text-xs">
              <div className="uppercase tracking-wider text-[10px] text-[var(--ayci-ink-muted)] mb-1">Flagged - uncertain match, review by hand:</div>
              <ul className="space-y-0.5 max-h-56 overflow-y-auto">
                {flagged.map((f) => (
                  <li key={f.id} className="text-[var(--ayci-ink-muted)]">
                    <strong className="text-[var(--ayci-ink)]">{f.name}</strong> - maybe "{f.maybe_doc}" ({f.reason} {f.score}) → would title "{f.would_title}"
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
