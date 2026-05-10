/* Private-Tier Video Submissions
 *
 * DB-backed (replaces Monday board 5083952249). Reads from
 * `private_video_submissions` collection. Tessa and Becky review submissions
 * and assign / reply / mark Done from this dashboard.
 *
 * New submissions arrive via Tally webhook (form 0Qr5py → POST
 * /api/private-videos/tally-webhook) — no Monday automation involved.
 */
import { useState, useEffect, useMemo } from "react";
import { Loader2, RefreshCw, ExternalLink, Search, MessageCircle, Video, Save, X, Send } from "lucide-react";
import { toast } from "sonner";
import { apiClient, formatApiErrorDetail, API } from "@/lib/api";
import { Button } from "@/components/ui/button";

const STATUS_OPTIONS = ["New", "Working on it", "Done", "Update name"];
const STATUS_TONE = {
  "New":            "bg-sky-100 text-sky-900 border-sky-300",
  "Working on it":  "bg-amber-100 text-amber-900 border-amber-300",
  "Done":           "bg-emerald-100 text-emerald-900 border-emerald-300",
  "Update name":    "bg-rose-100 text-rose-900 border-rose-300",
};

function formatUkDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  } catch {
    return iso;
  }
}

export default function PrivateVideos() {
  const [items, setItems] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncingMonday, setSyncingMonday] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [editing, setEditing] = useState(null); // currently-edited row
  const [fetchedAt, setFetchedAt] = useState(null);
  // Hide "Done" by default — clears the active backlog so the team only
  // sees what still needs attention. Toggleable.
  const [showDone, setShowDone] = useState(false);

  const load = async (force = false) => {
    setRefreshing(true);
    try {
      const [{ data: list }, { data: u }] = await Promise.all([
        apiClient.get(`/private-videos${force ? "?force=true" : ""}`, { timeout: 60000 }),
        apiClient.get("/private-videos/users", { timeout: 30000 }),
      ]);
      setItems(list.items || []);
      setFetchedAt(list.fetched_at);
      setUsers(u.users || []);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load private-tier videos");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    // First load: show whatever's in our DB instantly, then quietly sync
    // from Monday in the background so the count stays in lock-step with
    // the Monday board (which is the source of truth for replies right
    // now). The team gets a fresh-from-Monday view every time they open
    // this page, no manual button click needed.
    (async () => {
      await load();
      try {
        setSyncingMonday(true);
        const { data } = await apiClient.post(
          "/private-videos/sync-from-monday",
          {},
          { timeout: 180000 },
        );
        if ((data?.created ?? 0) > 0 || (data?.updated ?? 0) > 0) {
          await load(true);
        }
      } catch {
        // Silent — initial load was already successful, this is just a refresh
      } finally {
        setSyncingMonday(false);
      }
    })();
  }, []);

  const syncFromMonday = async () => {
    setSyncingMonday(true);
    try {
      const { data } = await apiClient.post("/private-videos/sync-from-monday", {}, { timeout: 180000 });
      const created = data?.created ?? 0;
      const updated = data?.updated ?? 0;
      toast.success(
        created === 0 && updated === 0
          ? "Already in sync with Monday"
          : `Synced from Monday — ${created} new, ${updated} updated`,
      );
      await load(true);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Sync from Monday failed");
    } finally {
      setSyncingMonday(false);
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = items.filter((it) => {
      // Hide Done by default — user can toggle the chip below to bring them
      // back when searching historical submissions. Explicit status filter
      // (e.g. user picks "Done") always wins.
      if (!statusFilter && !showDone && (it.status || "").toLowerCase() === "done") return false;
      if (statusFilter && it.status !== statusFilter) return false;
      if (assigneeFilter === "_unassigned" && it.assignee_id) return false;
      if (assigneeFilter && assigneeFilter !== "_unassigned" && it.assignee_id !== assigneeFilter) return false;
      if (q) {
        const hay = `${it.first_name || ""} ${it.last_name || ""} ${it.email || ""} ${it.question || ""} ${it.name || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    // Oldest submission first — the longest-waiting student rises to the top
    // so the team naturally clears the queue in fairness order.
    rows.sort((a, b) => {
      const ax = a.submitted ? new Date(a.submitted).getTime() : 0;
      const bx = b.submitted ? new Date(b.submitted).getTime() : 0;
      return ax - bx;
    });
    return rows;
  }, [items, search, statusFilter, assigneeFilter, showDone]);

  const counts = useMemo(() => {
    const c = { total: items.length, new: 0, working: 0, done: 0 };
    for (const it of items) {
      const s = (it.status || "").toLowerCase();
      if (s === "new") c.new++;
      else if (s === "working on it") c.working++;
      else if (s === "done") c.done++;
    }
    return c;
  }, [items]);

  return (
    <div className="p-4 lg:p-10 max-w-[1700px] mx-auto" data-testid="private-videos-page">
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <h1 className="font-display text-2xl lg:text-3xl font-extrabold tracking-tight text-[var(--ayci-ink)]">
          Private-Tier Videos
        </h1>
        <div className="flex items-center gap-2">
          {fetchedAt && (
            <span className="text-[11px] text-[var(--ayci-ink-muted)]">
              Updated · {formatUkDate(fetchedAt)}
            </span>
          )}
          <Button variant="outline" size="sm" onClick={syncFromMonday} disabled={syncingMonday} data-testid="pv-sync-monday" title="Pull new submissions from the Monday board (preserves your edits in this dashboard)">
            {syncingMonday ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1.5" />}
            Sync from Monday
          </Button>
          <Button variant="outline" size="sm" onClick={() => load(true)} disabled={refreshing} data-testid="pv-refresh">
            {refreshing ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1.5" />}
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <StatPill label="Total" value={counts.total} tone="slate" />
        <StatPill label="New" value={counts.new} tone="sky" />
        <StatPill label="Working" value={counts.working} tone="amber" />
        <button
          type="button"
          onClick={() => setShowDone((v) => !v)}
          title={showDone ? "Hide Done from the list" : "Show Done in the list"}
          className="focus:outline-none"
          data-testid="pv-toggle-done"
        >
          <StatPill
            label={showDone ? "Done · shown" : "Done · hidden"}
            value={counts.done}
            tone={showDone ? "emerald" : "slate"}
          />
        </button>
      </div>

      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-2.5 mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text" placeholder="Search name, email, question…"
            value={search} onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 border border-slate-200 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]"
            data-testid="pv-search"
          />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="px-2 py-1.5 border border-slate-200 rounded text-sm" data-testid="pv-status-filter">
          <option value="">All status</option>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={assigneeFilter} onChange={(e) => setAssigneeFilter(e.target.value)} className="px-2 py-1.5 border border-slate-200 rounded text-sm" data-testid="pv-assignee-filter">
          <option value="">All assignees</option>
          <option value="_unassigned">Unassigned</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </select>
      </div>

      {loading ? (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-12 text-center text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
          Loading…
        </div>
      ) : items.length === 0 ? (
        <EmptyStateMigrate onMigrated={() => load(true)} />
      ) : (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] border-b border-[var(--ayci-border)]">
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 font-semibold">Submission</th>
                <th className="px-3 py-2 font-semibold">Question</th>
                <th className="px-3 py-2 font-semibold whitespace-nowrap">Submitted</th>
                <th className="px-3 py-2 font-semibold">Assignee</th>
                <th className="px-3 py-2 font-semibold">Replied</th>
                <th className="px-3 py-2 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-[var(--ayci-ink-muted)] italic">
                    No submissions match the current filters.
                  </td>
                </tr>
              ) : filtered.map((it) => (
                <Row key={it.id} item={it} users={users} onEdit={() => setEditing(it)} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <EditModal
          item={editing}
          users={users}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load(true);
          }}
        />
      )}
    </div>
  );
}

function StatPill({ label, value, tone }) {
  const cls = {
    slate: "bg-slate-100 border-slate-200 text-slate-800",
    sky: "bg-sky-100 border-sky-200 text-sky-900",
    amber: "bg-amber-100 border-amber-200 text-amber-900",
    emerald: "bg-emerald-100 border-emerald-200 text-emerald-900",
  }[tone];
  return (
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 border rounded-full text-xs font-semibold ${cls}`}>
      <span className="opacity-75">{label}</span>
      <span className="text-sm font-bold">{value}</span>
    </div>
  );
}

function EmptyStateMigrate({ onMigrated }) {
  const [migrating, setMigrating] = useState(false);
  const run = async () => {
    if (!window.confirm("Pull all 462 submissions from the Monday board into the dashboard? Safe to re-run.")) return;
    setMigrating(true);
    try {
      const { data } = await apiClient.post("/private-videos/migrate-from-monday", {}, { timeout: 180000 });
      toast.success(`Migrated · created ${data.created} · updated ${data.updated}`);
      onMigrated();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Migration failed");
    } finally {
      setMigrating(false);
    }
  };
  return (
    <div
      className="bg-gradient-to-br from-violet-50 via-white to-sky-50 border-2 border-dashed border-violet-300 rounded-xl p-10 text-center"
      data-testid="pv-empty-migrate"
    >
      <Video className="w-12 h-12 text-violet-500 mx-auto mb-4" />
      <h2 className="font-display text-xl font-extrabold text-[var(--ayci-ink)] mb-2">
        No submissions yet
      </h2>
      <p className="text-sm text-[var(--ayci-ink-muted)] max-w-md mx-auto mb-6">
        Pull existing private-tier video submissions from the Monday board into
        this dashboard. After migrating, point the Tally webhook here and the
        Monday board can be retired.
      </p>
      <Button
        onClick={run}
        disabled={migrating}
        data-testid="pv-migrate-btn"
      >
        {migrating ? (
          <>
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            Migrating from Monday…
          </>
        ) : (
          <>
            <RefreshCw className="w-4 h-4 mr-2" />
            Migrate from Monday board
          </>
        )}
      </Button>
    </div>
  );
}

function Row({ item, users, onEdit }) {
  const assignee = item.assignee_name || (users.find((u) => u.id === item.assignee_id) || {}).name || null;
  const tally = item.tally_video?.url || item.video?.url;
  const reply = item.reply_link?.url;
  const studentName = `${item.first_name || ""} ${item.last_name || ""}`.trim() || item.name;
  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50/40">
      <td className="px-3 py-2.5">
        <span className={`inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${STATUS_TONE[item.status] || "bg-slate-100 text-slate-800 border-slate-300"}`}>
          {item.status || "—"}
        </span>
      </td>
      <td className="px-3 py-2.5">
        <div className="font-semibold text-[var(--ayci-ink)]">{studentName}</div>
        <div className="text-[11px] text-[var(--ayci-ink-muted)]">
          {item.submission_number}/{item.total_allowance} · {item.email || "no email"}
        </div>
      </td>
      <td className="px-3 py-2.5 max-w-[300px]">
        <div className="text-sm text-[var(--ayci-ink)] line-clamp-2">{item.question || "—"}</div>
      </td>
      <td className="px-3 py-2.5 text-[11px] text-[var(--ayci-ink-muted)] whitespace-nowrap">
        {item.submitted ? formatUkDate(item.submitted) : "—"}
      </td>
      <td className="px-3 py-2.5">
        {assignee ? (
          <span className="text-xs px-1.5 py-0.5 rounded bg-sky-100 text-sky-800 font-semibold">{assignee}</span>
        ) : (
          <span className="text-xs text-amber-700 italic">unassigned</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-[11px] text-[var(--ayci-ink-muted)] whitespace-nowrap">
        {item.replied ? formatUkDate(item.replied) : "—"}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-1.5 flex-wrap">
          {tally && (
            <a href={tally} target="_blank" rel="noreferrer" className="text-xs text-rose-700 hover:underline flex items-center gap-0.5" title="Watch the student's video">
              <Video className="w-3 h-3" /> Video
            </a>
          )}
          {reply && (
            <a href={reply} target="_blank" rel="noreferrer" className="text-xs text-emerald-700 hover:underline flex items-center gap-0.5" title="Coach voicenote reply">
              <MessageCircle className="w-3 h-3" /> Reply
            </a>
          )}
          {item.private_chat && (
            <a href={item.private_chat} target="_blank" rel="noreferrer" className="text-xs text-sky-700 hover:underline flex items-center gap-0.5" title="Open Circle DM thread">
              <ExternalLink className="w-3 h-3" /> Circle
            </a>
          )}
          <button
            onClick={onEdit}
            className="text-xs px-2 py-0.5 rounded border border-slate-200 hover:bg-slate-100 font-semibold text-slate-700"
            data-testid={`pv-edit-${item.id}`}
          >
            Edit
          </button>
        </div>
      </td>
    </tr>
  );
}

function EditModal({ item, users, onClose, onSaved }) {
  const [statusLabel, setStatusLabel] = useState(item.status || "");
  const [assigneeId, setAssigneeId] = useState(item.assignee_id || "");
  const [replied, setReplied] = useState((item.replied || "").slice(0, 10));
  const [replyLink, setReplyLink] = useState(item.reply_link?.url || "");
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.patch(`/private-videos/${item.id}`, {
        status_label: statusLabel,
        assignee_id: assigneeId || "",
        replied: replied || null,
        reply_link: replyLink,
      });
      toast.success("Saved");
      onSaved();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const sendToCircle = async () => {
    const url = (replyLink || "").trim();
    if (!url) {
      toast.error("Add the voicenote URL first");
      return;
    }
    if (!window.confirm(
      `Post this voicenote to ${item.first_name || item.name}'s Circle Group DM via Zapier?\n\n${url}\n\nThis can't be undone.`
    )) return;
    setSending(true);
    try {
      // Save first so the URL is persisted on the row before the webhook fires
      await apiClient.patch(`/private-videos/${item.id}`, {
        status_label: statusLabel,
        assignee_id: assigneeId || "",
        replied: replied || null,
        reply_link: url,
      });
      await apiClient.post(`/private-videos/${item.id}/send-to-circle`);
      toast.success("Sent to Circle ✓ — marked Done");
      onSaved();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-end lg:items-center justify-center p-2 lg:p-6" onClick={onClose}>
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[92vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-slate-200 flex items-start justify-between gap-3">
          <div>
            <div className="font-display text-lg font-extrabold text-[var(--ayci-ink)]">{item.name}</div>
            <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-0.5">
              {item.email} · video {item.submission_number}/{item.total_allowance}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-4 space-y-4">
          {item.question && (
            <div>
              <Label>Question</Label>
              <div className="text-sm bg-slate-50 border border-slate-200 rounded p-2.5 text-[var(--ayci-ink)]">
                {item.question}
              </div>
            </div>
          )}
          {(item.tally_video?.url || item.video?.url) && (
            <div>
              <Label>Student video</Label>
              <InlineVideo itemId={item.id} fallbackUrl={item.tally_video?.url || item.video?.url} />
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <Label>Status</Label>
              <select value={statusLabel} onChange={(e) => setStatusLabel(e.target.value)} className={inputCls} data-testid="pv-edit-status">
                {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <Label>Assignee</Label>
              <select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)} className={inputCls} data-testid="pv-edit-assignee">
                <option value="">Unassigned</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </div>
            <div>
              <Label>Replied date</Label>
              <input type="date" value={replied} onChange={(e) => setReplied(e.target.value)} className={inputCls} data-testid="pv-edit-replied" />
            </div>
            <div>
              <Label>Reply link (voicenote URL)</Label>
              <input
                type="url"
                value={replyLink}
                onChange={(e) => setReplyLink(e.target.value)}
                placeholder="https://www.voicenotes.com/s/…"
                className={inputCls}
                data-testid="pv-edit-reply"
              />
            </div>
          </div>

          {item.private_chat && (
            <div className="text-xs text-[var(--ayci-ink-muted)] bg-sky-50 border border-sky-200 rounded p-2 flex items-start gap-2">
              <MessageCircle className="w-3.5 h-3.5 text-sky-700 mt-0.5 shrink-0" />
              <div>
                Clicking <strong>Send to Circle</strong> below posts the voicenote to{" "}
                <a href={item.private_chat} target="_blank" rel="noreferrer" className="text-sky-700 font-semibold hover:underline">
                  this Circle Group DM
                </a>{" "}
                via Zapier and marks the submission Done.
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100 flex-wrap">
            <Button variant="outline" onClick={onClose} disabled={saving || sending}>Cancel</Button>
            <Button
              variant="outline"
              onClick={save}
              disabled={saving || sending}
              data-testid="pv-edit-save"
            >
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Save
            </Button>
            <Button
              onClick={sendToCircle}
              disabled={saving || sending || !replyLink.trim()}
              className="bg-emerald-600 hover:bg-emerald-700 text-white"
              data-testid="pv-edit-send-circle"
              title={!replyLink.trim() ? "Add the voicenote URL first" : "Save + post to Circle Group DM via Zapier"}
            >
              {sending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
              Send to Circle
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Label({ children }) {
  return <div className="text-[10px] uppercase tracking-wider font-bold text-[var(--ayci-ink-muted)] mb-1">{children}</div>;
}
const inputCls = "w-full px-3 py-1.5 border border-slate-200 rounded text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]";

// Inline `<video>` so coaches can watch on mobile + desktop without
// leaving the app. Backend pipeline:
//   1. download from Tally → disk
//   2. detect codec; if HEVC (iPhone default), transcode → H.264
//   3. serve from disk with proper Range support
// First load takes ~30-90s (download + transcode); we poll the status
// endpoint and show progress so the user knows it's working.
function InlineVideo({ itemId, fallbackUrl }) {
  const [errored, setErrored] = useState(false);
  const [status, setStatus] = useState("loading");
  const proxyUrl = `${API}/private-videos/${itemId}/video`;

  useEffect(() => {
    let cancelled = false;
    let pollTimer = null;
    const poll = async () => {
      try {
        const { data } = await apiClient.get(`/private-videos/${itemId}/video/status`);
        if (cancelled) return;
        setStatus(data.status);
        if (data.status === "ready") return;
        if (data.status === "error" || data.status === "no_video") return;
        pollTimer = setTimeout(poll, 3000);
      } catch {
        if (!cancelled) {
          setStatus("error");
        }
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [itemId]);

  if (errored || status === "error" || status === "no_video") {
    // Fallback when the inline `<video>` can't decode (rare — old browser
    // missing codecs). The proxy URL works as a navigation target since
    // the file's already cached + transcoded server-side.
    const downloadUrl = errored ? proxyUrl : fallbackUrl;
    return (
      <a
        href={downloadUrl}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 text-sm text-rose-700 hover:underline font-semibold"
        data-testid="pv-video-fallback"
      >
        <Video className="w-4 h-4" /> Open video in new tab
      </a>
    );
  }

  if (status !== "ready") {
    const labels = {
      loading: { title: "Loading…", sub: "" },
      missing: { title: "Preparing video…", sub: "Starting download from Tally" },
      downloading: { title: "Downloading from Tally…", sub: "First load only — usually 10-30s" },
      downloaded: { title: "Almost ready…", sub: "Optimising for your browser" },
      transcoding: { title: "Optimising for your browser…", sub: "Converting iPhone HEVC → universal H.264 (~60-90s)" },
    };
    const l = labels[status] || labels.loading;
    return (
      <div
        className="w-full aspect-video rounded-md bg-slate-100 border border-slate-200 flex flex-col items-center justify-center gap-2 text-[var(--ayci-ink-muted)] px-4 text-center"
        data-testid="pv-video-warming"
      >
        <Loader2 className="w-6 h-6 animate-spin text-[var(--ayci-accent)]" />
        <div className="text-xs font-semibold text-[var(--ayci-ink)]">{l.title}</div>
        {l.sub && <div className="text-[10px]">{l.sub}</div>}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <video
        src={proxyUrl}
        controls
        playsInline
        preload="metadata"
        className="w-full max-h-[60vh] rounded-md bg-black"
        onError={() => setErrored(true)}
        data-testid="pv-video-player"
      >
        Your browser can't play this video.
      </video>
      <a
        href={fallbackUrl}
        target="_blank"
        rel="noreferrer"
        className="text-[11px] text-[var(--ayci-ink-muted)] hover:text-rose-700 hover:underline inline-flex items-center gap-1"
      >
        <ExternalLink className="w-3 h-3" /> Open original (HEVC)
      </a>
    </div>
  );
}
