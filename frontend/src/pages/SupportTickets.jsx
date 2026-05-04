import { useEffect, useMemo, useState } from "react";
import {
  LifeBuoy,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  X,
  AlertTriangle,
  Clock,
  Send,
  Mail,
  ExternalLink,
  Filter,
  LayoutGrid,
  Rows,
  MessageCircle,
} from "lucide-react";
import { toast } from "sonner";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import PageHeader from "@/components/PageHeader";
import { Button } from "@/components/ui/button";

const STATUSES = [
  { value: "open", label: "Open", chip: "bg-rose-50 text-rose-800 border-rose-200" },
  { value: "in_progress", label: "In Progress", chip: "bg-amber-50 text-amber-800 border-amber-200" },
  { value: "waiting", label: "Waiting on Student", chip: "bg-violet-50 text-violet-800 border-violet-200" },
  { value: "resolved", label: "Resolved", chip: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  { value: "closed", label: "Closed", chip: "bg-slate-100 text-slate-700 border-slate-300" },
];
const STATUS_META = Object.fromEntries(STATUSES.map((s) => [s.value, s]));

const PRIORITIES = [
  { value: "urgent", label: "Urgent", chip: "bg-rose-600 text-white border-rose-700" },
  { value: "high", label: "High", chip: "bg-orange-100 text-orange-900 border-orange-300" },
  { value: "medium", label: "Medium", chip: "bg-sky-100 text-sky-900 border-sky-300" },
  { value: "low", label: "Low", chip: "bg-slate-100 text-slate-700 border-slate-300" },
];
const PRIORITY_META = Object.fromEntries(PRIORITIES.map((p) => [p.value, p]));

const CATEGORIES = [
  { value: "billing", label: "Billing" },
  { value: "tech", label: "Tech" },
  { value: "coaching", label: "Coaching" },
  { value: "refund", label: "Refund" },
  { value: "other", label: "Other" },
];

const SOURCE_LABEL = { manual: "Manual", tally: "Form", email: "Email", whatsapp: "WhatsApp" };

function formatUk(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  });
}

