import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    try {
      const res = await login(email, password);
      if (!res.ok) {
        toast.error(res.error || "Login failed");
      } else {
        toast.success("Welcome back");
      }
    } catch (err) {
      toast.error(err?.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* Left brand panel */}
      <div
        className="hidden lg:flex w-5/12 flex-col justify-between p-12 text-white relative overflow-hidden"
        style={{ backgroundColor: "var(--ayci-sidebar)" }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-11 h-11 rounded-lg flex items-center justify-center bg-white/10 p-1.5"
          >
            <img
              src="/ayci-icon.png"
              alt="AYCI"
              className="w-full h-full object-contain"
              style={{ filter: "brightness(0) invert(1)" }}
            />
          </div>
          <div className="font-display font-bold text-xl">AYCI Academy</div>
        </div>

        <div className="relative z-10 ayci-fade-up">
          <div className="text-[var(--ayci-accent)] text-xs uppercase tracking-[0.3em] mb-4">Team Dashboard</div>
          <h1 className="font-display text-5xl xl:text-6xl font-extrabold leading-[1.05] tracking-tight mb-6">
            Monday mornings,<br />answered in one screen.
          </h1>
          <p className="text-slate-300 text-base max-w-md leading-relaxed">
            Scorecard. Quarterly rocks. Launch pacing. Everything the team reviews at Monday
            stand-up — clean, fast, and always current.
          </p>
        </div>

        <div className="text-xs text-slate-400">© {new Date().getFullYear()} AYCI Academy. EOS Team Workspace.</div>

        {/* subtle grid accent */}
        <div className="pointer-events-none absolute inset-0 opacity-[0.04]"
          style={{
            backgroundImage:
              "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
            backgroundSize: "32px 32px",
          }}
        />
      </div>

      {/* Right form */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 bg-white">
        <form
          onSubmit={handleSubmit}
          className="w-full max-w-sm"
          data-testid="login-form"
          name="login"
          method="post"
          action="#"
          autoComplete="on"
        >
          <div className="mb-10">
            <h2 className="font-display text-3xl font-bold tracking-tight text-[var(--ayci-ink)]">Sign in</h2>
            <p className="text-sm text-[var(--ayci-ink-muted)] mt-2">
              Use your AYCI team account to access the dashboard.
            </p>
          </div>

          <div className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="email" className="text-[13px] font-medium">Email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="username"
                inputMode="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@ayci.com"
                required
                data-testid="login-email-input"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="text-[13px] font-medium">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                data-testid="login-password-input"
              />
            </div>
          </div>

          <Button
            type="submit"
            disabled={loading}
            data-testid="login-submit-btn"
            className="w-full mt-8 h-11 font-medium"
            style={{ backgroundColor: "var(--ayci-accent)" }}
          >
            {loading ? "Signing in…" : "Sign in"}
          </Button>

          <p className="text-xs text-[var(--ayci-ink-muted)] mt-6 leading-relaxed">
            Need access? Ask your admin to create an account for you in Settings.
          </p>
        </form>
      </div>
    </div>
  );
}
