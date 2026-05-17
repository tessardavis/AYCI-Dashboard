import { Lock } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

// Keep these two maps in sync with the route table in App.js and the
// NAV_GROUPS list in AppShell.jsx. Board IDs use snake_case; route paths
// often use kebab-case, which is why we can't just build one from the other.
const BOARD_LABELS = {
  weekly_scorecard: "Weekly Scorecard",
  quarterly_rocks: "Quarterly Rocks",
  launches: "Launch Dashboard",
  cohort: "Cohort Dashboard",
  interviews: "Upcoming Interviews",
  students: "Student Lookup",
  at_risk: "Students at Risk",
  coach_activity: "Coach Activity",
  spotlight: "Spotlight Coaching",
  leaderboard: "Cohort Leaderboard",
  tickets: "Support Tickets",
  private_videos: "Private-Tier Videos",
  settings: "Settings",
  bot: "Settings",
};

const BOARD_TO_PATH = {
  weekly_scorecard: "/",
  quarterly_rocks: "/rocks",
  launches: "/launches",
  cohort: "/cohort",
  interviews: "/interviews",
  students: "/students",
  at_risk: "/at-risk",
  coach_activity: "/coach-activity",
  spotlight: "/spotlight",
  leaderboard: "/leaderboard",
  tickets: "/tickets",
  private_videos: "/private-videos",
  settings: "/settings",
  bot: "/settings",
};

export default function NotAuthorized({ board }) {
  const { user } = useAuth();
  const allowed = (user?.board_access || []).filter((b) => b !== "settings");
  const fallbackBoard = allowed[0];
  const fallbackTo = fallbackBoard ? BOARD_TO_PATH[fallbackBoard] || "/" : "/";

  return (
    <div
      className="p-8 max-w-2xl mx-auto mt-16"
      data-testid="not-authorized-page"
    >
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center shadow-sm">
        <div className="w-12 h-12 bg-rose-50 rounded-lg mx-auto flex items-center justify-center mb-4">
          <Lock className="w-6 h-6 text-rose-600" />
        </div>
        <h1 className="font-display font-bold text-2xl text-[var(--ayci-ink)] mb-2">
          Access not granted
        </h1>
        <p className="text-sm text-[var(--ayci-ink-muted)] mb-6">
          You don't have access to <strong>{BOARD_LABELS[board] || board}</strong>.
          Ask an admin to grant you this board in Settings → Users.
        </p>
        {allowed.length > 0 ? (
          <Link
            to={fallbackTo}
            className="inline-block text-sm bg-[var(--ayci-accent)] text-white px-4 py-2 rounded-md hover:bg-[var(--ayci-accent-hover)] transition-colors"
            data-testid="not-authorized-back-btn"
          >
            Go to {BOARD_LABELS[fallbackBoard] || fallbackBoard}
          </Link>
        ) : (
          <p className="text-xs text-[var(--ayci-ink-muted)] italic">
            You don't currently have access to any boards. Contact an admin.
          </p>
        )}
      </div>
    </div>
  );
}
