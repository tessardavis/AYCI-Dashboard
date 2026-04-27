import { useCallback, useEffect, useMemo, useState } from "react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useAuth } from "@/context/AuthContext";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CheckCircle2, Circle, AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";

const STATUS_META = {
  on_track: {
    label: "On Track",
    icon: Circle,
    bg: "bg-emerald-50",
    text: "text-emerald-700",
    ring: "ring-emerald-200",
    dot: "bg-emerald-500",
  },
  off_track: {
    label: "Off Track",
    icon: AlertTriangle,
    bg: "bg-amber-50",
    text: "text-amber-700",
    ring: "ring-amber-200",
    dot: "bg-amber-500",
  },
  done: {
    label: "Done",
    icon: CheckCircle2,
    bg: "bg-sky-50",
    text: "text-sky-700",
    ring: "ring-sky-200",
    dot: "bg-sky-500",
  },
};

const NEXT_STATUS = { on_track: "off_track", off_track: "done", done: "on_track" };

export default function QuarterlyRocks() {
  const { user } = useAuth();
  const [team, setTeam] = useState([]);
  const [rocks, setRocks] = useState([]);
  const [quarter, setQuarter] = useState("Q2 2026");
  const [quarters, setQuarters] = useState(["Q2 2026"]);
  const [expandedNotes, setExpandedNotes] = useState({});
  const [notesDraft, setNotesDraft] = useState({});
  // On mobile, owner cards collapse by default (showing just a chevron + counts).
  // We default them to OPEN on initial render so first-time mobile users see the
  // rocks immediately; they can collapse the ones they don't care about.
  const [collapsedOwners, setCollapsedOwners] = useState({});

  const loadData = useCallback(async (q) => {
    try {
      const [t, r, qs] = await Promise.all([
        apiClient.get("/team"),
        apiClient.get("/rocks", { params: { quarter: q } }),
        apiClient.get("/rocks/quarters"),
      ]);
      setTeam(t.data);
      setRocks(r.data);
      setQuarters(qs.data.length > 0 ? qs.data : ["Q2 2026"]);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  }, []);

  useEffect(() => {
    loadData(quarter);
  }, [quarter, loadData]);

  const byOwner = useMemo(() => {
    const m = {};
    team.forEach((t) => (m[t.id] = { member: t, rocks: [] }));
    rocks.forEach((r) => {
      if (!m[r.owner_id]) m[r.owner_id] = { member: { id: r.owner_id, name: "Unassigned" }, rocks: [] };
      m[r.owner_id].rocks.push(r);
    });
    return Object.values(m).filter((g) => g.rocks.length > 0);
  }, [team, rocks]);

  const summary = useMemo(() => {
    const total = rocks.length;
    const onTrack = rocks.filter((r) => r.status === "on_track").length;
    const done = rocks.filter((r) => r.status === "done").length;
    const off = rocks.filter((r) => r.status === "off_track").length;
    const completedPct = total === 0 ? 0 : Math.round((done / total) * 100);
    return { total, onTrack, done, off, completedPct };
  }, [rocks]);

  const cycleStatus = async (rock) => {
    const next = NEXT_STATUS[rock.status];
    try {
      const { data } = await apiClient.patch(`/rocks/${rock.id}`, { status: next });
      setRocks((prev) => prev.map((r) => (r.id === rock.id ? data : r)));
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const saveNotes = async (rock) => {
    const notes = notesDraft[rock.id] ?? rock.notes ?? "";
    try {
      const { data } = await apiClient.patch(`/rocks/${rock.id}`, { notes });
      setRocks((prev) => prev.map((r) => (r.id === rock.id ? data : r)));
      toast.success("Notes saved");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  return (
    <div className="p-4 sm:p-6 lg:p-12 ayci-fade-up">
      <PageHeader
        eyebrow="90-Day Priorities"
        title="Quarterly Rocks"
        description="Each team member's 2–5 rocks for the quarter. Click a status pill to cycle On Track → Off Track → Done."
        right={<RocksSummary {...summary} />}
      />

      <div className="flex items-center gap-3 mb-8">
        <span className="text-xs text-[var(--ayci-ink-muted)]">Quarter:</span>
        <Select value={quarter} onValueChange={setQuarter}>
          <SelectTrigger className="w-[180px] bg-white" data-testid="rocks-quarter-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {quarters.map((q) => (
              <SelectItem key={q} value={q} data-testid={`rocks-quarter-option-${q}`}>
                {q}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-6">
        {byOwner.map(({ member, rocks: owned }) => (
          <div
            key={member.id}
            className="bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm overflow-hidden ayci-card-hover"
            data-testid={`rocks-owner-card-${member.id}`}
          >
            <button
              type="button"
              onClick={() => setCollapsedOwners((s) => ({ ...s, [member.id]: !s[member.id] }))}
              className="w-full px-4 sm:px-5 pt-4 sm:pt-5 pb-3 sm:pb-4 border-b border-[var(--ayci-border)] flex items-center gap-3 text-left lg:cursor-default"
              data-testid={`rocks-owner-toggle-${member.id}`}
            >
              <Avatar className="w-9 h-9 sm:w-10 sm:h-10">
                {member.avatar_url && <AvatarImage src={member.avatar_url} alt={member.name} />}
                <AvatarFallback className="bg-slate-100 text-slate-700 font-medium">
                  {(member.name || "??")
                    .split(" ")
                    .map((p) => p[0])
                    .slice(0, 2)
                    .join("")}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <div className="font-display font-bold text-[var(--ayci-ink)] leading-tight truncate">{member.name}</div>
                <div className="text-xs text-[var(--ayci-ink-muted)] truncate">{member.role_title || "—"}</div>
              </div>
              <div className="flex items-center gap-2 ml-auto shrink-0">
                <OwnerStatusDots rocks={owned} />
                <div className="text-xs text-[var(--ayci-ink-muted)] tabular-nums">
                  {owned.length}
                </div>
                {/* Chevron — only visible on mobile (controls collapse) */}
                <ChevronDown
                  className={`w-4 h-4 text-[var(--ayci-ink-muted)] lg:hidden transition-transform ${collapsedOwners[member.id] ? "" : "rotate-180"}`}
                />
              </div>
            </button>

            {/* Rocks list — hidden on mobile when collapsed; always shown on lg+ */}
            <ul className={`divide-y divide-[var(--ayci-border)] ${collapsedOwners[member.id] ? "hidden lg:block" : ""}`}>
              {owned.map((rock) => {
                const meta = STATUS_META[rock.status];
                const expanded = expandedNotes[rock.id];
                const draft = notesDraft[rock.id] ?? rock.notes ?? "";
                return (
                  <li key={rock.id} className="px-4 py-3 sm:px-5 sm:py-4" data-testid={`rock-${rock.id}`}>
                    <div className="flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-[var(--ayci-ink)] leading-snug">{rock.title}</div>
                        <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-1.5">
                          Due {new Date(rock.due_date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
                        </div>
                      </div>
                      <button
                        onClick={() => cycleStatus(rock)}
                        data-testid={`rock-status-${rock.id}`}
                        className={[
                          "inline-flex items-center gap-1.5 px-3 py-1.5 sm:px-2.5 sm:py-1 rounded-full text-[11px] font-medium shrink-0",
                          "ring-1 transition-transform active:scale-95 hover:scale-105",
                          meta.bg,
                          meta.text,
                          meta.ring,
                        ].join(" ")}
                        title="Click to cycle status"
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
                        {meta.label}
                      </button>
                    </div>

                    <button
                      className="mt-2 text-[11px] text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-accent)] inline-flex items-center gap-1"
                      onClick={() =>
                        setExpandedNotes((s) => ({ ...s, [rock.id]: !s[rock.id] }))
                      }
                      data-testid={`rock-notes-toggle-${rock.id}`}
                    >
                      {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                      {rock.notes ? "Notes" : "Add notes"}
                    </button>

                    {expanded && (
                      <div className="mt-2 space-y-2">
                        <Textarea
                          value={draft}
                          onChange={(e) =>
                            setNotesDraft((s) => ({ ...s, [rock.id]: e.target.value }))
                          }
                          placeholder="Update log… e.g. 12 Apr: kicked off affiliate outreach"
                          className="text-sm"
                          data-testid={`rock-notes-textarea-${rock.id}`}
                        />
                        <div className="flex justify-end">
                          <Button
                            size="sm"
                            onClick={() => saveNotes(rock)}
                            data-testid={`rock-notes-save-${rock.id}`}
                            style={{ backgroundColor: "var(--ayci-accent)" }}
                          >
                            Save
                          </Button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function OwnerStatusDots({ rocks }) {
  if (!rocks || rocks.length === 0) {
    return (
      <span className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] font-display font-semibold">
        no rocks
      </span>
    );
  }
  const counts = { on_track: 0, off_track: 0, done: 0 };
  for (const r of rocks) {
    const k = r.status in counts ? r.status : "on_track";
    counts[k] += 1;
  }
  const items = [
    { key: "off_track", color: "bg-amber-500", title: "Off track" },
    { key: "on_track", color: "bg-emerald-500", title: "On track" },
    { key: "done", color: "bg-sky-500", title: "Done" },
  ].filter((it) => counts[it.key] > 0);
  return (
    <div className="flex items-center gap-1" aria-label="Owner status summary">
      {items.map((it) => (
        <span key={it.key} className="inline-flex items-center gap-0.5" title={`${counts[it.key]} ${it.title}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${it.color}`} />
          <span className="text-[10px] tabular-nums text-[var(--ayci-ink-muted)]">{counts[it.key]}</span>
        </span>
      ))}
    </div>
  );
}

function RocksSummary({ onTrack, total, done, off, completedPct }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const offset = c - (completedPct / 100) * c;
  return (
    <div className="flex items-center gap-5 bg-white border border-[var(--ayci-border)] rounded-lg px-5 py-4 shadow-sm" data-testid="rocks-summary">
      <div className="relative w-[68px] h-[68px]">
        <svg width="68" height="68" className="-rotate-90">
          <circle cx="34" cy="34" r={r} stroke="#E2E8F0" strokeWidth="6" fill="none" />
          <circle
            cx="34"
            cy="34"
            r={r}
            stroke="var(--ayci-accent)"
            strokeWidth="6"
            fill="none"
            strokeDasharray={c}
            strokeDashoffset={offset}
            strokeLinecap="round"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="metric-number text-sm font-bold text-[var(--ayci-ink)]">{completedPct}%</span>
        </div>
      </div>
      <div className="flex gap-5">
        <Stat label="On track" value={onTrack} color="text-emerald-600" />
        <Stat label="Off track" value={off} color="text-amber-600" />
        <Stat label="Done" value={done} color="text-sky-600" />
      </div>
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div>
      <div className={`metric-number font-bold text-lg ${color}`}>{value}</div>
      <div className="text-[11px] text-[var(--ayci-ink-muted)]">{label}</div>
    </div>
  );
}
