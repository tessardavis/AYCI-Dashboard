import { useCallback, useEffect, useState } from "react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogTrigger,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { Trash2, Plus, Link2, GripVertical } from "lucide-react";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { formatValue } from "@/lib/format";
import MetricSourceDialog from "@/components/MetricSourceDialog";
import CohortMilestonesSection from "@/components/settings/CohortMilestonesSection";
import ConnectedInboxesSection from "@/components/settings/ConnectedInboxesSection";
import IntegrationsSection from "@/components/settings/IntegrationsSection";

const CATEGORIES = [
  "GROWTH + INTEREST",
  "CONVERSION + INTENT",
  "REVENUE",
  "SOCIAL PROOF",
  "DELIVERY + OPERATIONS",
];

export default function Settings() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const hasBot = isAdmin || (user?.board_access || []).includes("bot");

  return (
    <div className="p-4 sm:p-6 lg:p-12 ayci-fade-up">
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description={isAdmin ? "Manage team members, scorecard metrics, rocks and launches." : "Manage the Circle DM bot and its playbook."}
      />

      {!isAdmin && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded-md px-4 py-3 mb-6">
          You have access to the Bot tab only. Ask an admin if you need access to other settings.
        </div>
      )}

      <Tabs defaultValue={isAdmin ? "team" : "bot"} className="w-full">
        <div className="overflow-x-auto -mx-1 px-1 mb-6">
          <TabsList className="w-max">
            {isAdmin && <TabsTrigger value="team" data-testid="settings-tab-team">Team</TabsTrigger>}
            {isAdmin && <TabsTrigger value="users" data-testid="settings-tab-users">Users</TabsTrigger>}
            {isAdmin && <TabsTrigger value="metrics" data-testid="settings-tab-metrics">Metrics</TabsTrigger>}
            {isAdmin && <TabsTrigger value="rocks" data-testid="settings-tab-rocks">Rocks</TabsTrigger>}
            {isAdmin && <TabsTrigger value="launches" data-testid="settings-tab-launches">Launches</TabsTrigger>}
            {isAdmin && <TabsTrigger value="cohort" data-testid="settings-tab-cohort">Cohort</TabsTrigger>}
            {isAdmin && <TabsTrigger value="inboxes" data-testid="settings-tab-inboxes">Inboxes</TabsTrigger>}
            {isAdmin && <TabsTrigger value="integrations" data-testid="settings-tab-integrations">Integrations</TabsTrigger>}
            {hasBot && <TabsTrigger value="bot" data-testid="settings-tab-bot">Bot</TabsTrigger>}
          </TabsList>
        </div>
        {isAdmin && <TabsContent value="team"><TeamSection isAdmin={isAdmin} /></TabsContent>}
        {isAdmin && <TabsContent value="users"><UsersSection isAdmin={isAdmin} /></TabsContent>}
        {isAdmin && <TabsContent value="metrics"><MetricsSection isAdmin={isAdmin} /></TabsContent>}
        {isAdmin && <TabsContent value="rocks"><RocksSection isAdmin={isAdmin} /></TabsContent>}
        {isAdmin && <TabsContent value="launches"><LaunchesSection isAdmin={isAdmin} /></TabsContent>}
        {isAdmin && <TabsContent value="cohort"><CohortMilestonesSection isAdmin={isAdmin} /></TabsContent>}
        {isAdmin && <TabsContent value="inboxes"><ConnectedInboxesSection isAdmin={isAdmin} /></TabsContent>}
        {isAdmin && <TabsContent value="integrations"><IntegrationsSection isAdmin={isAdmin} /></TabsContent>}
        {hasBot && <TabsContent value="bot"><CoachPlaybookSection isAdmin={hasBot} /></TabsContent>}
      </Tabs>
    </div>
  );
}

function Panel({ children, title, action, description }) {
  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm mb-4">
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--ayci-border)]">
        <div>
          <div className="font-display font-bold text-[var(--ayci-ink)]">{title}</div>
          {description && (
            <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5 max-w-2xl">{description}</div>
          )}
        </div>
        {action}
      </div>
      <div>{children}</div>
    </div>
  );
}

