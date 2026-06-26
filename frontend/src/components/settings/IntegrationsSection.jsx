import { useEffect, useState } from "react";
import { Loader2, Save, Send, MessageSquare, Hash, Eye, EyeOff, Zap, Video, UserPlus, RefreshCw, Link2, MessagesSquare, Calendar, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Paste-in UI for the two Slack integrations that are stored in MongoDB
 * (rather than env vars) so admins can configure production without needing
 * a redeploy or DevTools console.
 *
 *  1. Slack Bot Token (xoxb-...) - powers assignment DMs on Support Tickets
 *  2. Slack #circle-days webhook - powers the "coach posted >3 videos this
 *     week" alert from Coach Activity
 */
export default function IntegrationsSection({ isAdmin }) {
  // Non-admins reach this tab only via the "students" board - show them just the
  // private-chat tooling (find/create), not the rest of the admin integrations.
  if (!isAdmin) {
    return (
      <div className="space-y-6 max-w-2xl" data-testid="integrations-section">
        <PrivateChatSetupCard isAdmin={isAdmin} />
      </div>
    );
  }
  return (
    <div className="space-y-6 max-w-2xl" data-testid="integrations-section">
      <IntakeStatusCard isAdmin={isAdmin} />
      <CircleEmailGapsCard isAdmin={isAdmin} />
      <PrivateChatSetupCard isAdmin={isAdmin} />
      <SlackBotTokenCard isAdmin={isAdmin} />
      <CircleDaysWebhookCard isAdmin={isAdmin} />
      <PrivateVideoAlertsCard isAdmin={isAdmin} />
      <ZapierCircleReplyCard isAdmin={isAdmin} />
      <CalendlyBonusCallCard isAdmin={isAdmin} />
      <UnmatchedBonusBookingsCard isAdmin={isAdmin} />
    </div>
  );
}

/**
 * Bonus-call bookings the dashboard couldn't tie to a student (booked under an
 * unknown email). Each can be linked to the right student - the booking email is
 * saved onto their "Other emails" so it auto-matches next time. Hidden when empty.
 */
function UnmatchedBonusBookingsCard({ isAdmin }) {
  const [state, setState] = useState({ loading: true, bookings: [] });
  const [linking, setLinking] = useState(null);
  const [emails, setEmails] = useState({});

  const load = async () => {
    try {
      const { data } = await apiClient.get("/bonus-call/unmatched");
      setState({ loading: false, bookings: data?.bookings || [] });
    } catch {
      setState({ loading: false, bookings: [] });
    }
  };
  useEffect(() => { load(); }, []);

  const link = async (b) => {
    const studentEmail = (emails[b.invitee_uri] || "").trim();
    if (!studentEmail) { toast.error("Enter the student's email on file to link to"); return; }
    setLinking(b.invitee_uri);
    try {
      const { data } = await apiClient.post("/bonus-call/link", {
        invitee_uri: b.invitee_uri, student_email: studentEmail,
      });
      toast.success(`Linked ${b.email} to ${data.name || studentEmail}`);
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Couldn't link");
    } finally {
      setLinking(null);
    }
  };

  if (state.loading || state.bookings.length === 0) return null;

  return (
    <div className="bg-white border border-amber-200 rounded-xl p-5 sm:p-6" data-testid="unmatched-bonus-card">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg bg-amber-50 border border-amber-200 flex items-center justify-center text-amber-700 shrink-0">
          <AlertTriangle className="w-5 h-5" />
        </div>
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Unmatched bonus-call bookings
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            These were booked under an email we don't have on a student record. Link each to the right
            student - their booking email gets saved to "Other emails" so it matches automatically next time.
          </p>
        </div>
      </div>
      <div className="space-y-2">
        {state.bookings.map((b) => (
          <div key={b.invitee_uri} className="border border-[var(--ayci-border)] rounded-lg p-3 flex flex-col sm:flex-row sm:items-center gap-2">
            <div className="min-w-0 flex-1 text-sm">
              <div className="font-medium text-[var(--ayci-ink)] truncate">{b.name || b.email}</div>
              <div className="text-xs text-[var(--ayci-ink-muted)] truncate">
                {b.email}{b.date ? ` · ${b.date}` : ""}{b.coach ? ` · ${b.coach}` : ""}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Input
                placeholder="student's email on file"
                value={emails[b.invitee_uri] || ""}
                onChange={(e) => setEmails((m) => ({ ...m, [b.invitee_uri]: e.target.value }))}
                className="h-8 text-sm w-full sm:w-56"
              />
              <Button size="sm" disabled={linking === b.invitee_uri || !isAdmin} onClick={() => link(b)}>
                {linking === b.invitee_uri ? <Loader2 className="w-4 h-4 animate-spin" /> : <Link2 className="w-4 h-4 mr-1.5" />}
                Link
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * One-click switch-on for the Calendly bonus-call automation (replaces the
 * Zapier "Bonus Call Booked" zap). Connecting registers a Calendly webhook
 * subscription + stores its signing key - see backend/routes/calendly.py.
 */
function CalendlyBonusCallCard({ isAdmin }) {
  const [state, setState] = useState({ loading: true, connected: false, callback: "" });
  const [busy, setBusy] = useState(false);
  const [backfilling, setBackfilling] = useState(false);

  const load = async () => {
    try {
      const { data } = await apiClient.get("/admin/calendly/status");
      setState({ loading: false, connected: !!data?.connected, callback: data?.callback || "" });
    } catch (err) {
      setState({ loading: false, connected: false, callback: "" });
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load Calendly status");
    }
  };

  useEffect(() => { load(); }, []);

  const connect = async () => {
    if (!isAdmin) return;
    setBusy(true);
    try {
      const { data } = await apiClient.post("/admin/calendly/register-webhook", {}, { timeout: 30000 });
      if (data?.ok) {
        toast.success("Calendly connected - bonus-call bookings now flow into the dashboard");
        await load();
      } else {
        toast.error(data?.error || "Couldn't connect Calendly");
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Couldn't connect Calendly");
    } finally {
      setBusy(false);
    }
  };

  const backfill = async () => {
    if (!isAdmin) return;
    setBackfilling(true);
    try {
      const { data } = await apiClient.post("/admin/calendly/backfill-bonus-tags", {}, { timeout: 120000 });
      if (data?.ok) {
        toast.success(
          `Backfill done - tagged ${data.tagged} of ${data.unique_emails} past bookers` +
          (data.recorded ? ` · ${data.recorded} recorded` : "") +
          (data.not_found ? ` · ${data.not_found} not in dashboard` : "")
        );
      } else {
        toast.error(data?.error || "Backfill failed");
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Backfill failed");
    } finally {
      setBackfilling(false);
    }
  };

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6"
      data-testid="calendly-bonus-call-card"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-lg bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-700 shrink-0">
          <Calendar className="w-5 h-5" />
        </div>
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Calendly bonus call
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            When someone books the AYCI Bonus Call, the dashboard tags them in Kit
            (stops their reminder emails), records the booking, and posts to
            #fulfillment-team - no Zapier. Connect once to switch it on.
          </p>
        </div>
      </div>

      {state.loading ? (
        <div className="flex items-center gap-2 text-sm text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-4 h-4 animate-spin" /> Checking status…
        </div>
      ) : (
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2 text-sm">
            <span className={`inline-block w-2 h-2 rounded-full ${state.connected ? "bg-emerald-500" : "bg-slate-300"}`} />
            <span className={state.connected ? "text-emerald-700 font-semibold" : "text-[var(--ayci-ink-muted)]"}>
              {state.connected ? "Connected" : "Not connected"}
            </span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Button
              variant="outline"
              onClick={backfill}
              disabled={!isAdmin || backfilling}
              title="Tag everyone who has already booked a bonus call (catches bookings missed while the zaps were off)"
              data-testid="calendly-backfill-btn"
            >
              {backfilling ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              Tag past bookings
            </Button>
            <Button onClick={connect} disabled={!isAdmin || busy} data-testid="calendly-connect-btn">
              {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
              {state.connected ? "Re-connect" : "Connect Calendly"}
            </Button>
          </div>
        </div>
      )}

      {state.connected && state.callback && (
        <p className="text-xs text-[var(--ayci-ink-muted)] mt-3 break-all">
          Receiving bookings at <code className="bg-slate-100 px-1 rounded">{state.callback}</code>
        </p>
      )}
    </div>
  );
}

/**
 * Read-only diagnostic for the Monday "Create Item" retirement: shows which
 * students arrived via the Zapier `intake` endpoint in the last N days, so we
 * can confirm signups are landing in the dashboard directly before pulling the
 * Monday create path. Backed by GET /api/students-db/intake-recent.
 */
function IntakeStatusCard() {
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);

  const load = async (d = days) => {
    setLoading(true);
    try {
      const { data } = await apiClient.get(`/students-db/intake-recent?days=${d}`);
      setData(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Couldn't load intake status");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(days); /* eslint-disable-next-line */ }, [days]);

  const counts = data?.counts || {};
  const recent = data?.recent || [];
  const pending = counts.pending_reconcile_total ?? 0;

  const fmtWhen = (iso) => {
    if (!iso) return "-";
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      });
    } catch { return iso; }
  };

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6"
      data-testid="intake-status-card"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-lg bg-indigo-50 border border-indigo-200 flex items-center justify-center text-indigo-700 shrink-0">
          <UserPlus className="w-5 h-5" />
        </div>
        <div className="flex-1">
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Signup intake (Monday retirement)
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            New signups now land in the dashboard directly via the Zapier{" "}
            <code className="text-xs bg-slate-100 px-1 rounded">intake</code> endpoint. Use this to
            confirm real signups are arriving with the right tier &amp; cohort{" "}
            <b>before removing the Monday "Create Item" steps</b>. Brand-new students show as{" "}
            <b>pending</b> until the 15-min mirror reconciles them onto their Monday row - that should
            clear within ~15&nbsp;min.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <div className="flex rounded-lg border border-[var(--ayci-border)] overflow-hidden text-sm">
          {[7, 14, 30].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              disabled={loading}
              className={`px-3 py-1.5 ${days === d ? "bg-[var(--ayci-accent)] text-white font-semibold" : "bg-white text-[var(--ayci-ink-muted)] hover:bg-slate-50"}`}
              data-testid={`intake-days-${d}`}
            >
              {d}d
            </button>
          ))}
        </div>
        <Button variant="outline" size="sm" onClick={() => load(days)} disabled={loading} data-testid="intake-refresh">
          {loading ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1.5" />}
          Refresh
        </Button>
      </div>

      {loading && !data ? (
        <div className="text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3 mb-4" data-testid="intake-counts">
            <Stat label={`Touched · ${days}d`} value={counts.intake_touched_in_window ?? 0} />
            <Stat label={`New · ${days}d`} value={counts.created_in_window ?? 0} />
            <Stat
              label="Pending reconcile"
              value={pending}
              tone={pending > 0 ? "amber" : "emerald"}
            />
          </div>

          {recent.length === 0 ? (
            <p className="text-sm text-[var(--ayci-ink-muted)]">
              No intake activity in the last {days} days.
            </p>
          ) : (
            <div className="border border-[var(--ayci-border)] rounded-lg divide-y divide-[var(--ayci-border)] max-h-72 overflow-y-auto" data-testid="intake-recent-list">
              {recent.map((r) => (
                <div key={r.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-[var(--ayci-ink)] truncate">
                      {r.name || r.email || "-"}
                    </div>
                    <div className="text-xs text-[var(--ayci-ink-muted)] truncate">
                      {[r.tier, r.cohort_joined, r.source].filter(Boolean).join(" · ") || r.email}
                    </div>
                  </div>
                  {r.pending_reconcile && (
                    <span className="shrink-0 text-[11px] font-semibold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200">
                      pending
                    </span>
                  )}
                  <span className="shrink-0 text-xs text-[var(--ayci-ink-muted)] tabular-nums">
                    {fmtWhen(r.dashboard_edited_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value, tone = "ink" }) {
  const valueClass =
    tone === "amber" ? "text-amber-700"
    : tone === "emerald" ? "text-emerald-700"
    : "text-[var(--ayci-ink)]";
  return (
    <div className="bg-slate-50 border border-[var(--ayci-border)] rounded-lg px-3 py-2.5 text-center">
      <div className={`font-display font-bold text-2xl tabular-nums ${valueClass}`}>{value}</div>
      <div className="text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mt-0.5">{label}</div>
    </div>
  );
}

/**
 * Finds private-tier students we likely failed to link to their Circle
 * identity because they joined Circle under a different email than they signed
 * up with - the root cause of coach group chats never getting created. Each
 * suggested match gets a one-click "Link" that PATCHes circle_email onto the
 * row (pinned dashboard-owned), which unblocks everything downstream.
 * Backed by GET /api/students-db/circle-email-gaps + PATCH /students-db/{id}.
 */
function CircleEmailGapsCard({ isAdmin }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [linkingId, setLinkingId] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/students-db/circle-email-gaps");
      setData(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Couldn't load Circle email gaps");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Link a row by writing the chosen email to circle_email, then drop it from
  // its bucket optimistically (it's no longer a gap).
  const link = async (row, email, bucket) => {
    if (!isAdmin || !email) return;
    setLinkingId(row.id);
    try {
      await apiClient.patch(`/students-db/${encodeURIComponent(row.id)}`, { circle_email: email });
      toast.success(`Linked ${row.name || row.kajabi_email || "student"} → ${email}`);
      setData((d) => {
        if (!d) return d;
        return {
          ...d,
          [bucket]: (d[bucket] || []).filter((x) => x.id !== row.id),
          counts: { ...d.counts, [bucket]: Math.max(0, (d.counts?.[bucket] || 1) - 1) },
        };
      });
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Link failed");
    } finally {
      setLinkingId(null);
    }
  };

  const counts = data?.counts || {};
  const mismatch = data?.likely_mismatch || [];
  const inCircle = data?.email_in_circle || [];

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6"
      data-testid="circle-email-gaps-card"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-lg bg-rose-50 border border-rose-200 flex items-center justify-center text-rose-700 shrink-0">
          <Link2 className="w-5 h-5" />
        </div>
        <div className="flex-1">
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Circle email gaps (unlinked private chats)
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            Private-tier students with no <code className="text-xs bg-slate-100 px-1 rounded">circle_email</code> -
            usually because they joined Circle under a different email than they signed up with, so the upstream
            match failed and their coach chat never got created. <b>Link</b> writes the matched Circle email onto
            the row (pinned, so the sync won't undo it), which unblocks the downstream automation.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <Button variant="outline" size="sm" onClick={load} disabled={loading} data-testid="circle-gaps-refresh">
          {loading ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1.5" />}
          Refresh
        </Button>
      </div>

      {loading && !data ? (
        <div className="text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Scanning…
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3 mb-5" data-testid="circle-gaps-counts">
            <Stat label="Likely mismatch" value={counts.likely_mismatch ?? 0} tone={(counts.likely_mismatch ?? 0) > 0 ? "amber" : "emerald"} />
            <Stat label="Email on Circle" value={counts.email_in_circle ?? 0} />
            <Stat label="Not on Circle" value={counts.not_on_circle ?? 0} />
          </div>

          {!isAdmin && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
              View-only - linking requires admin.
            </p>
          )}

          {mismatch.length > 0 && (
            <div className="mb-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-2">
                Likely mismatches - different email on Circle
              </p>
              <div className="border border-[var(--ayci-border)] rounded-lg divide-y divide-[var(--ayci-border)]" data-testid="circle-gaps-mismatch-list">
                {mismatch.map((r) => (
                  <div key={r.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-[var(--ayci-ink)] truncate flex items-center gap-2">
                        {r.name || "-"}
                        {!r.has_chat && (
                          <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded bg-rose-100 text-rose-700 border border-rose-200">
                            no chat
                          </span>
                        )}
                        {typeof r.match_score === "number" && (
                          <span className="text-[11px] text-[var(--ayci-ink-muted)]">{r.match_score}% match</span>
                        )}
                      </div>
                      <div className="text-xs text-[var(--ayci-ink-muted)] truncate">
                        <span className="line-through opacity-70">{r.kajabi_email || "-"}</span>
                        {" → "}
                        <span className="font-medium text-[var(--ayci-ink)]">{r.circle_email}</span>
                        {r.circle_name && r.circle_name !== r.name ? ` (Circle: ${r.circle_name})` : ""}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      onClick={() => link(r, r.circle_email, "likely_mismatch")}
                      disabled={!isAdmin || linkingId === r.id}
                      data-testid={`circle-gaps-link-${r.id}`}
                    >
                      {linkingId === r.id ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Link2 className="w-4 h-4 mr-1.5" />}
                      Link
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {inCircle.length > 0 && (
            <div className="mb-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-2">
                Their signup email is already on Circle - quick link
              </p>
              <div className="border border-[var(--ayci-border)] rounded-lg divide-y divide-[var(--ayci-border)]" data-testid="circle-gaps-incircle-list">
                {inCircle.map((r) => (
                  <div key={r.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-[var(--ayci-ink)] truncate flex items-center gap-2">
                        {r.name || "-"}
                        {!r.has_chat && (
                          <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded bg-rose-100 text-rose-700 border border-rose-200">
                            no chat
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-[var(--ayci-ink-muted)] truncate">{r.kajabi_email || "-"}</div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => link(r, r.kajabi_email, "email_in_circle")}
                      disabled={!isAdmin || linkingId === r.id}
                      data-testid={`circle-gaps-link-${r.id}`}
                    >
                      {linkingId === r.id ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Link2 className="w-4 h-4 mr-1.5" />}
                      Link
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {mismatch.length === 0 && inCircle.length === 0 && (
            <p className="text-sm text-[var(--ayci-ink-muted)]">
              Nothing to link - no private-tier students with a resolvable Circle email gap.
              {(counts.not_on_circle ?? 0) > 0 && ` (${counts.not_on_circle} aren't on Circle yet - nothing to link there.)`}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function PrivateVideoAlertsCard({ isAdmin }) {
  const [state, setState] = useState({ loading: true, configured: false, masked: "" });
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState("");        // "preview" | "send" | ""
  const [preview, setPreview] = useState(null); // last preview/send result

  const load = async () => {
    try {
      const { data } = await apiClient.get("/private-videos/alerts/webhook");
      setState({ loading: false, configured: !!data?.configured, masked: data?.masked || "" });
    } catch (err) {
      setState({ loading: false, configured: false, masked: "" });
    }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!isAdmin) return;
    const v = (value || "").trim();
    if (v && !v.startsWith("https://hooks.slack.com/")) {
      toast.error("Expected a Slack webhook URL starting with 'https://hooks.slack.com/'");
      return;
    }
    setSaving(true);
    try {
      const { data } = await apiClient.post("/private-videos/alerts/webhook", { url: v });
      if (data?.ok === false) {
        toast.error(data.error || "Save failed");
      } else {
        toast.success(v ? "#private-tiers webhook saved" : "#private-tiers webhook cleared");
        setValue("");
        await load();
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async () => {
    setBusy("preview");
    setPreview(null);
    try {
      const { data } = await apiClient.get("/private-videos/alerts/preview");
      setPreview({ mode: "preview", ...data });
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Preview failed");
    } finally {
      setBusy("");
    }
  };

  const sendNow = async () => {
    if (!isAdmin) return;
    if (!window.confirm("Post any pending private-video alerts to #private-tiers now?")) return;
    setBusy("send");
    setPreview(null);
    try {
      const { data } = await apiClient.post("/private-videos/alerts/test");
      const sent = (data?.interview_imminent?.alerts_posted || 0) + (data?.unanswered_24h?.alerts_posted || 0);
      toast.success(sent ? `Posted ${sent} alert${sent === 1 ? "" : "s"} to #private-tiers` : "Nothing pending - no alerts posted");
      setPreview({ mode: "send", ...data });
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Send failed");
    } finally {
      setBusy("");
    }
  };

  const imm = preview?.interview_imminent;
  const un = preview?.unanswered_24h;

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6"
      data-testid="private-video-alerts-card"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-lg bg-violet-50 border border-violet-200 flex items-center justify-center text-violet-700 shrink-0">
          <Video className="w-5 h-5" />
        </div>
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Slack #private-tiers video alerts
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            Posts to <code className="text-xs bg-slate-100 px-1 rounded">#private-tiers</code> when a private
            video is submitted by a student whose interview is <b>today or tomorrow</b> (urgent), and when any
            video has gone <b>&gt;24h without being marked Done</b>. Create an{" "}
            <a href="https://api.slack.com/messaging/webhooks" target="_blank" rel="noreferrer"
               className="text-[var(--ayci-accent)] underline">Incoming Webhook</a>{" "}
            for #private-tiers and paste the URL here.
          </p>
        </div>
      </div>

      {state.loading ? (
        <div className="text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 text-sm mb-4" data-testid="private-video-alerts-status">
            <span className={`inline-block w-2 h-2 rounded-full ${state.configured ? "bg-emerald-500" : "bg-slate-400"}`} />
            {state.configured ? (
              <span className="text-emerald-700 font-semibold break-all">Configured - {state.masked}</span>
            ) : (
              <span className="text-slate-500">Not configured (falls back to the general Slack webhook if set)</span>
            )}
          </div>

          <div className="flex gap-2">
            <Input
              type="text"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="https://hooks.slack.com/services/T.../B.../..."
              disabled={!isAdmin || saving}
              className="flex-1 font-mono text-xs"
              data-testid="private-video-alerts-input"
            />
            <Button onClick={save} disabled={!isAdmin || saving || !value.trim()} data-testid="private-video-alerts-save">
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Save
            </Button>
          </div>

          {isAdmin && (
            <div className="mt-5 pt-5 border-t border-[var(--ayci-border)]">
              <div className="flex gap-2">
                <Button variant="outline" onClick={runPreview} disabled={!!busy} data-testid="private-video-alerts-preview">
                  {busy === "preview" ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Eye className="w-4 h-4 mr-2" />}
                  Preview (no posts)
                </Button>
                <Button variant="outline" onClick={sendNow} disabled={!!busy} data-testid="private-video-alerts-send">
                  {busy === "send" ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
                  Send pending now
                </Button>
              </div>

              {preview && (
                <div className="mt-3 text-xs text-[var(--ayci-ink-muted)] bg-slate-50 border border-[var(--ayci-border)] rounded-lg p-3 space-y-1">
                  <div className="font-semibold text-[var(--ayci-ink)]">
                    {preview.mode === "preview" ? "Preview - would alert:" : "Sent:"}
                  </div>
                  <div>
                    Interview imminent: {preview.mode === "preview" ? (imm?.candidates?.length || 0) : (imm?.alerts_posted || 0)}
                    {imm?.candidates?.length ? ` - ${imm.candidates.map((c) => `${c.name} (${c.when})`).join(", ")}` : ""}
                  </div>
                  <div>
                    Unanswered &gt;24h: {preview.mode === "preview" ? (un?.candidates?.length || 0) : (un?.alerts_posted || 0)}
                    {un?.candidates?.length ? ` - ${un.candidates.map((c) => `${c.name} (${c.hours}h)`).join(", ")}` : ""}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/**
 * Phase 0 of the dashboard-native private-chat migration (Route 2). Edit the
 * coach config (who's in every chat + the welcome sender + opener text), then
 * preview which private-tier students would get a chat - matched on either
 * email so dual-email students are caught - and create each chat with one
 * click. Manual only; nothing runs on a schedule.
 * Backed by /students-db/private-chat/{config,preview} + .../{id}/create-private-chat.
 */
const PC_AUDIENCES = [
  ["private_plus", "Private Plus"],
  ["vip", "VIP"],
  ["boost_and_go", "Boost & Go"],
  ["boost_and_go_plus", "Boost & Go Plus"],
];

function PrivateChatSetupCard({ isAdmin }) {
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState(null);
  const [coaches, setCoaches] = useState([]);
  const [senderEmail, setSenderEmail] = useState("");
  const [templates, setTemplates] = useState({});
  const [selectedAud, setSelectedAud] = useState(PC_AUDIENCES[0][0]);
  const [savingCfg, setSavingCfg] = useState(false);
  const [creatingId, setCreatingId] = useState(null);
  const [audit, setAudit] = useState(null);
  const [auditing, setAuditing] = useState(false);

  const loadPreview = async () => {
    const { data } = await apiClient.get("/students-db/private-chat/preview");
    setPreview(data);
  };

  const loadAll = async () => {
    setLoading(true);
    try {
      const [{ data: cfg }] = await Promise.all([
        apiClient.get("/students-db/private-chat/config"),
        loadPreview(),
      ]);
      setCoaches(cfg.coaches || []);
      setSenderEmail(cfg.sender_email || "");
      setTemplates(cfg.welcome_templates || {});
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Couldn't load private-chat setup");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  const setCoachEmail = (i, email) =>
    setCoaches((cs) => cs.map((c, idx) => (idx === i ? { ...c, email } : c)));

  const saveConfig = async () => {
    if (!isAdmin) return;
    setSavingCfg(true);
    try {
      const { data } = await apiClient.post("/students-db/private-chat/config", {
        coaches, sender_email: senderEmail, welcome_templates: templates,
      });
      setCoaches(data.coaches || []);
      setSenderEmail(data.sender_email || "");
      setTemplates(data.welcome_templates || {});
      toast.success("Coach config saved");
      await loadPreview();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Save failed");
    } finally {
      setSavingCfg(false);
    }
  };

  const createChat = async (row) => {
    setCreatingId(row.id);
    try {
      // Creation runs in the background server-side (it can take up to ~1 min).
      await apiClient.post(`/students-db/${encodeURIComponent(row.id)}/create-private-chat`);
      toast(`Creating chat for ${row.name || row.id}… the list updates as it completes (up to ~1 min).`);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Couldn't start creating - try again.");
      setCreatingId(null);
      return;
    }
    // Poll the preview - the row drops off "Ready" once the chat is created (or
    // its existing chat is linked); if their DMs are off it moves to "Awaiting DMs".
    for (const ms of [7000, 9000, 14000]) {
      await new Promise((r) => setTimeout(r, ms));
      try { await loadPreview(); } catch { /* keep polling */ }
    }
    setCreatingId(null);
  };

  const runAudit = async () => {
    setAuditing(true);
    try {
      const { data } = await apiClient.get("/students-db/private-chat/no-chat-audit");
      if (data.ok === false) { toast.error(data.error || "Audit failed"); setAudit(null); }
      else setAudit(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Audit failed");
    } finally {
      setAuditing(false);
    }
  };

  const emailedCoaches = coaches.filter((c) => (c.email || "").trim());
  const configReady = preview?.config_ready;
  const ready = preview?.ready || [];
  const auditNoChat = audit?.no_chat || [];

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6"
      data-testid="private-chat-setup-card"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-lg bg-teal-50 border border-teal-200 flex items-center justify-center text-teal-700 shrink-0">
          <MessagesSquare className="w-5 h-5" />
        </div>
        <div className="flex-1">
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Private chat setup <span className="text-xs font-normal text-[var(--ayci-ink-muted)]">(Phase 0 · manual)</span>
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            Creates the coach group chat for private-tier students from the dashboard, matching them to Circle on
            <b> either email</b> (so students who joined under a different email aren't missed). Set the coaches once,
            then create each chat with one click. Nothing runs automatically.
          </p>
          <a
            href="https://docs.google.com/document/d/1BF12Qx9CcJKzXlnlIgXm4exuFfrXtL9bByzp7QqPfYI/edit"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 mt-2 text-sm font-semibold text-teal-700 hover:underline"
            title="How to find who's been missed, handle DMs-off / dual-email, and create chats"
          >
            📄 Troubleshooting guide
          </a>
        </div>
      </div>

      {loading ? (
        <div className="text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : (
        <>
          {/* Coach config - admin setup only. Coralie/Megan (students board) see
              the find/create tooling below, not this. */}
          {!isAdmin && (
            <p className="text-xs text-[var(--ayci-ink-muted)] bg-slate-50 border border-[var(--ayci-border)] rounded-lg px-3 py-2 mb-4">
              Coaches &amp; welcome messages are set up by an admin. Use the list below to create any missing chats.
            </p>
          )}
          {isAdmin && (
          <div className="border border-[var(--ayci-border)] rounded-lg p-4 mb-5">
            <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-3">
              Coaches in every chat - enter each one's Circle email
            </p>
            <div className="space-y-2">
              {coaches.map((c, i) => (
                <div key={c.name + i} className="flex items-center gap-2">
                  <span className="w-20 shrink-0 text-sm font-medium text-[var(--ayci-ink)]">{c.name}</span>
                  <Input
                    type="email"
                    value={c.email || ""}
                    onChange={(e) => setCoachEmail(i, e.target.value)}
                    placeholder="their-circle-email@…"
                    disabled={!isAdmin || savingCfg}
                    className="flex-1 font-mono text-xs"
                    data-testid={`pc-coach-${c.name}`}
                  />
                  <label className="flex items-center gap-1 text-xs text-[var(--ayci-ink-muted)] shrink-0 w-24" title="Posts the welcome message">
                    <input
                      type="radio"
                      name="pc-sender"
                      checked={!!c.email && senderEmail === c.email.trim().toLowerCase()}
                      onChange={() => setSenderEmail((c.email || "").trim().toLowerCase())}
                      disabled={!isAdmin || !(c.email || "").trim() || savingCfg}
                    />
                    sends opener
                  </label>
                </div>
              ))}
            </div>

            <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)] mt-4 mb-2">
              Welcome message per tier
              <span className="font-normal normal-case"> - placeholders: {"{first_name} {last_name} {email} {tier} {video_allowance}"}</span>
            </p>
            <div className="flex flex-wrap gap-1 mb-2">
              {PC_AUDIENCES.map(([key, label]) => {
                const filled = (templates[key] || "").trim();
                return (
                  <button
                    key={key}
                    onClick={() => setSelectedAud(key)}
                    className={`px-2.5 py-1 rounded text-xs border flex items-center gap-1.5 ${selectedAud === key ? "bg-[var(--ayci-accent)] text-white border-transparent" : "bg-white text-[var(--ayci-ink-muted)] border-[var(--ayci-border)] hover:bg-slate-50"}`}
                    data-testid={`pc-aud-${key}`}
                  >
                    <span className={`inline-block w-1.5 h-1.5 rounded-full ${filled ? "bg-emerald-500" : "bg-slate-300"}`} />
                    {label}
                  </button>
                );
              })}
            </div>
            <textarea
              value={templates[selectedAud] || ""}
              onChange={(e) => setTemplates((t) => ({ ...t, [selectedAud]: e.target.value }))}
              disabled={!isAdmin || savingCfg}
              rows={9}
              placeholder={`No message yet for ${PC_AUDIENCES.find(([k]) => k === selectedAud)?.[1]} - paste it here.`}
              className="w-full text-sm rounded-lg border border-[var(--ayci-border)] px-3 py-2 disabled:bg-slate-50 font-mono"
              data-testid="pc-welcome"
            />

            <div className="flex justify-end mt-3">
              <Button onClick={saveConfig} disabled={!isAdmin || savingCfg} data-testid="pc-save-config">
                {savingCfg ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
                Save config
              </Button>
            </div>
          </div>
          )}

          {/* Preview + create */}
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)]">
              Ready to create ({preview?.counts?.ready ?? 0}) · not on Circle ({preview?.counts?.not_on_circle ?? 0})
              {(preview?.counts?.awaiting_dms ?? 0) > 0 && ` · awaiting DMs (${preview.counts.awaiting_dms})`}
            </p>
            <Button variant="outline" size="sm" onClick={loadPreview} data-testid="pc-refresh-preview">
              <RefreshCw className="w-4 h-4 mr-1.5" /> Refresh
            </Button>
          </div>

          {!configReady && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
              Add every coach's Circle email and pick who sends the opener, then Save - creating is disabled until the config is complete{emailedCoaches.length ? "" : ""}.
            </p>
          )}

          {ready.length === 0 ? (
            <p className="text-sm text-[var(--ayci-ink-muted)]">
              No private-tier students are currently on Circle without a chat.
              {(preview?.counts?.not_on_circle ?? 0) > 0 && ` (${preview.counts.not_on_circle} aren't on Circle yet.)`}
            </p>
          ) : (
            <div className="border border-[var(--ayci-border)] rounded-lg divide-y divide-[var(--ayci-border)] max-h-80 overflow-y-auto" data-testid="pc-ready-list">
              {ready.map((r) => (
                <div key={r.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-[var(--ayci-ink)] truncate">{r.name || "-"}</div>
                    <div className="text-xs text-[var(--ayci-ink-muted)] truncate">
                      {[r.tier, r.circle_email].filter(Boolean).join(" · ")}
                      {r.matched_via === "name" ? " · matched by name" : r.matched_via === "circle_email" ? " · via circle email" : ""}
                      {!r.has_template && <span className="text-amber-700"> · no {r.audience || "tier"} template</span>}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    onClick={() => createChat(r)}
                    disabled={!configReady || !r.has_template || creatingId === r.id}
                    title={!r.has_template ? `Add a welcome message for ${r.audience || "this tier"} first` : undefined}
                    data-testid={`pc-create-${r.id}`}
                  >
                    {creatingId === r.id ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Send className="w-4 h-4 mr-1.5" />}
                    Create chat
                  </Button>
                </div>
              ))}
            </div>
          )}

          {(preview?.awaiting_dms?.length ?? 0) > 0 && (
            <div className="mt-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-orange-700 mb-2">
                Awaiting DMs ({preview.awaiting_dms.length}) - chat couldn't be created; ask them to turn Circle DMs on, then click Create
              </p>
              <div className="border border-orange-200 bg-orange-50/40 rounded-lg divide-y divide-orange-100 max-h-56 overflow-y-auto">
                {preview.awaiting_dms.map((r) => (
                  <div key={r.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-[var(--ayci-ink)] truncate">{r.name || "-"}</div>
                      <div className="text-xs text-[var(--ayci-ink-muted)] truncate">
                        {[r.tier, r.kajabi_email].filter(Boolean).join(" · ")} · {r.status}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => createChat(r)}
                      disabled={creatingId === r.id}
                      title="Once they've enabled Circle DMs, retry the create"
                    >
                      {creatingId === r.id ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Send className="w-4 h-4 mr-1.5" />}
                      Retry
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Backlog audit - students with no actual coach group chat in Circle */}
          <div className="mt-6 pt-5 border-t border-[var(--ayci-border)]">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)]">
                Backlog audit - no group chat in Circle
              </p>
              <Button variant="outline" size="sm" onClick={runAudit} disabled={auditing} data-testid="pc-run-audit">
                {auditing ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1.5" />}
                Run audit
              </Button>
            </div>
            <p className="text-xs text-[var(--ayci-ink-muted)] mb-3 max-w-prose">
              Checks Circle directly for every private-tier student - lists those <b>not in any coach group chat</b>,
              even if a (dead) chat URL exists on their row. The likely DMs-off / dual-email / never-created backlog;
              the cause is confirmed when you try to create the chat.
            </p>
            {audit && (
              <>
                <p className="text-xs text-[var(--ayci-ink-muted)] mb-2">
                  Checked {(audit.coaches_checked || []).map((c) => c.email).join(", ") || "-"} ·{" "}
                  {audit.group_chats_scanned} group chats scanned ·{" "}
                  <b className={auditNoChat.length ? "text-orange-700" : "text-emerald-700"}>{auditNoChat.length}</b> with no chat ·{" "}
                  {audit.counts?.not_on_circle ?? 0} not on Circle
                </p>
                {auditNoChat.length > 0 && (
                  <div className="border border-[var(--ayci-border)] rounded-lg divide-y divide-[var(--ayci-border)] max-h-80 overflow-y-auto" data-testid="pc-audit-list">
                    {auditNoChat.map((r) => (
                      <div key={r.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                        <div className="min-w-0 flex-1">
                          <div className="font-medium text-[var(--ayci-ink)] truncate">{r.name || "-"}</div>
                          <div className="text-xs text-[var(--ayci-ink-muted)] truncate">
                            {[r.tier, r.email].filter(Boolean).join(" · ")}
                            {r.has_dead_url && <span className="text-orange-700"> · has dead chat URL</span>}
                            {r.private_chat_status && <span className="text-orange-700"> · {r.private_chat_status}</span>}
                          </div>
                        </div>
                        <Button
                          size="sm"
                          onClick={() => createChat(r)}
                          disabled={!isAdmin || !configReady || creatingId === r.id}
                          title={!configReady ? "Complete the coach config first" : undefined}
                          data-testid={`pc-audit-create-${r.id}`}
                        >
                          {creatingId === r.id ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Send className="w-4 h-4 mr-1.5" />}
                          Create chat
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function SlackBotTokenCard({ isAdmin }) {
  const [state, setState] = useState({ loading: true, configured: false, masked: "" });
  const [value, setValue] = useState("");
  const [show, setShow] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testEmail, setTestEmail] = useState("");
  const [testing, setTesting] = useState(false);

  const load = async () => {
    try {
      const { data } = await apiClient.get("/slack/bot-token");
      setState({ loading: false, configured: !!data?.configured, masked: data?.masked || "" });
    } catch (err) {
      setState({ loading: false, configured: false, masked: "" });
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load token status");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (!isAdmin) return;
    const v = (value || "").trim();
    if (v && !v.startsWith("xoxb-")) {
      toast.error("Slack bot tokens must start with 'xoxb-' (not xapp- or xoxp-)");
      return;
    }
    setSaving(true);
    try {
      const { data } = await apiClient.post("/slack/bot-token", { value: v });
      if (data?.ok === false) {
        toast.error(data.error || "Save failed");
      } else {
        toast.success(v ? "Slack bot token saved" : "Slack bot token cleared");
        setValue("");
        await load();
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const sendTest = async () => {
    if (!isAdmin) return;
    const email = testEmail.trim().toLowerCase();
    if (!email) {
      toast.error("Enter the email of a teammate in your Slack workspace");
      return;
    }
    setTesting(true);
    try {
      const { data } = await apiClient.post("/slack/test-dm", { email });
      if (data?.ok) {
        toast.success(`Test DM sent - check Slack for '${email}'`);
      } else {
        toast.error(
          data?.error === "users_not_found"
            ? `No Slack user found with email '${email}' (check the email matches their Slack account)`
            : data?.error || "Slack rejected the DM"
        );
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Test failed");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6"
      data-testid="slack-bot-token-card"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-lg bg-emerald-50 border border-emerald-200 flex items-center justify-center text-emerald-700 shrink-0">
          <MessageSquare className="w-5 h-5" />
        </div>
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Slack bot token
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            Sends a private DM to a team member when a support ticket is
            assigned to them. Get this from{" "}
            <a
              href="https://api.slack.com/apps"
              target="_blank"
              rel="noreferrer"
              className="text-[var(--ayci-accent)] underline"
            >
              api.slack.com/apps
            </a>
            {" → your app → OAuth & Permissions → Bot User OAuth Token."}{" "}
            Starts with <code className="text-xs bg-slate-100 px-1 rounded">xoxb-</code>.
          </p>
        </div>
      </div>

      {state.loading ? (
        <div className="text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : (
        <>
          <div
            className="flex items-center gap-2 text-sm mb-4"
            data-testid="slack-bot-token-status"
          >
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                state.configured ? "bg-emerald-500" : "bg-slate-400"
              }`}
            />
            {state.configured ? (
              <span className="text-emerald-700 font-semibold">
                Configured - {state.masked}
              </span>
            ) : (
              <span className="text-slate-500">Not configured</span>
            )}
          </div>

          <div className="flex gap-2">
            <Input
              type={show ? "text" : "password"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="xoxb-..."
              disabled={!isAdmin || saving}
              className="flex-1 font-mono text-sm"
              data-testid="slack-bot-token-input"
            />
            <Button
              variant="outline"
              size="icon"
              onClick={() => setShow((s) => !s)}
              disabled={!isAdmin}
              data-testid="slack-bot-token-toggle-visibility"
              title={show ? "Hide" : "Show"}
            >
              {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </Button>
            <Button
              onClick={save}
              disabled={!isAdmin || saving || !value.trim()}
              data-testid="slack-bot-token-save"
            >
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Save
            </Button>
          </div>

          {state.configured && isAdmin && (
            <div className="mt-5 pt-5 border-t border-[var(--ayci-border)]">
              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-2">
                Send test DM
              </p>
              <div className="flex gap-2">
                <Input
                  type="email"
                  value={testEmail}
                  onChange={(e) => setTestEmail(e.target.value)}
                  placeholder="your-email@domain.com"
                  disabled={testing}
                  className="flex-1"
                  data-testid="slack-test-dm-email"
                />
                <Button
                  variant="outline"
                  onClick={sendTest}
                  disabled={testing || !testEmail.trim()}
                  data-testid="slack-test-dm-send"
                >
                  {testing ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
                  Send test
                </Button>
              </div>
              <p className="text-xs text-[var(--ayci-ink-muted)] mt-2">
                Must be the email address the recipient uses to log into Slack.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CircleDaysWebhookCard({ isAdmin }) {
  const [state, setState] = useState({ loading: true, configured: false, masked: "" });
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const { data } = await apiClient.get("/coach-activity/circle-video-alerts/webhook");
      setState({ loading: false, configured: !!data?.configured, masked: data?.masked || "" });
    } catch (err) {
      setState({ loading: false, configured: false, masked: "" });
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (!isAdmin) return;
    const v = (value || "").trim();
    if (v && !v.startsWith("https://hooks.slack.com/")) {
      toast.error("Expected a Slack webhook URL starting with 'https://hooks.slack.com/'");
      return;
    }
    setSaving(true);
    try {
      await apiClient.post("/coach-activity/circle-video-alerts/webhook", { url: v });
      toast.success(v ? "#circle-days webhook saved" : "#circle-days webhook cleared");
      setValue("");
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6"
      data-testid="circle-days-webhook-card"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-lg bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-700 shrink-0">
          <Hash className="w-5 h-5" />
        </div>
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Slack #circle-days webhook
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            Posts a one-line alert to <code className="text-xs bg-slate-100 px-1 rounded">#circle-days</code>{" "}
            whenever a coach posts more than 3 videos in a calendar week. Create an{" "}
            <a
              href="https://api.slack.com/messaging/webhooks"
              target="_blank"
              rel="noreferrer"
              className="text-[var(--ayci-accent)] underline"
            >
              Incoming Webhook
            </a>
            {" "}scoped to the #circle-days channel and paste the URL here.
          </p>
        </div>
      </div>

      {state.loading ? (
        <div className="text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : (
        <>
          <div
            className="flex items-center gap-2 text-sm mb-4"
            data-testid="circle-days-webhook-status"
          >
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                state.configured ? "bg-emerald-500" : "bg-slate-400"
              }`}
            />
            {state.configured ? (
              <span className="text-emerald-700 font-semibold break-all">
                Configured - {state.masked}
              </span>
            ) : (
              <span className="text-slate-500">Not configured</span>
            )}
          </div>

          <div className="flex gap-2">
            <Input
              type="text"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="https://hooks.slack.com/services/T.../B.../..."
              disabled={!isAdmin || saving}
              className="flex-1 font-mono text-xs"
              data-testid="circle-days-webhook-input"
            />
            <Button
              onClick={save}
              disabled={!isAdmin || saving || !value.trim()}
              data-testid="circle-days-webhook-save"
            >
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Save
            </Button>
          </div>
        </>
      )}
    </div>
  );
}


function ZapierCircleReplyCard({ isAdmin }) {
  const [state, setState] = useState({ loading: true, configured: false, masked: "" });
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const { data } = await apiClient.get("/private-videos/zapier-webhook");
      setState({ loading: false, configured: !!data?.configured, masked: data?.masked || "" });
    } catch (err) {
      setState({ loading: false, configured: false, masked: "" });
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (!isAdmin) return;
    const v = (value || "").trim();
    if (v && !v.startsWith("https://hooks.zapier.com/")) {
      toast.error("Expected a Zapier webhook URL starting with 'https://hooks.zapier.com/'");
      return;
    }
    setSaving(true);
    try {
      const { data } = await apiClient.post("/private-videos/zapier-webhook", { url: v });
      if (data?.ok === false) {
        toast.error(data.error || "Save failed");
      } else {
        toast.success(v ? "Zapier webhook saved" : "Zapier webhook cleared");
        setValue("");
        await load();
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-6"
      data-testid="zapier-circle-reply-card"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-lg bg-amber-50 border border-amber-200 flex items-center justify-center text-amber-700 shrink-0">
          <Zap className="w-5 h-5" />
        </div>
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            Zapier - Send to Circle (Private-Tier Videos)
          </h2>
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5 max-w-prose">
            When a coach hits "Send to Circle" on a private-tier video, the
            dashboard POSTs the voicenote URL + student details to this Zapier
            webhook. The zap then posts a fixed message into the student's
            Circle Group DM. Find the URL in the zap's "Catch Hook" trigger
            (looks like <code className="text-xs bg-slate-100 px-1 rounded">https://hooks.zapier.com/hooks/catch/…</code>).
          </p>
        </div>
      </div>

      {state.loading ? (
        <div className="text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : (
        <>
          <div
            className="flex items-center gap-2 text-sm mb-4"
            data-testid="zapier-circle-reply-status"
          >
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                state.configured ? "bg-emerald-500" : "bg-slate-400"
              }`}
            />
            {state.configured ? (
              <span className="text-emerald-700 font-semibold break-all">
                Configured - {state.masked}
              </span>
            ) : (
              <span className="text-slate-500">Not configured</span>
            )}
          </div>

          <div className="flex gap-2">
            <Input
              type="text"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="https://hooks.zapier.com/hooks/catch/…/…/"
              disabled={!isAdmin || saving}
              className="flex-1 font-mono text-xs"
              data-testid="zapier-circle-reply-input"
            />
            <Button
              onClick={save}
              disabled={!isAdmin || saving || !value.trim()}
              data-testid="zapier-circle-reply-save"
            >
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Save
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
