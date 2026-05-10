import { useEffect, useState } from "react";
import { Loader2, Plus, X, Calendar, Clock, ExternalLink, Trash2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Link } from "react-router-dom";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";

const HOSTS = ["Tessa", "Anoop", "Charlotte", "Becky", "Coralie", "Oksana", "Arub"];

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" });
  } catch {
    return iso.slice(11, 16);
  }
}

function relativeWhen(iso) {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  const min = Math.round(ms / 60000);
  if (Math.abs(min) < 60) return min < 0 ? `${-min}m ago` : `in ${min}m`;
  const h = Math.round(min / 60);
  return h < 0 ? `${-h}h ago` : `in ${h}h`;
}

export default function TodayCallsWidget() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/today-calls");
      setItems(data?.items || []);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Couldn't load today's calls");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const removeManual = async (id) => {
    try {
      await apiClient.delete(`/today-calls/manual/${id}`);
      toast.success("Manual call removed");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Delete failed");
    }
  };

  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-xl shadow-sm" data-testid="today-calls-widget">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
        <h2 className="font-display font-bold text-[var(--ayci-ink)] flex items-center gap-2 text-base">
          <Calendar className="w-4 h-4 text-[var(--ayci-accent)]" /> Today's calls
          <span className="text-xs font-normal text-[var(--ayci-ink-muted)]">
            ({items.length})
          </span>
          <span className="ml-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded inline-flex items-center gap-0.5">
            <Sparkles className="w-3 h-3" /> Pre-warmed
          </span>
        </h2>
        <button
          onClick={() => setAdding((v) => !v)}
          className="text-xs font-semibold inline-flex items-center gap-1 px-2.5 py-1 rounded border border-slate-200 hover:bg-slate-50"
          data-testid="today-calls-add-toggle"
        >
          {adding ? <X className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
          {adding ? "Cancel" : "Add manual"}
        </button>
      </div>

      {adding && <ManualCallForm onSaved={() => { setAdding(false); load(); }} onCancel={() => setAdding(false)} />}

      <div className="divide-y divide-slate-100">
        {loading ? (
          <div className="p-6 text-center text-sm text-[var(--ayci-ink-muted)]">
            <Loader2 className="w-4 h-4 animate-spin inline mr-2" /> Loading…
          </div>
        ) : items.length === 0 ? (
          <div className="p-6 text-center text-sm text-[var(--ayci-ink-muted)]">
            No calls scheduled today.
          </div>
        ) : (
          items.map((c) => <CallRow key={c.id} call={c} onDelete={removeManual} />)
        )}
      </div>
    </div>
  );
}

// Days from now (UK calendar day) until the interview. Returns null if no
// date or the interview is already in the past.
function daysToInterview(iso) {
  if (!iso) return null;
  try {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const interview = new Date(iso);
    interview.setHours(0, 0, 0, 0);
    const days = Math.round((interview - today) / 86400000);
    if (Number.isNaN(days) || days < 0) return null;
    return days;
  } catch {
    return null;
  }
}

function InterviewFlag({ days }) {
  if (days === null || days > 7) return null;
  let label, tone;
  if (days === 0) { label = "INTERVIEW TODAY"; tone = "bg-rose-600 text-white animate-pulse"; }
  else if (days === 1) { label = "INTERVIEW TOMORROW"; tone = "bg-rose-600 text-white"; }
  else if (days <= 3) { label = `INTERVIEW IN ${days}D`; tone = "bg-rose-100 text-rose-800 border border-rose-300"; }
  else { label = `INTERVIEW IN ${days}D`; tone = "bg-amber-100 text-amber-800 border border-amber-300"; }
  return (
    <span
      className={`text-[9px] uppercase tracking-wider font-bold px-1.5 py-0 rounded whitespace-nowrap ${tone}`}
      data-testid="today-call-interview-flag"
    >
      {label}
    </span>
  );
}


