import { useRef, useState } from "react";
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
  const passwordRef = useRef(null);

  // On failed login, clear the password and re-focus the field so the user
  // can immediately retry without having to click back into it.
  const handleLoginFailure = (message) => {
    toast.error(message || "Login failed");
    setPassword("");
    setTimeout(() => passwordRef.current?.focus(), 0);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    try {
      const res = await login(email, password);
      if (!res.ok) {
        handleLoginFailure(res.error);
      }
    } catch (err) {
      handleLoginFailure(err?.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* Left brand panel */}
      <div
        className="hidden lg:flex w-5/12 flex-col items-center justify-center p-12 text-white relative overflow-hidden"
        style={{ backgroundColor: "var(--ayci-sidebar)" }}
      >
        <div className="relative z-10 flex flex-col items-center text-center">
          <div className="w-28 h-28 rounded-2xl flex items-center justify-center bg-white/10 p-5 mb-8">
            <img
              src="/ayci-icon.png"
              alt="AYCI Academy"
              className="w-full h-full object-contain"
              style={{ filter: "brightness(0) invert(1)" }}
            />
          </div>
          <h1 className="font-display text-4xl xl:text-5xl font-extrabold leading-tight tracking-tight">
            AYCI Academy
          </h1>
          <div className="text-[var(--ayci-accent)] text-sm uppercase tracking-[0.3em] mt-3">
            Team Dashboard
          </div>
        </div>

        <div className="absolute bottom-8 text-xs text-slate-400">
          © {new Date().getFullYear()} AYCI Academy
        </div>

        {/* subtle grid accent */}
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.04]"
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
                ref={passwordRef}
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
