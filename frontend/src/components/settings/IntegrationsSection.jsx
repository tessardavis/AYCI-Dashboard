import { useEffect, useState } from "react";
import { Loader2, Save, Send, MessageSquare, Hash, Eye, EyeOff, Zap, Video, UserPlus, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Paste-in UI for the two Slack integrations that are stored in MongoDB
 * (rather than env vars) so admins can configure production without needing
 * a redeploy or DevTools console.
 *
 *  1. Slack Bot Token (xoxb-...) — powers assignment DMs on Support Tickets
 *  2. Slack #circle-days webhook — powers the "coach posted >3 videos this
 *     week" alert from Coach Activity
 */
export default function IntegrationsSection({ isAdmin }) {
  return (
    <div className="space-y-6 max-w-2xl" data-testid="integrations-section">
      <IntakeStatusCard isAdmin={isAdmin} />
      <SlackBotTokenCard isAdmin={isAdmin} />
      <CircleDaysWebhookCard isAdmin={isAdmin} />
      <PrivateVideoAlertsCard isAdmin={isAdmin} />
      <ZapierCircleReplyCard isAdmin={isAdmin} />
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
    if (!iso) return "—";
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
            <b>pending</b> until the 15-min mirror reconciles them onto their Monday row — that should
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
                      {r.name || r.email || "—"}
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
      toast.success(sent ? `Posted ${sent} alert${sent === 1 ? "" : "s"} to #private-tiers` : "Nothing pending — no alerts posted");
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
              <span className="text-emerald-700 font-semibold break-all">Configured — {state.masked}</span>
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
                    {preview.mode === "preview" ? "Preview — would alert:" : "Sent:"}
                  </div>
                  <div>
                    Interview imminent: {preview.mode === "preview" ? (imm?.candidates?.length || 0) : (imm?.alerts_posted || 0)}
                    {imm?.candidates?.length ? ` — ${imm.candidates.map((c) => `${c.name} (${c.when})`).join(", ")}` : ""}
                  </div>
                  <div>
                    Unanswered &gt;24h: {preview.mode === "preview" ? (un?.candidates?.length || 0) : (un?.alerts_posted || 0)}
                    {un?.candidates?.length ? ` — ${un.candidates.map((c) => `${c.name} (${c.hours}h)`).join(", ")}` : ""}
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
        toast.success(`Test DM sent — check Slack for '${email}'`);
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
                Configured — {state.masked}
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
                Configured — {state.masked}
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
            Zapier — Send to Circle (Private-Tier Videos)
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
                Configured — {state.masked}
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