// -------- Team --------
function TeamSection({ isAdmin }) {
  const [team, setTeam] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", role_title: "", avatar_url: "" });

  const load = useCallback(async () => {
    const { data } = await apiClient.get("/team");
    setTeam(data);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      await apiClient.post("/team", { ...form, avatar_url: form.avatar_url || null });
      toast.success("Member added");
      setOpen(false);
      setForm({ name: "", role_title: "", avatar_url: "" });
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const remove = async (id) => {
    try {
      await apiClient.delete(`/team/${id}`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  return (
    <>
    <Panel
      title="Team members"
      action={isAdmin && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" data-testid="team-add-btn" style={{ backgroundColor: "var(--ayci-accent)" }}>
              <Plus className="w-4 h-4 mr-1" /> Add member
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>New team member</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="team-form-name" /></div>
              <div><Label>Role</Label><Input value={form.role_title} onChange={(e) => setForm({ ...form, role_title: e.target.value })} data-testid="team-form-role" /></div>
              <div><Label>Avatar URL (optional)</Label><Input value={form.avatar_url} onChange={(e) => setForm({ ...form, avatar_url: e.target.value })} /></div>
            </div>
            <DialogFooter>
              <Button onClick={save} data-testid="team-form-save" style={{ backgroundColor: "var(--ayci-accent)" }}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    >
      <ul className="divide-y divide-[var(--ayci-border)]">
        {team.map((t) => (
          <li key={t.id} className="flex items-center gap-4 px-6 py-3" data-testid={`team-row-${t.id}`}>
            <Avatar className="w-9 h-9">
              {t.avatar_url && <AvatarImage src={t.avatar_url} alt={t.name} />}
              <AvatarFallback className="bg-slate-100 text-slate-700 text-xs">{t.name.split(" ").map(p => p[0]).slice(0, 2).join("")}</AvatarFallback>
            </Avatar>
            <div className="flex-1">
              <div className="font-medium text-[var(--ayci-ink)] text-sm">{t.name}</div>
              <div className="text-xs text-[var(--ayci-ink-muted)]">{t.role_title}</div>
            </div>
            {isAdmin && (
              <Button variant="ghost" size="icon" onClick={() => remove(t.id)} data-testid={`team-delete-${t.id}`}>
                <Trash2 className="w-4 h-4 text-slate-500" />
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Panel>
    <InboxRoutingPanel isAdmin={isAdmin} team={team} />
    </>
  );
}

function InboxRoutingPanel({ isAdmin, team }) {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/team/inbox-routing");
      setRules(
        (data.rules || []).map((r) => ({
          inbox_locals: (r.inbox_locals || []).join(", "),
          team_member_name: r.team_member_name || "",
        })),
      );
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const update = (i, field, value) => {
    setRules((prev) => prev.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  };
  const addRule = () => setRules((p) => [...p, { inbox_locals: "", team_member_name: "" }]);
  const removeRule = (i) => setRules((p) => p.filter((_, idx) => idx !== i));

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        rules: rules
          .map((r) => ({
            inbox_locals: r.inbox_locals
              .split(/[,\s]+/)
              .map((x) => x.trim().toLowerCase())
              .filter(Boolean),
            team_member_name: r.team_member_name.trim(),
          }))
          .filter((r) => r.inbox_locals.length > 0 && r.team_member_name),
      };
      const { data } = await apiClient.put("/team/inbox-routing", payload);
      setRules(
        (data.rules || []).map((r) => ({
          inbox_locals: (r.inbox_locals || []).join(", "),
          team_member_name: r.team_member_name || "",
        })),
      );
      toast.success("Inbox routing saved");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Panel
      title="Inbox auto-assignment"
      description="When an email lands in the listed inbox(es), the new ticket is auto-assigned to the chosen team member. Only the part before @ — comma-separated for multiple."
      action={isAdmin && (
        <Button size="sm" onClick={save} disabled={saving} data-testid="inbox-routing-save" style={{ backgroundColor: "var(--ayci-accent)" }}>
          {saving ? "Saving…" : "Save"}
        </Button>
      )}
    >
      {loading ? (
        <div className="px-6 py-4 text-sm text-[var(--ayci-ink-muted)]">Loading…</div>
      ) : (
        <div className="px-6 py-4 space-y-3">
          {rules.length === 0 && (
            <div className="text-xs text-[var(--ayci-ink-muted)] italic">No rules yet — add one below.</div>
          )}
          {rules.map((r, i) => (
            <div key={i} className="flex flex-wrap items-end gap-2" data-testid={`inbox-routing-row-${i}`}>
              <div className="flex-1 min-w-[220px]">
                <Label className="text-xs">Inbox local-parts</Label>
                <Input
                  value={r.inbox_locals}
                  onChange={(e) => update(i, "inbox_locals", e.target.value)}
                  placeholder="e.g. coralie, oksana"
                  disabled={!isAdmin}
                  data-testid={`inbox-routing-locals-${i}`}
                />
              </div>
              <div className="flex-1 min-w-[200px]">
                <Label className="text-xs">Assign to</Label>
                <select
                  value={r.team_member_name}
                  onChange={(e) => update(i, "team_member_name", e.target.value)}
                  disabled={!isAdmin}
                  className="w-full h-9 px-3 text-sm border border-[var(--ayci-border)] rounded-md bg-white"
                  data-testid={`inbox-routing-assignee-${i}`}
                >
                  <option value="">— pick a team member —</option>
                  {team.map((t) => (
                    <option key={t.id} value={t.name}>{t.name}</option>
                  ))}
                </select>
              </div>
              {isAdmin && (
                <Button variant="ghost" size="icon" onClick={() => removeRule(i)} data-testid={`inbox-routing-remove-${i}`}>
                  <Trash2 className="w-4 h-4 text-slate-500" />
                </Button>
              )}
            </div>
          ))}
          {isAdmin && (
            <Button variant="outline" size="sm" onClick={addRule} data-testid="inbox-routing-add">
              <Plus className="w-4 h-4 mr-1" /> Add rule
            </Button>
          )}
        </div>
      )}
    </Panel>
  );
}

// -------- Users (login accounts) --------
const BOARD_LABELS = {
  weekly_scorecard: "Weekly Scorecard",
  quarterly_rocks: "Quarterly Rocks",
  launches: "Launch Dashboard",
  cohort: "Cohort Dashboard",
  interviews: "Upcoming Interviews",
  students: "Student Lookup",
  at_risk: "Students at Risk",
  bot: "Circle DM Bot",
};

function UsersSection({ isAdmin }) {
  const [users, setUsers] = useState([]);
  const [allBoards, setAllBoards] = useState([]);
  const [teamMembers, setTeamMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    role: "user",
    board_access: [],
  });

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/admin/users");
      setUsers(data.users || []);
      setAllBoards(data.all_boards || []);
      setTeamMembers(data.team_members || []);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin) load();
  }, [isAdmin]);

  const create = async () => {
    setBusy(true);
    try {
      await apiClient.post("/auth/register", form);
      toast.success(`Invited ${form.email}`);
      setForm({ name: "", email: "", password: "", role: "user", board_access: [] });
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setBusy(false);
    }
  };

  const updateUser = async (userId, patch) => {
    try {
      await apiClient.patch(`/admin/users/${userId}`, patch);
      toast.success("Saved");
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const deleteUser = async (userId, email) => {
    if (!window.confirm(`Delete user ${email}? This cannot be undone.`)) return;
    try {
      await apiClient.delete(`/admin/users/${userId}`);
      toast.success("User deleted");
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const toggleBoard = (user, board) => {
    if (user.role === "admin") return; // admins always have everything
    const has = (user.board_access || []).includes(board);
    const next = has
      ? (user.board_access || []).filter((b) => b !== board)
      : [...(user.board_access || []), board];
    updateUser(user.id, { board_access: next });
  };

  const resetUserPassword = async (user) => {
    const newPw = window.prompt(
      `Set a new password for ${user.email}.\n\nThey'll need to log in with this and can change it later.\n\n(Min 8 chars)`,
      "",
    );
    if (newPw === null) return;
    if (newPw.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    try {
      await apiClient.patch(`/admin/users/${user.id}`, { password: newPw });
      toast.success(`Password reset for ${user.email} — share securely with them`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  if (!isAdmin) {
    return <div className="text-sm text-[var(--ayci-ink-muted)]">Admin only.</div>;
  }

  return (
    <div className="space-y-6">
      <Panel title="Invite a new user">
        <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-4 max-w-2xl">
          <div>
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              data-testid="user-form-name"
            />
          </div>
          <div>
            <Label>Email</Label>
            <Input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              data-testid="user-form-email"
            />
          </div>
          <div>
            <Label>Temporary password</Label>
            <Input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              data-testid="user-form-password"
            />
          </div>
          <div>
            <Label>Role</Label>
            <Select
              value={form.role}
              onValueChange={(v) => setForm({ ...form, role: v })}
            >
              <SelectTrigger data-testid="user-form-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">User</SelectItem>
                <SelectItem value="admin">Admin (full access)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {form.role === "user" && (
            <div className="md:col-span-2">
              <Label>Board access</Label>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-1">
                {allBoards.map((b) => (
                  <label
                    key={b}
                    className="flex items-center gap-2 text-xs bg-slate-50 border border-[var(--ayci-border)] rounded px-3 py-2 cursor-pointer hover:border-[var(--ayci-accent)]"
                  >
                    <input
                      type="checkbox"
                      checked={form.board_access.includes(b)}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...form.board_access, b]
                          : form.board_access.filter((x) => x !== b);
                        setForm({ ...form, board_access: next });
                      }}
                      data-testid={`user-form-board-${b}`}
                    />
                    {BOARD_LABELS[b] || b}
                  </label>
                ))}
              </div>
            </div>
          )}
          <div className="md:col-span-2">
            <Button
              onClick={create}
              disabled={busy || !form.email || !form.password || !form.name}
              data-testid="user-form-save"
              style={{ backgroundColor: "var(--ayci-accent)" }}
            >
              {busy ? "Inviting…" : "Invite user"}
            </Button>
          </div>
        </div>
      </Panel>

      <Panel
        title={`Existing users (${users.length})`}
        action={
          users.filter((u) => u.role !== "admin" && !u.team_member_id).length > 0 ? (
            <span
              className="text-[10px] uppercase tracking-wider font-semibold px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-800"
              data-testid="users-unlinked-badge"
            >
              ⚠ {users.filter((u) => u.role !== "admin" && !u.team_member_id).length} not linked
            </span>
          ) : null
        }
      >
        {loading ? (
          <div className="p-6 text-sm text-[var(--ayci-ink-muted)]">Loading…</div>
        ) : (
          <div className="divide-y divide-[var(--ayci-border)]">
            {users.map((u) => (
              <div key={u.id} className="p-4" data-testid={`user-row-${u.id}`}>
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <div className="font-semibold text-[var(--ayci-ink)]">
                      {u.name}{" "}
                      <span className="text-xs font-normal text-[var(--ayci-ink-muted)]">
                        ({u.email})
                      </span>
                    </div>
                    <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mt-0.5">
                      {u.role === "admin" ? "Admin · full access" : "User"}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Select
                      value={u.role}
                      onValueChange={(v) => updateUser(u.id, { role: v })}
                    >
                      <SelectTrigger
                        className="h-8 text-xs"
                        data-testid={`user-row-role-${u.id}`}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="user">User</SelectItem>
                        <SelectItem value="admin">Admin</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => resetUserPassword(u)}
                      data-testid={`user-row-reset-pw-${u.id}`}
                    >
                      Reset password
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => deleteUser(u.id, u.email)}
                      data-testid={`user-row-delete-${u.id}`}
                      className="text-rose-600 hover:bg-rose-50"
                    >
                      Delete
                    </Button>
                  </div>
                </div>
                {u.role === "user" && (
                  <>
                    <div className="mt-3 flex items-center gap-2 flex-wrap" data-testid={`user-tm-row-${u.id}`}>
                      <span className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] font-semibold">
                        Team member:
                      </span>
                      <Select
                        value={u.team_member_id || "__none__"}
                        onValueChange={(v) =>
                          updateUser(u.id, { team_member_id: v === "__none__" ? "" : v })
                        }
                      >
                        <SelectTrigger
                          className="h-7 w-[200px] text-xs"
                          data-testid={`user-tm-select-${u.id}`}
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__">— Not linked —</SelectItem>
                          {teamMembers.map((tm) => (
                            <SelectItem
                              key={tm.id}
                              value={tm.id}
                              data-testid={`user-tm-option-${u.id}-${tm.id}`}
                            >
                              {tm.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {!u.team_member_id && (
                        <span className="text-[10px] text-amber-700">
                          Can't edit any rocks until linked
                        </span>
                      )}
                    </div>
                    <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-1.5">
                    {allBoards.map((b) => {
                      const has = (u.board_access || []).includes(b);
                      return (
                        <button
                          key={b}
                          onClick={() => toggleBoard(u, b)}
                          data-testid={`user-row-board-${u.id}-${b}`}
                          className={
                            "text-[11px] px-2 py-1 rounded border transition-colors " +
                            (has
                              ? "bg-[var(--ayci-accent)]/10 border-[var(--ayci-accent)] text-[var(--ayci-accent)] font-semibold"
                              : "bg-white border-[var(--ayci-border)] text-[var(--ayci-ink-muted)] hover:border-[var(--ayci-accent)]")
                          }
                        >
                          {has ? "✓" : "+"} {BOARD_LABELS[b] || b}
                        </button>
                      );
                    })}
                  </div>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

// -------- Metrics --------
function MetricsSection({ isAdmin }) {
  const [metrics, setMetrics] = useState([]);
  const [team, setTeam] = useState([]);
  const [open, setOpen] = useState(false);
  const [sourceMetric, setSourceMetric] = useState(null);
  const [form, setForm] = useState({ name: "", category: "GROWTH + INTEREST", owner_ids: [], goal: 0, format: "number", goal_direction: "above" });

  const load = useCallback(async () => {
    const [m, t] = await Promise.all([apiClient.get("/metrics"), apiClient.get("/team")]);
    setMetrics(m.data); setTeam(t.data);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      await apiClient.post("/metrics", { ...form, goal: Number(form.goal) });
      toast.success("Metric added");
      setOpen(false);
      setForm({ name: "", category: "GROWTH + INTEREST", owner_ids: [], goal: 0, format: "number", goal_direction: "above" });
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const remove = async (id) => {
    await apiClient.delete(`/metrics/${id}`);
    load();
  };

  const toggleOwner = (id) => {
    setForm((f) => ({
      ...f,
      owner_ids: f.owner_ids.includes(id) ? f.owner_ids.filter((x) => x !== id) : [...f.owner_ids, id],
    }));
  };

  return (
    <Panel
      title="Scorecard metrics"
      action={isAdmin && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" data-testid="metric-add-btn" style={{ backgroundColor: "var(--ayci-accent)" }}>
              <Plus className="w-4 h-4 mr-1" /> Add metric
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg">
            <DialogHeader><DialogTitle>New metric</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="metric-form-name" /></div>
              <div>
                <Label>Category</Label>
                <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label>Goal</Label>
                  <Input type="number" value={form.goal} onChange={(e) => setForm({ ...form, goal: e.target.value })} data-testid="metric-form-goal" />
                </div>
                <div>
                  <Label>Format</Label>
                  <Select value={form.format} onValueChange={(v) => setForm({ ...form, format: v })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="number">Number</SelectItem>
                      <SelectItem value="currency">Currency (£)</SelectItem>
                      <SelectItem value="percentage">Percentage (%)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Direction</Label>
                  <Select value={form.goal_direction} onValueChange={(v) => setForm({ ...form, goal_direction: v })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="above">Higher is better</SelectItem>
                      <SelectItem value="below">Lower is better</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div>
                <Label>Owners</Label>
                <div className="flex flex-wrap gap-2 mt-2">
                  {team.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => toggleOwner(t.id)}
                      className={
                        "text-xs px-2.5 py-1 rounded-full border transition-colors " +
                        (form.owner_ids.includes(t.id)
                          ? "bg-[var(--ayci-accent)] text-white border-[var(--ayci-accent)]"
                          : "bg-white border-[var(--ayci-border)] text-[var(--ayci-ink-muted)]")
                      }
                    >
                      {t.name}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={save} data-testid="metric-form-save" style={{ backgroundColor: "var(--ayci-accent)" }}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    >
      <table className="w-full text-sm">
        <thead className="bg-slate-50 border-b border-[var(--ayci-border)]">
          <tr>
            {isAdmin && <th className="w-8" />}
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Name</th>
            <th className="text-right px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Goal</th>
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Format</th>
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Source</th>
            {isAdmin && <th />}
          </tr>
        </thead>
        <DragDropContext
          onDragEnd={async (result) => {
            if (!isAdmin) return;
            if (!result.destination) return;
            const category = result.source.droppableId;
            if (result.destination.droppableId !== category) return;

            const groupMetrics = metrics
              .filter((m) => m.category === category)
              .sort((a, b) => a.order - b.order);
            const [moved] = groupMetrics.splice(result.source.index, 1);
            groupMetrics.splice(result.destination.index, 0, moved);

            // Re-assign orders in this category starting from the min order
            const minOrder = Math.min(...groupMetrics.map((m) => m.order));
            const updates = groupMetrics.map((m, i) => ({ id: m.id, order: minOrder + i }));

            // Optimistic UI
            setMetrics((prev) =>
              prev.map((m) => {
                const u = updates.find((x) => x.id === m.id);
                return u ? { ...m, order: u.order } : m;
              }),
            );

            try {
              await apiClient.patch("/metrics/reorder", { order: updates });
              toast.success("Reordered");
            } catch (err) {
              toast.error(
                formatApiErrorDetail(err.response?.data?.detail) || "Reorder failed",
              );
              load(); // rollback
            }
          }}
        >
          {CATEGORIES.map((cat) => {
            const rows = metrics
              .filter((m) => m.category === cat)
              .sort((a, b) => a.order - b.order);
            if (rows.length === 0) return null;
            return (
              <tbody key={cat}>
                <tr className="bg-slate-50/50">
                  <td
                    colSpan={isAdmin ? 6 : 5}
                    className="px-6 py-1.5 text-[10px] font-display font-semibold uppercase tracking-[0.2em] text-[var(--ayci-teal)] border-t border-b border-[var(--ayci-border)]"
                  >
                    {cat}
                  </td>
                </tr>
                <Droppable droppableId={cat} isDropDisabled={!isAdmin}>
                  {(dropProv) => (
                    <>
                      {rows.map((m, idx) => (
                        <Draggable key={m.id} draggableId={m.id} index={idx} isDragDisabled={!isAdmin}>
                          {(dragProv, snap) => (
                            <tr
                              ref={dragProv.innerRef}
                              {...dragProv.draggableProps}
                              className={
                                "border-b border-[var(--ayci-border)] last:border-0 " +
                                (snap.isDragging ? "bg-amber-50 shadow-md" : "")
                              }
                              style={dragProv.draggableProps.style}
                              data-testid={`metric-row-${m.id}`}
                            >
                              {isAdmin && (
                                <td
                                  className="px-2 text-slate-300 cursor-grab active:cursor-grabbing hover:text-slate-600"
                                  {...dragProv.dragHandleProps}
                                  data-testid={`metric-drag-${m.id}`}
                                >
                                  <GripVertical className="w-4 h-4" />
                                </td>
                              )}
                              <td className="px-6 py-2.5 font-medium text-[var(--ayci-ink)]">
                                {m.name}
                              </td>
                              <td className="px-6 py-2.5 text-right metric-number">
                                {formatValue(m.goal, m.format)}
                              </td>
                              <td className="px-6 py-2.5 capitalize text-[var(--ayci-ink-muted)]">
                                {m.format}
                              </td>
                              <td className="px-6 py-2.5">
                                {m.source_type ? (
                                  <button
                                    onClick={() => isAdmin && setSourceMetric(m)}
                                    className="inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full bg-sky-50 text-sky-700 ring-1 ring-sky-200 hover:bg-sky-100"
                                    data-testid={`metric-source-${m.id}`}
                                  >
                                    <Link2 className="w-3 h-3" />
                                    {m.source_type.replace(/_/g, " ")}
                                  </button>
                                ) : isAdmin ? (
                                  <button
                                    onClick={() => setSourceMetric(m)}
                                    className="text-[11px] text-[var(--ayci-accent)] hover:underline"
                                    data-testid={`metric-source-${m.id}`}
                                  >
                                    + Connect source
                                  </button>
                                ) : (
                                  <span className="text-xs text-[var(--ayci-ink-muted)]">manual</span>
                                )}
                              </td>
                              {isAdmin && (
                                <td className="px-6 py-2.5 text-right">
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => remove(m.id)}
                                    data-testid={`metric-delete-${m.id}`}
                                  >
                                    <Trash2 className="w-4 h-4 text-slate-500" />
                                  </Button>
                                </td>
                              )}
                            </tr>
                          )}
                        </Draggable>
                      ))}
                      <tr ref={dropProv.innerRef} {...dropProv.droppableProps} className="h-0">
                        <td colSpan={isAdmin ? 6 : 5}>{dropProv.placeholder}</td>
                      </tr>
                    </>
                  )}
                </Droppable>
              </tbody>
            );
          })}
        </DragDropContext>
      </table>
      <MetricSourceDialog
        open={!!sourceMetric}
        onOpenChange={(o) => !o && setSourceMetric(null)}
        metric={sourceMetric}
        onSaved={load}
      />
    </Panel>
  );
}

// -------- Rocks --------
function RocksSection({ isAdmin }) {
  const [rocks, setRocks] = useState([]);
  const [team, setTeam] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ owner_id: "", title: "", status: "on_track", due_date: "2026-06-30", notes: "", quarter: "Q2 2026" });
  const [quarters, setQuarters] = useState([]);
  const [activeQuarter, setActiveQuarter] = useState(null);
  const [savingActive, setSavingActive] = useState(false);

  const load = useCallback(async () => {
    const [r, t, q] = await Promise.all([
      apiClient.get("/rocks"),
      apiClient.get("/team"),
      apiClient.get("/rocks/quarters"),
    ]);
    setRocks(r.data); setTeam(t.data);
    const qd = q.data;
    setQuarters(Array.isArray(qd) ? qd : qd.quarters || []);
    setActiveQuarter(Array.isArray(qd) ? null : qd.active);
  }, []);
  useEffect(() => { load(); }, [load]);

  const setActive = async (q) => {
    if (!isAdmin || !q) return;
    setSavingActive(true);
    try {
      const { data } = await apiClient.put("/rocks/active-quarter", { quarter: q });
      setActiveQuarter(data.active);
      toast.success(`Active quarter set to ${data.active}`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to set active quarter");
    } finally {
      setSavingActive(false);
    }
  };

  const save = async () => {
    try {
      await apiClient.post("/rocks", form);
      toast.success("Rock added");
      setOpen(false);
      setForm({ owner_id: "", title: "", status: "on_track", due_date: "2026-06-30", notes: "", quarter: "Q2 2026" });
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const remove = async (id) => {
    await apiClient.delete(`/rocks/${id}`);
    load();
  };

  const teamById = Object.fromEntries(team.map((t) => [t.id, t]));

  return (
    <Panel
      title="Quarterly rocks"
      action={isAdmin && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" data-testid="rock-add-btn" style={{ backgroundColor: "var(--ayci-accent)" }}>
              <Plus className="w-4 h-4 mr-1" /> Add rock
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>New rock</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Title</Label><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="rock-form-title" /></div>
              <div>
                <Label>Owner</Label>
                <Select value={form.owner_id} onValueChange={(v) => setForm({ ...form, owner_id: v })}>
                  <SelectTrigger data-testid="rock-form-owner"><SelectValue placeholder="Choose owner" /></SelectTrigger>
                  <SelectContent>
                    {team.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Quarter</Label>
                  <Input value={form.quarter} onChange={(e) => setForm({ ...form, quarter: e.target.value })} data-testid="rock-form-quarter" />
                </div>
                <div>
                  <Label>Due date</Label>
                  <Input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={save} data-testid="rock-form-save" style={{ backgroundColor: "var(--ayci-accent)" }}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    >
      {quarters.length > 0 && (
        <div
          className="px-5 py-4 border-b border-[var(--ayci-border)] bg-slate-50/50 flex items-center gap-3 flex-wrap"
          data-testid="active-quarter-panel"
        >
          <div className="flex-1 min-w-[200px]">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)]">
              Active quarter
            </div>
            <div className="text-sm text-[var(--ayci-ink)] mt-0.5">
              Rocks in other quarters become read-only for non-admin users.
            </div>
          </div>
          <Select
            value={activeQuarter || ""}
            onValueChange={setActive}
            disabled={!isAdmin || savingActive}
          >
            <SelectTrigger className="w-[200px] bg-white" data-testid="active-quarter-select">
              <SelectValue placeholder="Pick active quarter" />
            </SelectTrigger>
            <SelectContent>
              {quarters.map((q) => (
                <SelectItem key={q} value={q} data-testid={`active-quarter-option-${q}`}>
                  {q}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      <ul className="divide-y divide-[var(--ayci-border)]">
        {rocks.map((r) => (
          <li key={r.id} className="px-6 py-3 flex items-center gap-4">
            <div className="w-32 text-xs text-[var(--ayci-ink-muted)]">{teamById[r.owner_id]?.name || "—"}</div>
            <div className="flex-1 text-sm">{r.title}</div>
            <div className="text-xs text-[var(--ayci-ink-muted)] flex items-center gap-1">
              {r.quarter}
              {r.quarter === activeQuarter && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 uppercase tracking-wider font-semibold">
                  Active
                </span>
              )}
            </div>
            <div className="text-xs text-[var(--ayci-ink-muted)] capitalize">{r.status.replace("_", " ")}</div>
            {isAdmin && (
              <Button variant="ghost" size="icon" onClick={() => remove(r.id)} data-testid={`rock-delete-${r.id}`}>
                <Trash2 className="w-4 h-4 text-slate-500" />
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// -------- Launches --------
const PHASE_KEYS = [
  ["in_between_start", "In-between (start)"],
  ["early_access", "Early access"],
  ["flash_sale", "Flash sale"],
  ["webinar", "Webinar"],
  ["open_cart", "Open cart"],
  ["close_cart", "Close cart"],
  ["in_between_end", "In-between (end)"],
];

function LaunchesSection({ isAdmin }) {
  const [launches, setLaunches] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", code: "", start_date: "", end_date: "", webinar_date: "", target_good: 140000, target_better: 160000, target_best: 200000 });
  const [editing, setEditing] = useState(null); // launch object being edited

  const load = useCallback(async () => {
    const { data } = await apiClient.get("/launches");
    setLaunches(data);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      await apiClient.post("/launches", {
        ...form,
        target_good: Number(form.target_good),
        target_better: Number(form.target_better),
        target_best: Number(form.target_best),
      });
      toast.success("Launch created");
      setOpen(false);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const remove = async (id) => {
    await apiClient.delete(`/launches/${id}`);
    load();
  };

  const saveEdit = async () => {
    try {
      await apiClient.patch(`/launches/${editing.id}`, {
        name: editing.name,
        code: editing.code,
        start_date: editing.start_date,
        end_date: editing.end_date,
        webinar_date: editing.webinar_date,
        target_good: Number(editing.target_good),
        target_better: Number(editing.target_better),
        target_best: Number(editing.target_best),
        phases: editing.phases,
      });
      toast.success("Launch updated");
      setEditing(null);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const setEditingPhase = (key, field, value) => {
    setEditing((cur) => ({
      ...cur,
      phases: {
        ...(cur.phases || {}),
        [key]: { ...((cur.phases || {})[key] || {}), [field]: value },
      },
    }));
  };

  return (
    <Panel
      title="Launches"
      action={isAdmin && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" data-testid="launch-add-btn" style={{ backgroundColor: "var(--ayci-accent)" }}>
              <Plus className="w-4 h-4 mr-1" /> Add launch
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>New launch</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Name</Label><Input placeholder="e.g. September 2026" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="launch-form-name" /></div>
              <div><Label>Kit tag code</Label><Input placeholder="e.g. SEP-26 (matches '[AYCI SEP-26] Webinar - Registered - X' tags)" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} data-testid="launch-form-code" /></div>
              <div className="grid grid-cols-3 gap-3">
                <div><Label>Start date</Label><Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></div>
                <div><Label>End date</Label><Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></div>
                <div><Label>Webinar date</Label><Input type="date" value={form.webinar_date} onChange={(e) => setForm({ ...form, webinar_date: e.target.value })} /></div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div><Label>Good (£)</Label><Input type="number" value={form.target_good} onChange={(e) => setForm({ ...form, target_good: e.target.value })} /></div>
                <div><Label>Better (£)</Label><Input type="number" value={form.target_better} onChange={(e) => setForm({ ...form, target_better: e.target.value })} /></div>
                <div><Label>Best (£)</Label><Input type="number" value={form.target_best} onChange={(e) => setForm({ ...form, target_best: e.target.value })} /></div>
              </div>
              <p className="text-xs text-[var(--ayci-ink-muted)]">Phase dates can be set after creating — click "Edit phases" on the launch row.</p>
            </div>
            <DialogFooter>
              <Button onClick={save} data-testid="launch-form-save" style={{ backgroundColor: "var(--ayci-accent)" }}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    >
      <ul className="divide-y divide-[var(--ayci-border)]">
        {launches.map((l) => (
          <li key={l.id} className="px-6 py-3 flex items-center gap-4">
            <div className="font-display font-bold text-[var(--ayci-ink)] w-40">{l.name}</div>
            <div className="text-xs text-[var(--ayci-ink-muted)] w-24">{l.code || "—"}</div>
            <div className="text-xs text-[var(--ayci-ink-muted)] w-44">Webinar: {l.webinar_date}</div>
            <div className="flex-1 text-xs text-[var(--ayci-ink-muted)]">
              £{Number(l.target_good / 1000).toFixed(0)}k / £{Number(l.target_better / 1000).toFixed(0)}k / £{Number(l.target_best / 1000).toFixed(0)}k
            </div>
            {isAdmin && (
              <>
                <Button variant="outline" size="sm" onClick={() => setEditing({ ...l, phases: l.phases || {} })} data-testid={`launch-edit-${l.id}`}>
                  Edit
                </Button>
                <Button variant="ghost" size="icon" onClick={() => remove(l.id)} data-testid={`launch-delete-${l.id}`}>
                  <Trash2 className="w-4 h-4 text-slate-500" />
                </Button>
              </>
            )}
          </li>
        ))}
      </ul>

      {/* Edit dialog */}
      <Dialog open={!!editing} onOpenChange={(v) => !v && setEditing(null)}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit launch — {editing?.name}</DialogTitle>
          </DialogHeader>
          {editing && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Name</Label><Input value={editing.name || ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></div>
                <div><Label>Kit tag code</Label><Input value={editing.code || ""} onChange={(e) => setEditing({ ...editing, code: e.target.value.toUpperCase() })} placeholder="e.g. APR-26" data-testid="launch-edit-code" /></div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div><Label>Start date</Label><Input type="date" value={editing.start_date || ""} onChange={(e) => setEditing({ ...editing, start_date: e.target.value })} /></div>
                <div><Label>End date</Label><Input type="date" value={editing.end_date || ""} onChange={(e) => setEditing({ ...editing, end_date: e.target.value })} /></div>
                <div><Label>Webinar date</Label><Input type="date" value={editing.webinar_date || ""} onChange={(e) => setEditing({ ...editing, webinar_date: e.target.value })} /></div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div><Label>Good (£)</Label><Input type="number" value={editing.target_good || 0} onChange={(e) => setEditing({ ...editing, target_good: e.target.value })} /></div>
                <div><Label>Better (£)</Label><Input type="number" value={editing.target_better || 0} onChange={(e) => setEditing({ ...editing, target_better: e.target.value })} /></div>
                <div><Label>Best (£)</Label><Input type="number" value={editing.target_best || 0} onChange={(e) => setEditing({ ...editing, target_best: e.target.value })} /></div>
              </div>

              <div className="border-t border-[var(--ayci-border)] pt-4">
                <h3 className="font-display font-bold text-sm text-[var(--ayci-ink)] mb-2">Launch phases</h3>
                <p className="text-xs text-[var(--ayci-ink-muted)] mb-3">
                  Use date+time format (datetime-local). The phase timeline on the Launch Dashboard reads these.
                </p>
                <div className="space-y-2">
                  {PHASE_KEYS.map(([key, label]) => {
                    const ph = (editing.phases || {})[key] || {};
                    const trim = (s) => (s ? s.replace("Z", "").slice(0, 16) : "");
                    return (
                      <div key={key} className="grid grid-cols-[140px_1fr_1fr] gap-2 items-center">
                        <span className="text-sm font-medium">{label}</span>
                        <Input
                          type="datetime-local"
                          value={trim(ph.start)}
                          onChange={(e) => setEditingPhase(key, "start", e.target.value ? `${e.target.value}:00Z` : null)}
                          data-testid={`phase-${key}-start`}
                        />
                        <Input
                          type="datetime-local"
                          value={trim(ph.end)}
                          onChange={(e) => setEditingPhase(key, "end", e.target.value ? `${e.target.value}:00Z` : null)}
                          data-testid={`phase-${key}-end`}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={saveEdit} data-testid="launch-edit-save" style={{ backgroundColor: "var(--ayci-accent)" }}>
              Save changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}



// ---------------------------------------------------------------- Bot section
function CoachPlaybookSection({ isAdmin }) {
  const [text, setText] = useState("");
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [events, setEvents] = useState([]);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [bot, setBot] = useState(null);
  const [loadingBot, setLoadingBot] = useState(true);
  const [polling, setPolling] = useState(false);
  const [resetting, setResetting] = useState(null);
  const [resettingAll, setResettingAll] = useState(false);
  const [editingCoaches, setEditingCoaches] = useState(false);
  const [coachEmailsInput, setCoachEmailsInput] = useState("");
  const [editingTags, setEditingTags] = useState(false);
  const [tagsInput, setTagsInput] = useState("");
  const [editingExclCoaches, setEditingExclCoaches] = useState(false);
  const [exclCoachesInput, setExclCoachesInput] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [loadingSuggs, setLoadingSuggs] = useState(false);
  const [suggAnswers, setSuggAnswers] = useState({});  // ticket_id -> draft answer
  const [handlingSugg, setHandlingSugg] = useState(null);
  // Watched-threads search/filter (so coaches can find a specific student
  // without scrolling through hundreds of rows).
  const [threadSearch, setThreadSearch] = useState("");
  const [threadStateFilter, setThreadStateFilter] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/circle/coach-playbook");
      setText(data.text || "");
      setMeta({ isDefault: data.is_default, updatedAt: data.updated_at, updatedBy: data.updated_by_name });
    } catch (err) {
      toast.error("Failed to load coach playbook");
    } finally {
      setLoading(false);
    }
  };

  const loadBot = async (opts = {}) => {
    setLoadingBot(true);
    try {
      const params = {};
      const s = opts.search ?? threadSearch;
      const st = opts.state ?? threadStateFilter;
      if (s && s.trim()) params.search = s.trim();
      if (st) params.state = st;
      const { data } = await apiClient.get("/circle/bot/status", { params });
      setBot(data);
    } catch (err) {
      toast.error("Failed to load bot status");
    } finally {
      setLoadingBot(false);
    }
  };

  const loadEvents = async () => {
    setLoadingEvents(true);
    try {
      const { data } = await apiClient.get("/circle/dm-events", { params: { limit: 20 } });
      setEvents(data.events || []);
    } catch (err) {
      toast.error("Failed to load events");
    } finally {
      setLoadingEvents(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/circle/coach-playbook", { text });
      toast.success("Playbook saved");
      load();
    } catch (err) {
      toast.error("Save failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  const toggleBot = async () => {
    if (!bot) return;
    try {
      const next = !bot.config.enabled;
      await apiClient.put("/circle/bot/config", { enabled: next });
      toast.success(next ? "Bot enabled — will reply on next poll" : "Bot paused");
      loadBot();
    } catch (err) {
      toast.error("Failed: " + (err.response?.data?.detail || err.message));
    }
  };

  const pollNow = async () => {
    setPolling(true);
    try {
      const { data } = await apiClient.post("/circle/bot/poll-now");
      const r = data.replied || 0, e = data.escalated || 0, s = data.seeded || 0;
      toast.success(`Poll done — replied ${r}, escalated ${e}, seeded ${s}`);
      loadBot();
    } catch (err) {
      toast.error("Poll failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setPolling(false);
    }
  };

  const resetAllStuck = async () => {
    if (!confirm(
      "Reset every thread currently in 'human takeover' back to active?\n\n" +
      "Use this when threads got stuck because of a deployment / env race. " +
      "The bot's lookback guard will auto-re-flag any threads where a coach " +
      "has been chatting in Circle's own UI on the next poll, so this is safe."
    )) return;
    setResettingAll(true);
    try {
      const { data } = await apiClient.post("/circle/bot/reset-stuck-threads");
      toast.success(`Reset ${data.modified} stuck thread${data.modified === 1 ? "" : "s"} — bot re-armed`);
      loadBot();
    } catch (err) {
      toast.error("Reset all failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setResettingAll(false);
    }
  };

  const resetThread = async (uuid) => {
    setResetting(uuid);
    try {
      await apiClient.post(`/circle/bot/reset-thread/${uuid}`);
      toast.success("Thread re-armed — bot will engage on next student message");
      loadBot();
    } catch (err) {
      toast.error("Reset failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setResetting(null);
    }
  };

  const saveCoachEmails = async () => {
    const list = coachEmailsInput.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
    if (list.length === 0) {
      toast.error("Need at least one coach email");
      return;
    }
    try {
      await apiClient.put("/circle/bot/config", { coach_emails: list });
      toast.success(`Watching ${list.length} coach${list.length === 1 ? "" : "es"}`);
      setEditingCoaches(false);
      loadBot();
    } catch (err) {
      toast.error("Save failed: " + (err.response?.data?.detail || err.message));
    }
  };

  const saveExcludedTags = async () => {
    const list = tagsInput.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      await apiClient.put("/circle/bot/config", { excluded_member_tags: list });
      toast.success(`${list.length} excluded tag${list.length === 1 ? "" : "s"} saved`);
      setEditingTags(false);
      loadBot();
    } catch (err) {
      toast.error("Save failed: " + (err.response?.data?.detail || err.message));
    }
  };

  const saveExclCoaches = async () => {
    const list = exclCoachesInput.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
    try {
      await apiClient.put("/circle/bot/config", { tag_exclusion_coach_emails: list });
      toast.success(`Tag exclusion applies to ${list.length} coach${list.length === 1 ? "" : "es"}`);
      setEditingExclCoaches(false);
      loadBot();
    } catch (err) {
      toast.error("Save failed: " + (err.response?.data?.detail || err.message));
    }
  };

  const loadSuggestions = async () => {
    setLoadingSuggs(true);
    try {
      const { data } = await apiClient.get("/circle/bot/playbook-suggestions", { params: { limit: 30 } });
      setSuggestions(data.suggestions || []);
    } catch (err) {
      toast.error("Failed to load playbook suggestions");
    } finally {
      setLoadingSuggs(false);
    }
  };

  const handleSugg = async (ticketId, action) => {
    setHandlingSugg(ticketId);
    try {
      const payload = action === "accept"
        ? { action: "accept", answer: (suggAnswers[ticketId] || "").trim() }
        : { action: "dismiss" };
      const { data } = await apiClient.post(`/circle/bot/playbook-suggestions/${ticketId}/handle`, payload);
      toast.success(action === "accept" ? "Added to playbook ✓" : "Dismissed");
      setSuggAnswers((m) => { const n = { ...m }; delete n[ticketId]; return n; });
      if (action === "accept") load();  // refresh playbook text
      loadSuggestions();
    } catch (err) {
      toast.error("Failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setHandlingSugg(null);
    }
  };

  useEffect(() => { load(); loadBot(); loadSuggestions(); }, []);

  return (
    <Panel
      title="Circle DM Bot"
      description="AI auto-responder for Circle DMs sent to your coach accounts. Polls the Circle Headless API every minute and replies in-thread (with an AI disclosure) when the playbook covers the question. Backs off permanently the moment the coach replies manually. Escalates to a support ticket when the playbook can't help, the student asks for a human, or a sensitive keyword (refund/complaint/urgent) is detected."
    >
      <div className="p-6 space-y-6">
        {/* --- Polling status block --- */}
        <div className="border border-[var(--ayci-border)] rounded-lg p-4 bg-slate-50/40">
          <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
            <div className="min-w-0 flex-1">
              <h4 className="font-semibold text-sm text-[var(--ayci-ink)]">Polling status</h4>
              <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-0.5">
                {loadingBot ? "Loading…" : bot ? (
                  <>
                    Watching: <b>{(bot.config.coach_emails || []).join(", ") || "—"}</b>{" • "}
                    Last poll: {bot.last_poll_at ? new Date(bot.last_poll_at).toLocaleString("en-GB") : "never"}
                  </>
                ) : "—"}
              </div>
              {editingCoaches && (
                <div className="mt-2 flex items-center gap-2 flex-wrap">
                  <input
                    type="text" value={coachEmailsInput}
                    onChange={(e) => setCoachEmailsInput(e.target.value)}
                    placeholder="tessa@…, coralie@…"
                    className="text-xs border border-[var(--ayci-border)] rounded px-2 py-1 w-72"
                    data-testid="bot-coach-emails-input"
                  />
                  <Button size="sm" onClick={saveCoachEmails} data-testid="bot-coach-emails-save">Save</Button>
                  <Button size="sm" variant="outline" onClick={() => setEditingCoaches(false)} data-testid="bot-coach-emails-cancel">Cancel</Button>
                  <span className="text-[10px] text-[var(--ayci-ink-muted)]">Comma-separated admin emails. Each must already be a Circle admin.</span>
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {bot && (
                <span
                  className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${bot.config.enabled ? "bg-emerald-100 text-emerald-800 border border-emerald-200" : "bg-slate-200 text-slate-700 border border-slate-300"}`}
                  data-testid="bot-status-pill"
                >
                  {bot.config.enabled ? "● Active" : "○ Paused"}
                </span>
              )}
              {isAdmin && bot && !editingCoaches && (
                <Button
                  onClick={() => { setCoachEmailsInput((bot.config.coach_emails || []).join(", ")); setEditingCoaches(true); }}
                  variant="outline" size="sm"
                  data-testid="bot-edit-coaches-btn"
                >
                  Edit coaches
                </Button>
              )}
              {isAdmin && bot && (
                <Button
                  onClick={toggleBot} variant="outline" size="sm"
                  data-testid="bot-toggle-btn"
                >
                  {bot.config.enabled ? "Pause bot" : "Resume bot"}
                </Button>
              )}
              {isAdmin && (
                <Button
                  onClick={pollNow} variant="outline" size="sm"
                  disabled={polling} data-testid="bot-poll-now-btn"
                >
                  {polling ? "Polling…" : "Poll now"}
                </Button>
              )}
              {isAdmin && (
                <Button
                  onClick={resetAllStuck} variant="outline" size="sm"
                  disabled={resettingAll} data-testid="bot-reset-all-stuck-btn"
                  className="border-amber-300 text-amber-800 hover:bg-amber-50"
                  title="Re-arm every thread currently in 'human takeover'. The bot's lookback guard will auto-re-flag any active coach conversations on the next poll."
                >
                  {resettingAll ? "Resetting…" : "Reset stuck threads"}
                </Button>
              )}
            </div>
          </div>
          {/* Live thread-state totals (across ALL polls, not just the last cycle) */}
          {bot?.state_totals && Object.keys(bot.state_totals).length > 0 && (
            <div className="border-t border-[var(--ayci-border)] pt-3">
              <div className="text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-2 font-semibold">
                Live thread state — across all coaches
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-[11px]" data-testid="bot-state-totals">
                {[
                  ["Active", bot.state_totals.active || 0, "bg-emerald-50 border-emerald-200 text-emerald-900", "Bot is watching — will reply on next student message"],
                  ["Human takeover", bot.state_totals.human_takeover || 0, "bg-violet-50 border-violet-200 text-violet-900", "Coach replied directly — bot is silent here"],
                  ["Escalated", bot.state_totals.escalated || 0, "bg-amber-50 border-amber-200 text-amber-900", "Converted to a Support Ticket — bot is silent here"],
                  ["Tag-excluded", bot.state_totals.tag_excluded || 0, "bg-pink-50 border-pink-200 text-pink-900", "Student has an excluded tag (e.g. Boss) — bot is silent here"],
                ].map(([label, n, cls, hint]) => (
                  <div key={label} className={`border rounded px-2 py-1.5 ${cls}`} title={hint}>
                    <div className="text-base font-bold leading-none">{n}</div>
                    <div className="text-[10px] uppercase tracking-wider mt-0.5">{label}</div>
                  </div>
                ))}
              </div>
              {bot.by_coach && Object.keys(bot.by_coach).length > 1 && (
                <details className="mt-2 text-[11px]" data-testid="bot-state-by-coach">
                  <summary className="cursor-pointer text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-ink)]">
                    Break down by coach
                  </summary>
                  <div className="mt-2 overflow-x-auto">
                    <table className="w-full text-[11px]">
                      <thead className="text-[var(--ayci-ink-muted)]">
                        <tr>
                          <th className="text-left font-semibold py-1 pr-3">Coach</th>
                          <th className="text-right font-semibold px-2">Active</th>
                          <th className="text-right font-semibold px-2">Human takeover</th>
                          <th className="text-right font-semibold px-2">Escalated</th>
                          <th className="text-right font-semibold px-2">Tag-excluded</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(bot.by_coach).map(([coach, counts]) => (
                          <tr key={coach} className="border-t border-[var(--ayci-border)]">
                            <td className="py-1 pr-3 font-mono text-[10px]">{coach}</td>
                            <td className="text-right px-2">{counts.active || 0}</td>
                            <td className="text-right px-2">{counts.human_takeover || 0}</td>
                            <td className="text-right px-2">{counts.escalated || 0}</td>
                            <td className="text-right px-2">{counts.tag_excluded || 0}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
            </div>
          )}
          {/* Counters from last poll */}
          {bot?.last_poll_summary && (
            <div className="grid grid-cols-2 sm:grid-cols-6 gap-2 text-center text-[11px]">
              {[
                ["Replied", bot.last_poll_summary.replied, "bg-blue-50 border-blue-200 text-blue-900"],
                ["Escalated", bot.last_poll_summary.escalated, "bg-amber-50 border-amber-200 text-amber-900"],
                ["Tag-excluded", bot.last_poll_summary.tag_excluded, "bg-pink-50 border-pink-200 text-pink-900"],
                ["Seeded", bot.last_poll_summary.seeded, "bg-slate-100 border-slate-300 text-slate-800"],
                ["Human takeover", bot.last_poll_summary.human_takeover, "bg-violet-50 border-violet-200 text-violet-900"],
                ["Skipped", bot.last_poll_summary.skipped, "bg-slate-50 border-slate-200 text-slate-700"],
              ].map(([label, n, cls]) => (
                <div key={label} className={`border rounded px-2 py-1.5 ${cls}`}>
                  <div className="text-base font-bold leading-none">{n ?? 0}</div>
                  <div className="text-[10px] uppercase tracking-wider mt-0.5">{label}</div>
                </div>
              ))}
            </div>
          )}
          {(bot?.last_poll_summary?.errors || []).length > 0 && (
            <div className="mt-2 text-[11px] bg-rose-50 border border-rose-200 text-rose-900 rounded px-2 py-1">
              <b>Errors:</b> {bot.last_poll_summary.errors.join(" • ")}
            </div>
          )}

          {/* Excluded member tags */}
          {bot && (
            <div className="mt-3 pt-3 border-t border-slate-200">
              <div className="flex items-start justify-between gap-2 flex-wrap mb-1.5">
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)]">Excluded member tags</div>
                  <div className="text-[10px] text-[var(--ayci-ink-muted)]">If a student has any of these tags, the bot stays silent (no reply, no ticket) — the coach handles it themselves in Circle.</div>
                </div>
                {isAdmin && !editingTags && (
                  <Button
                    onClick={() => { setTagsInput((bot.config.excluded_member_tags || []).join(", ")); setEditingTags(true); }}
                    variant="outline" size="sm"
                    data-testid="bot-edit-excluded-tags-btn"
                  >
                    Edit tags
                  </Button>
                )}
              </div>
              {editingTags ? (
                <div className="flex items-center gap-2 flex-wrap">
                  <input
                    type="text" value={tagsInput}
                    onChange={(e) => setTagsInput(e.target.value)}
                    placeholder="Circle Member, Autoreply hold, Interview week, AYGI 25/26"
                    className="text-xs border border-[var(--ayci-border)] rounded px-2 py-1 flex-1 min-w-[280px]"
                    data-testid="bot-excluded-tags-input"
                  />
                  <Button size="sm" onClick={saveExcludedTags} data-testid="bot-excluded-tags-save">Save</Button>
                  <Button size="sm" variant="outline" onClick={() => setEditingTags(false)} data-testid="bot-excluded-tags-cancel">Cancel</Button>
                </div>
              ) : (
                <div className="flex gap-1.5 flex-wrap" data-testid="bot-excluded-tags-list">
                  {(bot.config.excluded_member_tags || []).length === 0 ? (
                    <span className="text-[11px] italic text-[var(--ayci-ink-muted)]">No tags excluded — bot will reply to everyone.</span>
                  ) : (bot.config.excluded_member_tags || []).map((t) => (
                    <span key={t} className="text-[11px] bg-pink-50 border border-pink-200 text-pink-900 rounded px-2 py-0.5 font-medium">
                      {t}
                    </span>
                  ))}
                </div>
              )}
              {/* Which coaches the exclusion applies to */}
              <div className="mt-2 pt-2 border-t border-slate-100">
                <div className="flex items-start justify-between gap-2 flex-wrap mb-1">
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)]">Exclusion applies to</div>
                    <div className="text-[10px] text-[var(--ayci-ink-muted)]">Coaches whose DMs respect the excluded tags above. Other coaches get auto-replies for everyone.</div>
                  </div>
                  {isAdmin && !editingExclCoaches && (
                    <Button
                      onClick={() => { setExclCoachesInput((bot.config.tag_exclusion_coach_emails || []).join(", ")); setEditingExclCoaches(true); }}
                      variant="outline" size="sm"
                      data-testid="bot-edit-excl-coaches-btn"
                    >
                      Edit
                    </Button>
                  )}
                </div>
                {editingExclCoaches ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    <input
                      type="text" value={exclCoachesInput}
                      onChange={(e) => setExclCoachesInput(e.target.value)}
                      placeholder="tessa@…"
                      className="text-xs border border-[var(--ayci-border)] rounded px-2 py-1 flex-1 min-w-[280px]"
                      data-testid="bot-excl-coaches-input"
                    />
                    <Button size="sm" onClick={saveExclCoaches} data-testid="bot-excl-coaches-save">Save</Button>
                    <Button size="sm" variant="outline" onClick={() => setEditingExclCoaches(false)} data-testid="bot-excl-coaches-cancel">Cancel</Button>
                  </div>
                ) : (
                  <div className="flex gap-1.5 flex-wrap" data-testid="bot-excl-coaches-list">
                    {(bot.config.tag_exclusion_coach_emails || []).length === 0 ? (
                      <span className="text-[11px] italic text-[var(--ayci-ink-muted)]">No coaches selected — exclusion currently disabled.</span>
                    ) : (bot.config.tag_exclusion_coach_emails || []).map((e) => (
                      <span key={e} className="text-[11px] bg-slate-100 border border-slate-300 text-slate-700 rounded px-2 py-0.5 font-medium">
                        {e}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* --- Thread state table --- */}
        <div>
          <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
            <h4 className="font-semibold text-sm text-[var(--ayci-ink)]">
              Watched threads
              {bot?.total_matching != null && (
                <span className="ml-2 text-xs font-normal text-[var(--ayci-ink-muted)]">
                  ({bot.threads?.length || 0} shown of {bot.total_matching} {threadSearch || threadStateFilter ? "matching" : "total"})
                </span>
              )}
            </h4>
            <div className="flex items-center gap-2 flex-wrap">
              <input
                type="search"
                value={threadSearch}
                onChange={(e) => setThreadSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") loadBot({ search: threadSearch }); }}
                placeholder="Search by student name…"
                className="text-xs border border-[var(--ayci-border)] rounded px-2 py-1.5 w-48 focus:outline-none focus:ring-1 focus:ring-[var(--ayci-teal)]"
                data-testid="bot-threads-search"
              />
              <select
                value={threadStateFilter}
                onChange={(e) => { setThreadStateFilter(e.target.value); loadBot({ state: e.target.value }); }}
                className="text-xs border border-[var(--ayci-border)] rounded px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-[var(--ayci-teal)]"
                data-testid="bot-threads-state-filter"
              >
                <option value="">All states</option>
                <option value="active">Active</option>
                <option value="human_takeover">Human takeover</option>
                <option value="escalated">Escalated</option>
                <option value="tag_excluded">Tag-excluded</option>
              </select>
              <Button
                type="button" variant="outline" size="sm"
                onClick={() => loadBot()}
                disabled={loadingBot}
                className="h-8 text-xs px-2.5"
                data-testid="bot-threads-search-btn"
              >
                {loadingBot ? "…" : "Search"}
              </Button>
              {(threadSearch || threadStateFilter) && (
                <Button
                  type="button" variant="ghost" size="sm"
                  onClick={() => { setThreadSearch(""); setThreadStateFilter(""); loadBot({ search: "", state: "" }); }}
                  className="h-8 text-xs px-2 text-[var(--ayci-ink-muted)]"
                  data-testid="bot-threads-clear-btn"
                >
                  Clear
                </Button>
              )}
            </div>
          </div>
          {bot?.threads && bot.threads.length > 0 ? (
            <div className="space-y-1.5 max-h-96 overflow-y-auto" data-testid="bot-threads-list">
              {bot.threads.map((t) => (
                <div key={t.thread_uuid} className="text-xs bg-white border border-[var(--ayci-border)] rounded px-3 py-2 flex items-center gap-3 flex-wrap">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold truncate">{t.student_name || "—"}</span>
                      <span
                        className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border ${
                          t.state === "active" ? "bg-emerald-50 border-emerald-200 text-emerald-800" :
                          t.state === "escalated" ? "bg-amber-50 border-amber-200 text-amber-800" :
                          t.state === "human_takeover" ? "bg-violet-50 border-violet-200 text-violet-800" :
                          t.state === "tag_excluded" ? "bg-pink-50 border-pink-200 text-pink-800" :
                          "bg-slate-100 border-slate-300 text-slate-700"
                        }`}
                      >{t.state}</span>
                      {t.escalation_reason && (
                        <span className="text-[10px] text-amber-700">({t.escalation_reason})</span>
                      )}
                      {t.matched_excluded_tags?.length > 0 && (
                        <span className="text-[10px] text-pink-700">({t.matched_excluded_tags.join(", ")})</span>
                      )}
                      {t.ai_reply_count_today ? (
                        <span className="text-[10px] text-slate-600">{t.ai_reply_count_today} reply{t.ai_reply_count_today > 1 ? "ies" : ""} today</span>
                      ) : null}
                    </div>
                    {t.last_reply_text && (
                      <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-0.5 truncate" title={t.last_reply_text}>
                        Last bot reply: {t.last_reply_text.slice(0, 120)}{t.last_reply_text.length > 120 ? "…" : ""}
                      </div>
                    )}
                    <div className="text-[10px] text-slate-500 mt-0.5">
                      {t.last_activity_at ? `Last activity: ${new Date(t.last_activity_at).toLocaleString("en-GB")}` : ""}
                    </div>
                  </div>
                  {isAdmin && (t.state === "escalated" || t.state === "human_takeover" || t.state === "tag_excluded") && (
                    <Button
                      onClick={() => resetThread(t.thread_uuid)}
                      variant="outline" size="sm"
                      disabled={resetting === t.thread_uuid}
                      data-testid={`bot-thread-reset-${t.thread_uuid}`}
                    >
                      {resetting === t.thread_uuid ? "…" : "Re-arm"}
                    </Button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-[var(--ayci-ink-muted)] italic bg-white border border-dashed border-[var(--ayci-border)] rounded px-3 py-3 text-center" data-testid="bot-threads-empty">
              {threadSearch || threadStateFilter
                ? `No threads match "${threadSearch || ""}" ${threadStateFilter ? `(state: ${threadStateFilter})` : ""}`
                : loadingBot ? "Loading…" : "No threads yet"}
            </div>
          )}
        </div>

        {/* --- Playbook suggestions (self-improving) --- */}
        <div className="border-t border-[var(--ayci-border)] pt-5">
          <div className="flex items-center justify-between mb-2">
            <div>
              <h4 className="font-semibold text-sm text-[var(--ayci-ink)]">Playbook suggestions ({suggestions.filter(s => s.suggestion_status === "pending").length})</h4>
              <div className="text-[11px] text-[var(--ayci-ink-muted)]">Real student questions the bot escalated because the playbook didn't cover them. Add an answer → bot will handle the next student who asks the same thing. Dismiss to ignore.</div>
            </div>
            <Button onClick={loadSuggestions} variant="outline" size="sm" data-testid="playbook-suggestions-refresh">
              {loadingSuggs ? "Loading…" : "Refresh"}
            </Button>
          </div>
          {suggestions.length === 0 && !loadingSuggs && (
            <div className="text-xs text-[var(--ayci-ink-muted)]">No outstanding suggestions yet. They'll show up here whenever the bot escalates with reason <code>playbook_miss</code>.</div>
          )}
          <div className="space-y-2 max-h-[28rem] overflow-y-auto" data-testid="playbook-suggestions-list">
            {suggestions.map((s) => {
              const answered = s.suggestion_status === "added";
              return (
                <div
                  key={s.ticket_id}
                  className={`border rounded-md p-3 ${answered ? "bg-emerald-50/40 border-emerald-200" : "bg-white border-[var(--ayci-border)]"}`}
                  data-testid={`playbook-suggestion-${s.ticket_id}`}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-1.5">
                    <span className="text-xs font-semibold">{s.student_name || "Unknown"}</span>
                    <span className="text-[10px] text-[var(--ayci-ink-muted)]">{new Date(s.created_at).toLocaleString("en-GB")}</span>
                    {answered && (
                      <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-100 border border-emerald-200 text-emerald-800">Added</span>
                    )}
                  </div>
                  <div className="text-xs italic text-[var(--ayci-ink)] mb-2">"{s.question}"</div>
                  {!answered && isAdmin && (
                    <div className="flex items-end gap-2 flex-wrap">
                      <textarea
                        value={suggAnswers[s.ticket_id] || ""}
                        onChange={(e) => setSuggAnswers((m) => ({ ...m, [s.ticket_id]: e.target.value }))}
                        placeholder="Write the answer the bot should give next time…"
                        rows={2}
                        className="flex-1 min-w-[260px] text-xs border border-[var(--ayci-border)] rounded px-2 py-1.5 focus:border-[var(--ayci-teal)] focus:outline-none"
                        data-testid={`playbook-suggestion-input-${s.ticket_id}`}
                      />
                      <Button
                        onClick={() => handleSugg(s.ticket_id, "accept")}
                        disabled={handlingSugg === s.ticket_id || (suggAnswers[s.ticket_id] || "").trim().length < 5}
                        size="sm" style={{ backgroundColor: "var(--ayci-accent)" }}
                        data-testid={`playbook-suggestion-accept-${s.ticket_id}`}
                      >
                        {handlingSugg === s.ticket_id ? "…" : "Add to playbook"}
                      </Button>
                      <Button
                        onClick={() => handleSugg(s.ticket_id, "dismiss")}
                        disabled={handlingSugg === s.ticket_id}
                        size="sm" variant="outline"
                        data-testid={`playbook-suggestion-dismiss-${s.ticket_id}`}
                      >
                        Dismiss
                      </Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* --- Coach playbook editor (existing) --- */}
        <div className="border-t border-[var(--ayci-border)] pt-5">
          <h4 className="font-semibold text-sm text-[var(--ayci-ink)] mb-2">Coach Playbook</h4>
          <p className="text-[11px] text-[var(--ayci-ink-muted)] mb-3">
            Plain text the AI references when deciding whether it can answer. Anything not clearly covered here → escalated to the team. Sensitive keywords (refund, complaint, urgent) always escalate regardless.
          </p>
          {!isAdmin && (
            <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-3">
              Only admins can edit the playbook.
            </div>
          )}
          {meta && (
            <div className="text-xs text-[var(--ayci-ink-muted)] flex items-center gap-2 flex-wrap mb-2">
              {meta.isDefault ? (
                <span className="bg-slate-100 border border-slate-300 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider">Using default</span>
              ) : (
                <span className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider">Custom</span>
              )}
              {meta.updatedAt && (
                <span>Last edited {new Date(meta.updatedAt).toLocaleString("en-GB")} by {meta.updatedBy || "—"}</span>
              )}
            </div>
          )}
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!isAdmin || loading}
            rows={14}
            placeholder="Markdown-style FAQ. One topic per line / paragraph."
            className="w-full font-mono text-xs border border-[var(--ayci-border)] rounded-md px-3 py-2 focus:border-[var(--ayci-teal)] focus:outline-none disabled:opacity-50"
            data-testid="coach-playbook-textarea"
          />
          <div className="flex items-center justify-between gap-3 flex-wrap mt-2">
            <span className="text-[11px] text-[var(--ayci-ink-muted)]">{text.length}/8000 chars</span>
            <Button
              onClick={save}
              disabled={!isAdmin || saving || loading || text.trim().length < 10}
              style={{ backgroundColor: "var(--ayci-accent)" }}
              data-testid="coach-playbook-save"
            >
              {saving ? "Saving…" : "Save playbook"}
            </Button>
          </div>
        </div>

        {/* --- Recent webhook events (legacy / debug) --- */}
        <div className="border-t border-[var(--ayci-border)] pt-5">
          <div className="flex items-center justify-between mb-2">
            <div>
              <h4 className="font-semibold text-sm text-[var(--ayci-ink)]">Recent webhook events (legacy debug)</h4>
              <div className="text-[11px] text-[var(--ayci-ink-muted)]">Polling is the primary path now; webhook events here only fire if you still have the Circle Workflow connected.</div>
            </div>
            <Button onClick={loadEvents} variant="outline" size="sm" data-testid="coach-playbook-load-events">
              {loadingEvents ? "Loading…" : "Load latest 20"}
            </Button>
          </div>
          {events.length === 0 && !loadingEvents && (
            <div className="text-xs text-[var(--ayci-ink-muted)]">No events loaded yet — click "Load latest 20" if your Circle Workflow webhook is still active.</div>
          )}
          {events.length > 0 && (
            <div className="space-y-1.5 max-h-64 overflow-y-auto" data-testid="coach-playbook-events">
              {events.map((e, i) => (
                <div key={i} className="text-[11px] bg-slate-50 border border-[var(--ayci-border)] rounded px-2 py-1.5">
                  <div className="opacity-70">{new Date(e.received_at).toLocaleString("en-GB")}</div>
                  <pre className="whitespace-pre-wrap break-words text-[10px] mt-0.5 font-mono">{JSON.stringify(e.payload, null, 2).slice(0, 600)}</pre>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}