function CallRow({ call, onDelete }) {
  const isManual = call.source === "manual";
  const [brief, setBrief] = useState(null);
  const [loadingBrief, setLoadingBrief] = useState(false);

  // Lazy-load on mount — backend is cached per (email, UK-date) so this is
  // a no-op after the first call.
  useEffect(() => {
    if (!call.student_email) return;
    let cancelled = false;
    setLoadingBrief(true);
    apiClient
      .get(`/today-calls/brief?email=${encodeURIComponent(call.student_email)}&name=${encodeURIComponent(call.student_name || "")}`)
      .then(({ data }) => {
        if (cancelled) return;
        setBrief(data?.lines || []);
      })
      .catch(() => { if (!cancelled) setBrief([]); })
      .finally(() => { if (!cancelled) setLoadingBrief(false); });
    return () => { cancelled = true; };
  }, [call.student_email, call.student_name]);

  return (
    <div className="px-4 py-2.5 hover:bg-slate-50/50" data-testid={`today-call-${call.id}`}>
      <div className="flex items-center gap-3">
        <div className="text-sm font-mono font-bold text-[var(--ayci-ink)] w-14 shrink-0">
          {fmtTime(call.starts_at)}
        </div>
        <div className="text-[10px] text-[var(--ayci-ink-muted)] w-12 shrink-0">
          {call.duration_min}m
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-sm text-[var(--ayci-ink)] truncate flex items-center gap-1.5 flex-wrap">
            {call.student_name || call.student_email}
            <InterviewFlag days={daysToInterview(call.interview_date)} />
            {call.tier && (
              <span
                className={
                  "text-[9px] uppercase tracking-wider font-bold px-1.5 py-0 rounded border whitespace-nowrap " +
                  (
                    String(call.tier).toLowerCase().includes("vip")
                      ? "bg-violet-100 text-violet-800 border-violet-200"
                      : "bg-sky-100 text-sky-800 border-sky-200"
                  )
                }
                title={call.tier + (call.speciality ? " · " + call.speciality : "")}
                data-testid={`today-call-tier-${call.id}`}
              >
                {call.tier}
              </span>
            )}
            {isManual && (
              <span className="text-[10px] uppercase tracking-wider font-bold text-amber-800 bg-amber-50 border border-amber-200 px-1 py-0 rounded">
                manual
              </span>
            )}
          </div>
          <div className="text-[11px] text-[var(--ayci-ink-muted)] truncate">
            with <span className="font-medium text-[var(--ayci-ink)]">{call.host}</span>
            {call.event_type && <> · {call.event_type}</>}
            {call.notes && <> · {call.notes}</>}
          </div>
        </div>
        <div className="text-[10px] text-[var(--ayci-ink-muted)] shrink-0 hidden sm:block">
          {relativeWhen(call.starts_at)}
        </div>
        <Link
          to={`/students?email=${encodeURIComponent(call.student_email)}&name=${encodeURIComponent(call.student_name || "")}`}
          className="text-xs text-[var(--ayci-accent)] font-semibold hover:underline shrink-0 inline-flex items-center gap-0.5"
          data-testid={`today-call-lookup-${call.id}`}
        >
          Lookup <ExternalLink className="w-3 h-3" />
        </Link>
        {isManual && (
          <button
            onClick={() => onDelete(call.id)}
            title="Remove manual call"
            className="text-slate-400 hover:text-rose-700 shrink-0"
            data-testid={`today-call-delete-${call.id}`}
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {/* AI brief — 3 short lines, lazily fetched + cached server-side */}
      {(loadingBrief || (brief && brief.length > 0)) && (
        <div className="ml-[88px] mt-1.5 pl-2 border-l-2 border-emerald-200/70">
          {loadingBrief && !brief && (
            <div className="text-[11px] text-[var(--ayci-ink-muted)] flex items-center gap-1.5">
              <Sparkles className="w-3 h-3 text-emerald-600 animate-pulse" />
              Building brief…
            </div>
          )}
          {brief && brief.map((line, i) => (
            <div
              key={i}
              className="text-[11.5px] text-[var(--ayci-ink-muted)] leading-relaxed flex items-start gap-1.5"
              data-testid={`today-call-brief-line-${i}-${call.id}`}
            >
              {i === 0 && <Sparkles className="w-3 h-3 text-emerald-600 mt-0.5 shrink-0" />}
              {i !== 0 && <span className="w-3 shrink-0" />}
              <span>{line}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ManualCallForm({ onSaved, onCancel }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [host, setHost] = useState(HOSTS[0]);
  // Default to "now + 30min" rounded to next quarter, in local time
  const defaultStart = (() => {
    const d = new Date();
    d.setMinutes(d.getMinutes() + 30, 0, 0);
    d.setMinutes(Math.ceil(d.getMinutes() / 15) * 15);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  })();
  const [startsLocal, setStartsLocal] = useState(defaultStart);
  const [duration, setDuration] = useState(30);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!name.trim() || !email.trim() || !startsLocal) {
      toast.error("Name, email and time are required");
      return;
    }
    setSaving(true);
    try {
      // Convert local datetime-input to UTC ISO
      const startsUtc = new Date(startsLocal).toISOString();
      await apiClient.post("/today-calls/manual", {
        student_name: name.trim(),
        student_email: email.trim(),
        host,
        starts_at: startsUtc,
        duration_min: Number(duration) || 30,
        notes: notes.trim() || null,
      });
      toast.success("Manual call added · Drive summary pre-warming");
      onSaved();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Couldn't add call");
    } finally {
      setSaving(false);
    }
  };

  const inputCls = "w-full px-2 py-1 border border-slate-200 rounded text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]/40";
  return (
    <div className="px-4 py-3 bg-slate-50/60 border-b border-slate-100 grid grid-cols-2 sm:grid-cols-5 gap-2">
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Student name" className={inputCls} data-testid="manual-call-name" />
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="student@email.com" className={inputCls + " col-span-2 sm:col-span-1"} data-testid="manual-call-email" />
      <select value={host} onChange={(e) => setHost(e.target.value)} className={inputCls} data-testid="manual-call-host">
        {HOSTS.map((h) => <option key={h} value={h}>{h}</option>)}
      </select>
      <input type="datetime-local" value={startsLocal} onChange={(e) => setStartsLocal(e.target.value)} className={inputCls} data-testid="manual-call-time" />
      <select value={duration} onChange={(e) => setDuration(e.target.value)} className={inputCls} data-testid="manual-call-duration">
        <option value="15">15 min</option>
        <option value="30">30 min</option>
        <option value="45">45 min</option>
        <option value="60">60 min</option>
        <option value="90">90 min</option>
      </select>
      <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="notes (optional)" className={inputCls + " col-span-2 sm:col-span-4"} data-testid="manual-call-notes" />
      <div className="col-span-2 sm:col-span-1 flex justify-end gap-1.5">
        <Button variant="outline" size="sm" onClick={onCancel} disabled={saving}>Cancel</Button>
        <Button size="sm" onClick={save} disabled={saving} className="bg-[var(--ayci-accent)] hover:bg-[var(--ayci-accent)]/90 text-white" data-testid="manual-call-save">
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <><Clock className="w-3 h-3 mr-1" /> Add</>}
        </Button>
      </div>
    </div>
  );
}
