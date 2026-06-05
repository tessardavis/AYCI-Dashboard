import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import Login from "@/pages/Login";
import AppShell, { userCanAccess } from "@/components/AppShell";
import WeeklyScorecard from "@/pages/WeeklyScorecard";
import QuarterlyRocks from "@/pages/QuarterlyRocks";
import LaunchDashboard from "@/pages/LaunchDashboard";
import StudentLookup from "@/pages/StudentLookup";
import StudentsDB from "@/pages/StudentsDB";
import WebhookSubscriptions from "@/pages/WebhookSubscriptions";
import StudentsAtRisk from "@/pages/StudentsAtRisk";
import UpcomingInterviews from "@/pages/UpcomingInterviews";
import CohortDashboard from "@/pages/CohortDashboard";
import CoachActivity from "@/pages/CoachActivity";
import SpotlightCoaching from "@/pages/SpotlightCoaching";
import CohortLeaderboard from "@/pages/CohortLeaderboard";
import SupportTickets from "@/pages/SupportTickets";
import PrivateVideos from "@/pages/PrivateVideos";
import Settings from "@/pages/Settings";
import Profile from "@/pages/Profile";
import NotAuthorized from "@/pages/NotAuthorized";

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

function BoardGuard({ board, children }) {
  const { user } = useAuth();
  // Accept a list of acceptable boards (any one grants access)
  const boards = Array.isArray(board) ? board : [board];
  if (!boards.some((b) => userCanAccess(user, b))) {
    return <NotAuthorized board={boards.join(" / ")} />;
  }
  return children;
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
                <Route path="/" element={<BoardGuard board="weekly_scorecard"><WeeklyScorecard /></BoardGuard>} />
                <Route path="/rocks" element={<BoardGuard board="quarterly_rocks"><QuarterlyRocks /></BoardGuard>} />
                <Route path="/launches" element={<BoardGuard board="launches"><LaunchDashboard /></BoardGuard>} />
                <Route path="/cohort" element={<BoardGuard board="cohort"><CohortDashboard /></BoardGuard>} />
                <Route path="/students" element={<BoardGuard board="students"><StudentLookup /></BoardGuard>} />
                <Route path="/students-db" element={<BoardGuard board="students"><StudentsDB /></BoardGuard>} />
                <Route path="/webhooks" element={<BoardGuard board="students"><WebhookSubscriptions /></BoardGuard>} />
                <Route path="/at-risk" element={<BoardGuard board="at_risk"><StudentsAtRisk /></BoardGuard>} />
                <Route path="/interviews" element={<BoardGuard board="interviews"><UpcomingInterviews /></BoardGuard>} />
                <Route path="/coach-activity" element={<BoardGuard board="coach_activity"><CoachActivity /></BoardGuard>} />
                <Route path="/spotlight" element={<BoardGuard board="spotlight"><SpotlightCoaching /></BoardGuard>} />
                <Route path="/leaderboard" element={<BoardGuard board="leaderboard"><CohortLeaderboard /></BoardGuard>} />
                <Route path="/tickets" element={<BoardGuard board="tickets"><SupportTickets /></BoardGuard>} />
                <Route path="/private-videos" element={<BoardGuard board="private_videos"><PrivateVideos /></BoardGuard>} />
                <Route path="/settings" element={<BoardGuard board={["settings","bot"]}><Settings /></BoardGuard>} />
                <Route path="/profile" element={<Profile />} />
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