function relativeAge(iso) {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const h = Math.floor(ms / 3600000);
  if (h < 1) return `${Math.max(1, Math.floor(ms / 60000))}m ago`;
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export default function SupportTickets() {
  const { user } = useAuth();
  const [tickets, setTickets] = useState([]);
  const [team, setTeam] = useState([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState("kanban"); // "kanban" | "table"
  const [search, setSearch] = useState("");
  const [filterPriority, setFilterPriority] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [filterAssignee, setFilterAssignee] = useState("");
  const [mineOnly, setMineOnly] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [activeId, setActiveId] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const myTeamId = user?.team_member_id || null;
  const teamById = useMemo(() => Object.fromEntries(team.map((t) => [t.id, t])), [team]);

  const load = async () => {
    setLoading(true);
    try {
      const [tRes, teamRes] = await Promise.all([
        apiClient.get("/tickets"),
        apiClient.get("/team"),
      ]);
      setTickets(tRes.data.tickets || []);
      setTeam(teamRes.data || []);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load tickets");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return tickets.filter((t) => {
      if (filterPriority && t.priority !== filterPriority) return false;
      if (filterCategory && t.category !== filterCategory) return false;
      if (filterAssignee === "_unassigned" && t.assignee_id) return false;
      if (filterAssignee && filterAssignee !== "_unassigned" && t.assignee_id !== filterAssignee) return false;
      if (mineOnly) {
        if (!myTeamId) return false;
        if (t.assignee_id !== myTeamId) return false;
      }
      if (q) {
        const hay = `${t.student_name} ${t.student_email} ${t.subject} ${t.description}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [tickets, search, filterPriority, filterCategory, filterAssignee, mineOnly, myTeamId]);

  const grouped = useMemo(() => {
    const out = Object.fromEntries(STATUSES.map((s) => [s.value, []]));
    filtered.forEach((t) => {
      if (out[t.status]) out[t.status].push(t);
    });
    return out;
  }, [filtered]);

  const counts = useMemo(() => {
    const open = tickets.filter((t) => ["open", "in_progress", "waiting"].includes(t.status));
    return {
      total_open: open.length,
      overdue: open.filter((t) => t.overdue).length,
      urgent: open.filter((t) => t.priority === "urgent").length,
      mine: myTeamId
        ? tickets.filter(
            (t) =>
              t.assignee_id === myTeamId &&
              ["open", "in_progress", "waiting"].includes(t.status),
          ).length
        : 0,
    };
  }, [tickets, myTeamId]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const { data } = await apiClient.post("/tickets/tally/sync");
      toast.success(`Tally sync: ${data.inserted} new ticket${data.inserted === 1 ? "" : "s"} (scanned ${data.scanned})`);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Tally sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const updateTicket = async (id, patch) => {
    try {
      const { data } = await apiClient.patch(`/tickets/${id}`, patch);
      setTickets((prev) => prev.map((t) => (t.id === id ? data : t)));
      return data;
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Update failed");
    }
  };

  const handleCreate = async (form) => {
    try {
      const { data } = await apiClient.post("/tickets", form);
      setTickets((prev) => [data, ...prev]);
      setCreateOpen(false);
      toast.success("Ticket created");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Create failed");
    }
  };

  const activeTicket = tickets.find((t) => t.id === activeId);

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="support-tickets-page">
      <PageHeader
        eyebrow="Customer Service"
        title="Support Tickets"
        description="Triage student issues across manual entry, the AYCI Support Desk Tally form, and (Phase 2) inbox auto-pull. Slack pings on Urgent. Per-priority SLA: 4h Urgent · 24h High · 48h Medium · 5d Low."
        right={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleSync}
              disabled={syncing}
              data-testid="tickets-sync-tally"
            >
              {syncing ? (
                <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4 mr-1.5" />
              )}
              Sync Tally
            </Button>
            <Button onClick={() => setCreateOpen(true)} size="sm" data-testid="tickets-new-button">
              <Plus className="w-4 h-4 mr-1.5" />
              New ticket
            </Button>
          </div>
        }
      />

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <StatCard label="Open" value={counts.total_open} tone="slate" testid="ticket-stat-open" />
        <StatCard
          label="Overdue (SLA breach)"
          value={counts.overdue}
          tone={counts.overdue > 0 ? "rose" : "emerald"}
          testid="ticket-stat-overdue"
          icon={AlertTriangle}
        />
        <StatCard
          label="Urgent"
          value={counts.urgent}
          tone={counts.urgent > 0 ? "rose" : "slate"}
          testid="ticket-stat-urgent"
        />
        <StatCard label="Assigned to me" value={counts.mine} tone="sky" testid="ticket-stat-mine" />
      </div>

      {/* Toolbar */}
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-3 mb-5 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--ayci-ink-muted)]" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search subject, student, email…"
            className="w-full pl-9 pr-3 py-2 text-sm border border-[var(--ayci-border)] rounded-md focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]/40"
            data-testid="tickets-search-input"
          />
        </div>
        <Select
          value={filterPriority}
          onChange={setFilterPriority}
          placeholder="All priorities"
          options={PRIORITIES.map((p) => ({ value: p.value, label: p.label }))}
          testid="tickets-filter-priority"
        />
        <Select
          value={filterCategory}
          onChange={setFilterCategory}
          placeholder="All categories"
          options={CATEGORIES}
          testid="tickets-filter-category"
        />
        <Select
          value={filterAssignee}
          onChange={setFilterAssignee}
          placeholder="All assignees"
          options={[
            { value: "_unassigned", label: "Unassigned" },
            ...team.map((t) => ({ value: t.id, label: t.name })),
          ]}
          testid="tickets-filter-assignee"
        />
        <label
          className={[
            "flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-md border cursor-pointer transition-colors",
            mineOnly
              ? "bg-[var(--ayci-accent)] text-white border-[var(--ayci-accent)]"
              : "bg-white text-[var(--ayci-ink-muted)] border-[var(--ayci-border)] hover:border-[var(--ayci-accent)]",
          ].join(" ")}
          data-testid="tickets-mine-only-toggle"
        >
          <input
            type="checkbox"
            checked={mineOnly}
            onChange={(e) => setMineOnly(e.target.checked)}
            className="hidden"
          />
          My tickets
        </label>
        <div className="ml-auto flex items-center gap-1 bg-slate-100 rounded-md p-0.5">
          <button
            onClick={() => setView("kanban")}
            data-testid="tickets-view-kanban"
            className={[
              "flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded transition-colors",
              view === "kanban" ? "bg-white shadow-sm text-[var(--ayci-ink)]" : "text-[var(--ayci-ink-muted)]",
            ].join(" ")}
          >
            <LayoutGrid className="w-3.5 h-3.5" />
            Kanban
          </button>
          <button
            onClick={() => setView("table")}
            data-testid="tickets-view-table"
            className={[
              "flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded transition-colors",
              view === "table" ? "bg-white shadow-sm text-[var(--ayci-ink)]" : "text-[var(--ayci-ink-muted)]",
            ].join(" ")}
          >
            <Rows className="w-3.5 h-3.5" />
            Table
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-sm text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading tickets…
        </div>
      ) : view === "kanban" ? (
        <KanbanBoard
          grouped={grouped}
          teamById={teamById}
          onOpen={setActiveId}
          onUpdate={updateTicket}
        />
      ) : (
        <TicketTable rows={filtered} teamById={teamById} onOpen={setActiveId} />
      )}

      {createOpen && (
        <CreateTicketModal team={team} onClose={() => setCreateOpen(false)} onSubmit={handleCreate} />
      )}
      {activeTicket && (
        <TicketDetailModal
          key={activeTicket.id}
          ticket={activeTicket}
          team={team}
          onClose={() => setActiveId(null)}
          onUpdate={updateTicket}
          onRefresh={load}
        />
      )}
    </div>
  );
}

// -------------------- Subcomponents --------------------

function StatCard({ label, value, tone, icon: Icon, testid }) {
  const toneCls = {
    slate: "bg-slate-50 border-slate-200 text-slate-900",
    rose: "bg-rose-50 border-rose-200 text-rose-900",
    emerald: "bg-emerald-50 border-emerald-200 text-emerald-900",
    sky: "bg-sky-50 border-sky-200 text-sky-900",
  }[tone || "slate"];
  return (
    <div className={`border rounded-lg p-3 ${toneCls}`} data-testid={testid}>
      <div className="text-[11px] uppercase tracking-wider font-semibold opacity-70 flex items-center gap-1">
        {Icon && <Icon className="w-3.5 h-3.5" />}
        {label}
      </div>
      <div className="text-2xl font-bold mt-1">{value}</div>
    </div>
  );
}

function Select({ value, onChange, placeholder, options, testid }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      data-testid={testid}
      className="text-sm border border-[var(--ayci-border)] rounded-md px-2.5 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]/40"
    >
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function PriorityChip({ priority }) {
  const meta = PRIORITY_META[priority] || PRIORITY_META.medium;
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 text-[10px] uppercase tracking-wider font-bold rounded border ${meta.chip}`}
      data-testid={`ticket-priority-chip-${priority}`}
    >
      {meta.label}
    </span>
  );
}

function StatusChip({ status }) {
  const meta = STATUS_META[status] || STATUS_META.open;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-[11px] font-semibold rounded border ${meta.chip}`}
      data-testid={`ticket-status-chip-${status}`}
    >
      {meta.label}
    </span>
  );
}

function KanbanBoard({ grouped, teamById, onOpen, onUpdate }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3" data-testid="tickets-kanban">
      {STATUSES.map((s) => (
        <div key={s.value} className="bg-slate-50 border border-slate-200 rounded-lg flex flex-col min-h-[300px]">
          <div className={`px-3 py-2 border-b border-slate-200 flex items-center justify-between rounded-t-lg ${s.chip}`}>
            <span className="text-xs font-semibold uppercase tracking-wider">{s.label}</span>
            <span className="text-xs font-bold">{grouped[s.value].length}</span>
          </div>
          <div className="p-2 space-y-2 flex-1 overflow-y-auto max-h-[70vh]">
            {grouped[s.value].length === 0 ? (
              <div className="text-center text-xs text-slate-400 py-6">—</div>
            ) : (
              grouped[s.value].map((t) => (
                <KanbanCard
                  key={t.id}
                  ticket={t}
                  teamById={teamById}
                  onOpen={() => onOpen(t.id)}
                  onUpdate={onUpdate}
                />
              ))
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function KanbanCard({ ticket, teamById, onOpen, onUpdate }) {
  const assignee = ticket.assignee_id ? teamById[ticket.assignee_id] : null;
  return (
    <div
      onClick={onOpen}
      className={[
        "bg-white border rounded-md p-2.5 cursor-pointer hover:shadow-md transition-shadow text-sm group",
        ticket.overdue ? "border-rose-300 ring-1 ring-rose-200" : "border-slate-200",
      ].join(" ")}
      data-testid={`ticket-card-${ticket.id}`}
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <PriorityChip priority={ticket.priority} />
        {ticket.overdue && (
          <span className="inline-flex items-center gap-0.5 text-[10px] font-bold text-rose-700">
            <AlertTriangle className="w-3 h-3" /> SLA
          </span>
        )}
      </div>
      <div className="font-semibold text-[var(--ayci-ink)] line-clamp-2 leading-snug">{ticket.subject}</div>
      <div className="text-xs text-[var(--ayci-ink-muted)] mt-1 truncate">{ticket.student_name}</div>
      <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-1.5 flex items-center justify-between gap-1">
        <span className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {relativeAge(ticket.created_at)}
        </span>
        {assignee ? (
          <span className="px-1.5 py-0.5 rounded bg-sky-100 text-sky-800 truncate max-w-[100px]">
            {assignee.name}
          </span>
        ) : (
          <span className="text-amber-700">unassigned</span>
        )}
      </div>
    </div>
  );
}

function TicketTable({ rows, teamById, onOpen }) {
  if (rows.length === 0) {
    return (
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-12 text-center text-sm text-[var(--ayci-ink-muted)]">
        No tickets match the current filters.
      </div>
    );
  }
  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-lg overflow-hidden" data-testid="tickets-table">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)] font-semibold">
            <tr>
              <th className="text-left px-3 py-2.5">Priority</th>
              <th className="text-left px-3 py-2.5">Status</th>
              <th className="text-left px-3 py-2.5">Subject</th>
              <th className="text-left px-3 py-2.5">Student</th>
              <th className="text-left px-3 py-2.5">Category</th>
              <th className="text-left px-3 py-2.5">Assignee</th>
              <th className="text-left px-3 py-2.5">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((t) => {
              const assignee = t.assignee_id ? teamById[t.assignee_id] : null;
              return (
                <tr
                  key={t.id}
                  onClick={() => onOpen(t.id)}
                  className={`hover:bg-slate-50 cursor-pointer ${t.overdue ? "bg-rose-50/40" : ""}`}
                  data-testid={`ticket-row-${t.id}`}
                >
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <PriorityChip priority={t.priority} />
                      {t.overdue && <AlertTriangle className="w-3.5 h-3.5 text-rose-600" />}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusChip status={t.status} />
                  </td>
                  <td className="px-3 py-2.5 max-w-md">
                    <div className="font-semibold text-[var(--ayci-ink)] truncate">{t.subject}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="text-[var(--ayci-ink)]">{t.student_name}</div>
                    <div className="text-xs text-[var(--ayci-ink-muted)]">{t.student_email}</div>
                  </td>
                  <td className="px-3 py-2.5 capitalize text-[var(--ayci-ink-muted)]">{t.category}</td>
                  <td className="px-3 py-2.5 text-[var(--ayci-ink-muted)]">
                    {assignee ? assignee.name : <span className="text-amber-700">unassigned</span>}
                  </td>
                  <td className="px-3 py-2.5 text-[var(--ayci-ink-muted)] whitespace-nowrap">
                    {formatUk(t.created_at)}
                    <div className="text-[11px] opacity-70">{relativeAge(t.created_at)}</div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CreateTicketModal({ team, onClose, onSubmit }) {
  const [form, setForm] = useState({
    student_name: "",
    student_email: "",
    subject: "",
    description: "",
    priority: "medium",
    category: "other",
    assignee_id: "",
  });
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.student_email || !form.subject || !form.student_name) {
      toast.error("Name, email and subject are required");
      return;
    }
    setSubmitting(true);
    await onSubmit({
      ...form,
      assignee_id: form.assignee_id || null,
    });
    setSubmitting(false);
  };

  return (
    <Modal title="New ticket" onClose={onClose} testid="ticket-create-modal">
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Student name" required>
            <input
              type="text"
              value={form.student_name}
              onChange={(e) => setForm({ ...form, student_name: e.target.value })}
              required
              data-testid="ticket-create-name"
              className={inputCls}
            />
          </Field>
          <Field label="Student email" required>
            <input
              type="email"
              value={form.student_email}
              onChange={(e) => setForm({ ...form, student_email: e.target.value })}
              required
              data-testid="ticket-create-email"
              className={inputCls}
            />
          </Field>
        </div>
        <Field label="Subject" required>
          <input
            type="text"
            value={form.subject}
            onChange={(e) => setForm({ ...form, subject: e.target.value })}
            required
            data-testid="ticket-create-subject"
            className={inputCls}
          />
        </Field>
        <Field label="Description">
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={4}
            data-testid="ticket-create-description"
            className={inputCls}
          />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Priority">
            <select
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: e.target.value })}
              data-testid="ticket-create-priority"
              className={inputCls}
            >
              {PRIORITIES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Category">
            <select
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              data-testid="ticket-create-category"
              className={inputCls}
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Assignee">
            <select
              value={form.assignee_id}
              onChange={(e) => setForm({ ...form, assignee_id: e.target.value })}
              data-testid="ticket-create-assignee"
              className={inputCls}
            >
              <option value="">Unassigned</option>
              {team.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
          <Button type="button" variant="outline" onClick={onClose} data-testid="ticket-create-cancel">
            Cancel
          </Button>
          <Button type="submit" disabled={submitting} data-testid="ticket-create-submit">
            {submitting && <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />}
            Create ticket
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function TicketDetailModal({ ticket, team, onClose, onUpdate, onRefresh }) {
  const [note, setNote] = useState("");
  const [posting, setPosting] = useState(false);

  const handleField = (field, value) => onUpdate(ticket.id, { [field]: value });

  const handleAddNote = async () => {
    const body = note.trim();
    if (!body) return;
    setPosting(true);
    try {
      await apiClient.post(`/tickets/${ticket.id}/notes`, { body, internal: true });
      setNote("");
      await onRefresh();
      toast.success("Note added");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to add note");
    } finally {
      setPosting(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("Delete this ticket? This cannot be undone.")) return;
    try {
      await apiClient.delete(`/tickets/${ticket.id}`);
      await onRefresh();
      onClose();
      toast.success("Ticket deleted");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to delete");
    }
  };

  const studentLookupHref = `/students?q=${encodeURIComponent(ticket.student_email)}`;

  return (
    <Modal title={null} onClose={onClose} wide testid="ticket-detail-modal">
      <div className="space-y-4">
        <div className="flex items-start gap-3">
          <PriorityChip priority={ticket.priority} />
          <StatusChip status={ticket.status} />
          {ticket.overdue && (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded">
              <AlertTriangle className="w-3 h-3" /> SLA breach
            </span>
          )}
          <span className="ml-auto text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
            via {SOURCE_LABEL[ticket.source] || ticket.source}
          </span>
        </div>
        <h2 className="text-xl font-bold text-[var(--ayci-ink)] font-display leading-tight">
          {ticket.subject}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <Label>Student</Label>
            <div className="font-semibold">{ticket.student_name}</div>
            <a
              href={`mailto:${ticket.student_email}`}
              className="text-sm text-[var(--ayci-accent)] hover:underline flex items-center gap-1 mt-0.5"
            >
              <Mail className="w-3 h-3" /> {ticket.student_email}
            </a>
            <a
              href={studentLookupHref}
              className="text-xs text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-accent)] flex items-center gap-1 mt-1.5"
              data-testid="ticket-student-lookup-link"
            >
              <ExternalLink className="w-3 h-3" /> Open in Student Lookup
            </a>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <Field label="Status">
              <select
                value={ticket.status}
                onChange={(e) => handleField("status", e.target.value)}
                data-testid="ticket-detail-status"
                className={inputCls}
              >
                {STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Priority">
              <select
                value={ticket.priority}
                onChange={(e) => handleField("priority", e.target.value)}
                data-testid="ticket-detail-priority"
                className={inputCls}
              >
                {PRIORITIES.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Category">
              <select
                value={ticket.category}
                onChange={(e) => handleField("category", e.target.value)}
                data-testid="ticket-detail-category"
                className={inputCls}
              >
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Assignee">
              <select
                value={ticket.assignee_id || ""}
                onChange={(e) => handleField("assignee_id", e.target.value || null)}
                data-testid="ticket-detail-assignee"
                className={inputCls}
              >
                <option value="">Unassigned</option>
                {team.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </div>
        <div>
          <Label>Description</Label>
          <div className="bg-slate-50 border border-slate-200 rounded-md p-3 text-sm whitespace-pre-wrap text-[var(--ayci-ink)] max-h-[40vh] overflow-y-auto">
            {ticket.description || <span className="text-[var(--ayci-ink-muted)] italic">(no description)</span>}
          </div>
        </div>

        {ticket.source === "whatsapp" && (
          <WhatsAppReplyPanel ticket={ticket} onSent={onRefresh} />
        )}

        <div>
          <Label>Internal notes ({(ticket.notes || []).length})</Label>
          <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
            {(ticket.notes || []).length === 0 ? (
              <div className="text-xs text-[var(--ayci-ink-muted)] italic">No notes yet.</div>
            ) : (
              ticket.notes.map((n) => (
                <div
                  key={n.id}
                  className="border border-slate-200 bg-slate-50 rounded-md p-2.5 text-sm"
                  data-testid={`ticket-note-${n.id}`}
                >
                  <div className="flex items-center justify-between text-[11px] text-[var(--ayci-ink-muted)] mb-1">
                    <span className="font-semibold text-[var(--ayci-ink)]">{n.author_name}</span>
                    <span>{formatUk(n.created_at)}</span>
                  </div>
                  <div className="whitespace-pre-wrap">{n.body}</div>
                </div>
              ))
            )}
          </div>
          <div className="flex items-end gap-2 mt-2">
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Add an internal note…"
              rows={2}
              className={inputCls}
              data-testid="ticket-add-note-input"
            />
            <Button
              onClick={handleAddNote}
              disabled={!note.trim() || posting}
              size="sm"
              data-testid="ticket-add-note-submit"
            >
              {posting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </Button>
          </div>
        </div>

        <div className="flex justify-between items-center pt-3 border-t border-slate-100 text-[11px] text-[var(--ayci-ink-muted)]">
          <div>
            Created {formatUk(ticket.created_at)} ·{" "}
            {ticket.resolved_at ? `Resolved ${formatUk(ticket.resolved_at)}` : `Updated ${formatUk(ticket.updated_at)}`}
          </div>
          <button
            onClick={handleDelete}
            className="text-rose-600 hover:text-rose-800 font-semibold uppercase tracking-wider"
            data-testid="ticket-delete-button"
          >
            Delete
          </button>
        </div>
      </div>
    </Modal>
  );
}


// -------------------- WhatsApp reply panel --------------------

function WhatsAppReplyPanel({ ticket, onSent }) {
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [templatesLoaded, setTemplatesLoaded] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [showTemplates, setShowTemplates] = useState(false);

  // 24h session window — Wati requires templates after this
  const lastInbound = ticket.wati_last_inbound_at || ticket.created_at;
  const hoursSince = lastInbound ? (Date.now() - new Date(lastInbound).getTime()) / 3600000 : Infinity;
  const outOfWindow = hoursSince >= 24;

  const loadTemplates = async () => {
    if (templatesLoaded) return;
    try {
      const { data } = await apiClient.get("/wati/templates");
      setTemplates(data.templates || []);
      setTemplatesLoaded(true);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load templates");
    }
  };

  const handleSend = async () => {
    const text = body.trim();
    if (!text) return;
    setSending(true);
    try {
      await apiClient.post(`/wati/tickets/${ticket.id}/reply`, { body: text });
      setBody("");
      toast.success("WhatsApp reply sent");
      onSent && (await onSent());
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Send failed");
    } finally {
      setSending(false);
    }
  };

  const handleSendTemplate = async () => {
    if (!templateName) return;
    setSending(true);
    try {
      await apiClient.post(`/wati/tickets/${ticket.id}/template`, {
        template_name: templateName,
        broadcast_name: `ticket-${ticket.id}`,
        parameters: [],
      });
      setTemplateName("");
      toast.success("Template message sent");
      onSent && (await onSent());
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Template send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className="border border-emerald-200 bg-emerald-50/40 rounded-md p-3"
      data-testid="whatsapp-reply-panel"
    >
      <div className="flex items-center gap-2 mb-2">
        <MessageCircle className="w-4 h-4 text-emerald-700" />
        <span className="text-[11px] uppercase tracking-wider font-semibold text-emerald-800">
          WhatsApp reply · {ticket.wati_wa_id}
        </span>
        {outOfWindow && (
          <span className="ml-auto text-[10px] font-bold bg-amber-100 text-amber-900 px-1.5 py-0.5 rounded border border-amber-200">
            24H WINDOW EXPIRED
          </span>
        )}
      </div>

      {!outOfWindow ? (
        <div className="flex items-end gap-2">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Type a WhatsApp reply…"
            rows={2}
            className={inputCls}
            data-testid="whatsapp-reply-input"
          />
          <Button
            onClick={handleSend}
            disabled={!body.trim() || sending}
            size="sm"
            data-testid="whatsapp-reply-send"
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-amber-900">
            More than 24h since last student message — only pre-approved templates can be sent.
          </p>
          {!showTemplates ? (
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                setShowTemplates(true);
                await loadTemplates();
              }}
              data-testid="whatsapp-load-templates"
            >
              Load templates
            </Button>
          ) : (
            <div className="flex items-end gap-2">
              <select
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                className={inputCls}
                data-testid="whatsapp-template-select"
              >
                <option value="">Choose a template…</option>
                {templates.map((t) => {
                  const lang = typeof t.language === "object" ? (t.language?.text || t.language?.value) : t.language;
                  return (
                    <option key={t.name} value={t.name}>
                      {t.name}{lang ? ` (${lang})` : ""}
                    </option>
                  );
                })}
              </select>
              <Button
                onClick={handleSendTemplate}
                disabled={!templateName || sending}
                size="sm"
                data-testid="whatsapp-template-send"
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </Button>
            </div>
          )}
          {templateName && (
            <div className="text-xs text-[var(--ayci-ink-muted)] bg-white border border-slate-200 rounded p-2">
              {(templates.find((t) => t.name === templateName) || {}).body || "—"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


// -------------------- Generic UI helpers --------------------

const inputCls =
  "w-full text-sm border border-[var(--ayci-border)] rounded-md px-2.5 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]/40";

function Field({ label, required, children }) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)] block mb-1">
        {label} {required && <span className="text-rose-600">*</span>}
      </span>
      {children}
    </label>
  );
}

function Label({ children }) {
  return (
    <div className="text-[11px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)] mb-1">
      {children}
    </div>
  );
}

function Modal({ title, onClose, children, wide, testid }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      onClick={onClose}
      data-testid={testid}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={`bg-white rounded-lg shadow-xl w-full ${wide ? "max-w-3xl" : "max-w-lg"} max-h-[90vh] overflow-y-auto`}
      >
        <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between">
          <div className="font-display font-bold text-base text-[var(--ayci-ink)]">{title}</div>
          <button onClick={onClose} className="text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-ink)]" data-testid="modal-close">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
