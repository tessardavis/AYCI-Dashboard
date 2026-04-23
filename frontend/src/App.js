import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import Login from "@/pages/Login";
import AppShell from "@/components/AppShell";
import WeeklyScorecard from "@/pages/WeeklyScorecard";
import QuarterlyRocks from "@/pages/QuarterlyRocks";
import LaunchDashboard from "@/pages/LaunchDashboard";
import StudentLookup from "@/pages/StudentLookup";
import UpcomingInterviews from "@/pages/UpcomingInterviews";
import Settings from "@/pages/Settings";

function Protected() {
  const { user, ready } = useAuth();
  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--ayci-canvas)]">
        <div className="text-[var(--ayci-ink-muted)] text-sm" data-testid="auth-loading">Loading…</div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
}

function PublicOnly() {
  const { user, ready } = useAuth();
  if (!ready) return null;
  if (user) return <Navigate to="/" replace />;
  return <Outlet />;
}

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<PublicOnly />}>
              <Route path="/login" element={<Login />} />
            </Route>
            <Route element={<Protected />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<WeeklyScorecard />} />
                <Route path="/rocks" element={<QuarterlyRocks />} />
                <Route path="/launches" element={<LaunchDashboard />} />
                <Route path="/students" element={<StudentLookup />} />
                <Route path="/interviews" element={<UpcomingInterviews />} />
                <Route path="/settings" element={<Settings />} />
              </Route>
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster richColors position="top-right" />
      </AuthProvider>
    </div>
  );
}

export default App;
