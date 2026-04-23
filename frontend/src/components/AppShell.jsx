import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LineChart, Mountain, Rocket, Settings as SettingsIcon, LogOut, Search } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const NAV = [
  { to: "/", label: "Weekly Scorecard", icon: LineChart, testid: "sidebar-nav-scorecard" },
  { to: "/rocks", label: "Quarterly Rocks", icon: Mountain, testid: "sidebar-nav-rocks" },
  { to: "/launches", label: "Launch Dashboard", icon: Rocket, testid: "sidebar-nav-launches" },
  { to: "/students", label: "Student Lookup", icon: Search, testid: "sidebar-nav-students" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, testid: "sidebar-nav-settings" },
];

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
              className="w-9 h-9 rounded-lg flex items-center justify-center font-display font-extrabold text-[var(--ayci-sidebar)]"
              style={{ backgroundColor: "var(--ayci-accent)" }}
              aria-hidden="true"
            >
              A
            </div>
            <div>
              <div className="text-white font-display font-bold tracking-tight leading-tight">AYCI Academy</div>
              <div className="text-[11px] uppercase tracking-widest text-[var(--ayci-sidebar-muted)]">Team Dashboard</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 space-y-1">
          {NAV.map(({ to, label, icon: Icon, testid }) => (
            <NavLink
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
            </NavLink>
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
