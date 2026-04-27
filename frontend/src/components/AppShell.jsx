import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LineChart, Mountain, Rocket, Settings as SettingsIcon, LogOut, Search, Calendar, GraduationCap, AlertTriangle, UserCircle2, MessageCircle } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { PrefetchNavLink } from "@/components/PrefetchLink";

const NAV = [
  { to: "/", label: "Weekly Scorecard", icon: LineChart, testid: "sidebar-nav-scorecard", board: "weekly_scorecard" },
  { to: "/rocks", label: "Quarterly Rocks", icon: Mountain, testid: "sidebar-nav-rocks", board: "quarterly_rocks" },
  { to: "/launches", label: "Launch Dashboard", icon: Rocket, testid: "sidebar-nav-launches", board: "launches" },
  { to: "/cohort", label: "Cohort Dashboard", icon: GraduationCap, testid: "sidebar-nav-cohort", board: "cohort" },
  { to: "/interviews", label: "Upcoming Interviews", icon: Calendar, testid: "sidebar-nav-interviews", board: "interviews" },
  { to: "/coach-activity", label: "Coach Activity", icon: MessageCircle, testid: "sidebar-nav-coach-activity", board: "coach_activity" },
  { to: "/students", label: "Student Lookup", icon: Search, testid: "sidebar-nav-students", board: "students" },
  { to: "/at-risk", label: "Students at Risk", icon: AlertTriangle, testid: "sidebar-nav-at-risk", board: "at_risk" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, testid: "sidebar-nav-settings", board: "settings" },
];

export function userCanAccess(user, board) {
  if (!user) return false;
  if (user.role === "admin") return true;
  return (user.board_access || []).includes(board);
}

export default function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen flex bg-[var(--ayci-canvas)]">
      <aside
        className="w-64 shrink-0 flex flex-col sticky top-0 h-screen"
        style={{ backgroundColor: "var(--ayci-sidebar)" }}
        data-testid="app-sidebar"
      >
        <div className="px-6 pt-8 pb-6">
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center bg-white/10 p-1.5"
              aria-hidden="true"
            >
              <img
                src="/ayci-icon.png"
                alt="AYCI"
                className="w-full h-full object-contain"
                style={{ filter: "brightness(0) invert(1)" }}
              />
            </div>
            <div>
              <div className="text-white font-display font-bold tracking-tight leading-tight">AYCI Academy</div>
              <div className="text-[11px] uppercase tracking-widest text-[var(--ayci-sidebar-muted)] font-subhead">Team Dashboard</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 space-y-1">
          {NAV.filter((item) => userCanAccess(user, item.board)).map(({ to, label, icon: Icon, testid }) => (
            <PrefetchNavLink
              key={to}
              to={to}
              end={to === "/"}
              data-testid={testid}
              className={({ isActive }) =>
                [
                  "group flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-all duration-200",
                  isActive
                    ? "bg-white/10 text-white font-medium"
                    : "text-[var(--ayci-sidebar-muted)] hover:text-white hover:bg-white/5",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className="w-0.5 h-5 rounded-full transition-all"
                    style={{ backgroundColor: isActive ? "var(--ayci-accent)" : "transparent" }}
                  />
                  <Icon className="w-4 h-4" />
                  <span>{label}</span>
                </>
              )}
            </PrefetchNavLink>
          ))}
        </nav>

        <div className="px-3 pb-6 pt-4 border-t border-white/5 mx-3">
          <div className="px-3 py-2 mb-2">
            <div className="text-white text-sm font-medium truncate" data-testid="sidebar-user-name">
              {user?.name || "—"}
            </div>
            <div className="text-[var(--ayci-sidebar-muted)] text-xs capitalize">{user?.role || ""}</div>
          </div>
          <button
            onClick={() => navigate("/profile")}
            data-testid="sidebar-profile-btn"
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-[var(--ayci-sidebar-muted)] hover:text-white hover:bg-white/5 transition-all"
          >
            <UserCircle2 className="w-4 h-4" />
            My profile
          </button>
          <button
            onClick={handleLogout}
            data-testid="sidebar-logout-btn"
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-[var(--ayci-sidebar-muted)] hover:text-white hover:bg-white/5 transition-all"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </aside>

      <main className="flex-1 min-w-0 overflow-x-hidden">
        <Outlet />
      </main>
    </div>
  );
}
