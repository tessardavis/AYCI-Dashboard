import { useState } from "react";
import { Loader2, KeyRound, ShieldCheck, ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function Profile() {
  const { user } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSuccess(false);
    if (next.length < 8) {
      toast.error("New password must be at least 8 characters");
      return;
    }
    if (next !== confirm) {
      toast.error("New password and confirmation don't match");
      return;
    }
    if (next === current) {
      toast.error("New password must be different from current");
      return;
    }
    setBusy(true);
    try {
      await apiClient.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      toast.success("Password updated");
      setSuccess(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      toast.error(
        formatApiErrorDetail(err.response?.data?.detail) || "Couldn't change password",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-4 sm:p-8 max-w-2xl mx-auto" data-testid="profile-page">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-sm text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-teal)] mb-4"
        data-testid="profile-back-link"
      >
        <ArrowLeft className="w-4 h-4" /> Back to dashboard
      </Link>

      <div className="bg-white border border-[var(--ayci-border)] rounded-2xl p-8 shadow-sm">
        <div className="flex items-start gap-4 mb-6">
          <div className="w-12 h-12 rounded-full bg-[var(--ayci-teal)]/10 text-[var(--ayci-teal)] flex items-center justify-center font-display font-bold text-lg">
            {(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}
          </div>
          <div>
            <div
              className="font-display font-bold text-2xl text-[var(--ayci-ink)]"
              data-testid="profile-name"
            >
              {user?.name || "Profile"}
            </div>
            <div className="text-sm text-[var(--ayci-ink-muted)]" data-testid="profile-email">
              {user?.email}
            </div>
            <div className="text-[11px] uppercase tracking-widest text-[var(--ayci-teal)] mt-1 font-display font-semibold">
              {user?.role || ""}
            </div>
          </div>
        </div>

        <div className="border-t border-[var(--ayci-border)] pt-6">
          <div className="flex items-center gap-2 mb-1">
            <KeyRound className="w-4 h-4 text-[var(--ayci-teal)]" />
            <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
              Change password
            </h2>
          </div>
          <p className="text-xs text-[var(--ayci-ink-muted)] mb-4">
            Pick something at least 8 characters long. Your session stays active afterwards.
          </p>

          <form onSubmit={submit} className="space-y-3" data-testid="change-password-form">
            <Field
              label="Current password"
              value={current}
              onChange={setCurrent}
              testid="current-password-input"
              autoComplete="current-password"
            />
            <Field
              label="New password"
              value={next}
              onChange={setNext}
              testid="new-password-input"
              autoComplete="new-password"
            />
            <Field
              label="Confirm new password"
              value={confirm}
              onChange={setConfirm}
              testid="confirm-password-input"
              autoComplete="new-password"
            />

            <button
              type="submit"
              disabled={busy || !current || !next || !confirm}
              className="w-full bg-[var(--ayci-teal)] text-white font-display font-semibold rounded-lg px-4 py-2.5 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 transition-all"
              data-testid="change-password-submit"
            >
              {busy ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : success ? (
                <ShieldCheck className="w-4 h-4" />
              ) : (
                <KeyRound className="w-4 h-4" />
              )}
              {success ? "Password updated" : "Update password"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, testid, autoComplete }) {
  return (
    <label className="block">
      <span className="text-xs font-display font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)]">
        {label}
      </span>
      <input
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        className="mt-1 w-full bg-white border border-[var(--ayci-border)] rounded-lg px-3 py-2 text-sm font-medium text-[var(--ayci-ink)] focus:outline-none focus:border-[var(--ayci-teal)] focus:ring-1 focus:ring-[var(--ayci-teal)]/40"
        data-testid={testid}
      />
    </label>
  );
}
