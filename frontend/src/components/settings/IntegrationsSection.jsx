import { useEffect, useState } from "react";
import { Loader2, Save, Send, MessageSquare, Hash, Eye, EyeOff, Zap } from "lucide-react";
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
      <SlackBotTokenCard isAdmin={isAdmin} />
      <CircleDaysWebhookCard isAdmin={isAdmin} />
      <ZapierCircleReplyCard isAdmin={isAdmin} />
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
