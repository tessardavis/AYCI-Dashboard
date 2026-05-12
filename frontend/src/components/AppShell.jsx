import { useState, useEffect } from "react";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { LineChart, Mountain, Rocket, Settings as SettingsIcon, LogOut, Search, Calendar, GraduationCap, AlertTriangle, UserCircle2, MessageCircle, Menu, X, Bell, Sparkles, Trophy, LifeBuoy, ChevronDown, Video } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { PrefetchNavLink } from "@/components/PrefetchLink";
import { apiClient } from "@/lib/api";

// Sidebar information architecture — collapsible groups at the top so they're
// the primary navigation surface, then top-level items (Tickets, Settings)
// underneath.
const NAV_GROUPS = [
  {
    type: "group",
    id: "community",
    label: "Community",
    defaultOpen: true,
    items: [
      { to: "/leaderboard", label: "Cohort Leaderboard", icon: Trophy, testid: "sidebar-nav-leaderboard", board: "leaderboard" },
      { to: "/coach-activity", label: "Coach Activity", icon: MessageCircle, testid: "sidebar-nav-coach-activity", board: "coach_activity" },
      { to: "/cohort", label: "Cohort Dashboard", icon: GraduationCap, testid: "sidebar-nav-cohort", board: "cohort" },
      { to: "/interviews", label: "Upcoming Interviews", icon: Calendar, testid: "sidebar-nav-interviews", board: "interviews" },
      { to: "/spotlight", label: "Spotlight Coaching", icon: Sparkles, testid: "sidebar-nav-spotlight", board: "spotlight" },
      { to: "/private-videos", label: "Private-Tier Videos", icon: Video, testid: "sidebar-nav-private-videos", board: "private_videos" },
      { to: "/students", label: "Student Lookup", icon: Search, testid: "sidebar-nav-students", board: "students" },
    ],
  },
  {
    type: "group",
    id: "growth",
    label: "Growth",
    defaultOpen: false,
    items: [
      { to: "/", label: "Weekly Scorecard", icon: LineChart, testid: "sidebar-nav-scorecard", board: "weekly_scorecard", end: true },
      { to: "/rocks", label: "Quarterly Rocks", icon: Mountain, testid: "sidebar-nav-rocks", board: "quarterly_rocks" },
      { to: "/launches", label: "Launch Dashboard", icon: Rocket, testid: "sidebar-nav-launches", board: "launches" },
      { to: "/at-risk", label: "Students at Risk", icon: AlertTriangle, testid: "sidebar-nav-at-risk", board: "at_risk" },
    ],
  },
  {
    type: "item",
    to: "/tickets",
    label: "Support Tickets",
    icon: LifeBuoy,
    testid: "sidebar-nav-tickets",
    board: "tickets",
  },
  {
    type: "item",
    to: "/settings",
    label: "Settings",
    icon: SettingsIcon,
    testid: "sidebar-nav-settings",
    board: ["settings", "bot"],
  },
];

export function userCanAccess(user, board) {
  if (!user) return false;
  if (user.role === "admin") return true;
  if (Array.isArray(board)) {
    return board.some((b) => (user.board_access || []).includes(b));
  }
  return (user.board_access || []).includes(board);
}

// Single nav row — used both for top-level items and inside groups.
function NavItem({ item, indent = false }) {
  const { to, label, icon: Icon, testid, end } = item;
  return (
    <PrefetchNavLink
      to={to}
      end={!!end || to === "/"}
      data-testid={testid}
      className={({ isActive }) =>
        [
          "group flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-all duration-200",
          indent ? "pl-6" : "",
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
  );
}

// Collapsible nav group. Open/closed state persists in localStorage so the
// sidebar feels stable across reloads.
function NavGroup({ id, label, defaultOpen, items, currentPath }) {
  const storageKey = `ayci.nav.group.${id}`;
  const containsActive = items.some(
    (it) => it.to === currentPath || (it.to !== "/" && currentPath.startsWith(it.to)),
  );
  const [open, setOpen] = useState(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw === "1") return true;
      if (raw === "0") return false;
    } catch {
      // ignore
    }
    return defaultOpen;
  });
  // Auto-open the group if the user navigates to a route inside it (so the
  // active row is never hidden behind a collapsed group).
  useEffect(() => {
    if (containsActive && !open) setOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containsActive]);

  const toggle = () => {
    setOpen((v) => {
      const nv = !v;
      try {
        window.localStorage.setItem(storageKey, nv ? "1" : "0");
      } catch {
        // ignore quota / private mode
      }
      return nv;
    });
  };

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        data-testid={`sidebar-group-${id}`}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--ayci-sidebar-muted)] hover:text-white transition-colors"
      >
        <span>{label}</span>
        <ChevronDown
          className={`w-3.5 h-3.5 transition-transform duration-200 ${open ? "" : "-rotate-90"}`}
        />
      </button>
      <div
        className={`overflow-hidden transition-[max-height,opacity] duration-200 ${
          open ? "max-h-[600px] opacity-100" : "max-h-0 opacity-0"
        }`}
      >
        <div className="space-y-1 pb-1">
          {items.map((it) => (
            <NavItem key={it.to} item={it} indent />
          ))}
        </div>
      </div>
    </div>
  );
}

export default function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close drawer whenever the route changes (e.g. user taps a nav link)
  const closeDrawer = () => setMobileOpen(false);
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen lg:flex bg-[var(--ayci-canvas)]">
      {/* Mobile top bar — visible below lg */}
      <header
        className="lg:hidden sticky top-0 z-30 flex items-center justify-between px-4 h-14 border-b border-[var(--ayci-border)]"
        style={{ backgroundColor: "var(--ayci-sidebar)" }}
        data-testid="mobile-topbar"
      >
        <div className="flex items-center gap-2 text-white">
          <img src="/ayci-icon.png" alt="AYCI" className="w-7 h-7" style={{ filter: "brightness(0) invert(1)" }} />
          <span className="font-display font-bold text-sm">AYCI Academy</span>
        </div>
        <button
          onClick={() => setMobileOpen(true)}
          className="text-white p-2 hover:bg-white/10 rounded-md"
          aria-label="Open menu"
          data-testid="mobile-menu-button"
        >
          <Menu className="w-5 h-5" />
        </button>
      </header>

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black/50 z-40"
          onClick={closeDrawer}
          data-testid="mobile-backdrop"
        />
      )}

      <aside
        className={[
          "shrink-0 flex flex-col",
          // Desktop: sticky 256px column
          "lg:w-64 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0",
          // Mobile: fixed slide-in drawer. Use dynamic viewport units (dvh)
          // so iOS Safari's URL bar doesn't push the bottom buttons (My
          // profile / Sign out) below the visible area.
          "fixed lg:static top-0 left-0 h-[100dvh] w-64 z-50 transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        ].join(" ")}
        style={{ backgroundColor: "var(--ayci-sidebar)" }}
        data-testid="app-sidebar"
      >
        {/* Close button — mobile only */}
        <button
          onClick={closeDrawer}
          className="lg:hidden absolute top-3 right-3 p-2 text-white/70 hover:text-white"
          aria-label="Close menu"
          data-testid="mobile-close-button"
        >
          <X className="w-5 h-5" />
        </button>
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

        <nav className="flex-1 overflow-y-auto px-3 space-y-1 min-h-0">
          {NAV_GROUPS.map((node, i) => {
            if (node.type === "item") {
              if (!userCanAccess(user, node.board)) return null;
              return <NavItem key={node.to} item={node} />;
            }
            // group
            const visibleItems = node.items.filter((it) => userCanAccess(user, it.board));
            if (visibleItems.length === 0) return null;
            return (
              <NavGroup
                key={node.id}
                id={node.id}
                label={node.label}
                defaultOpen={node.defaultOpen}
                items={visibleItems}
                currentPath={location.pathname}
              />
            );
          })}
        </nav>

        <div className="px-3 pb-6 pt-4 border-t border-white/5 mx-3">
          <div className="px-3 py-2 mb-2">
            <div className="text-white text-sm font-medium truncate" data-testid="sidebar-user-name">
              {user?.name || "—"}
            </div>
            <div className="text-[var(--ayci-sidebar-muted)] text-xs capitalize">{user?.role || ""}</div>
          </div>
          <button
            onClick={() => navigate("/coach-activity")}
            data-testid="sidebar-sla-bell"
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-[var(--ayci-sidebar-muted)] hover:text-white hover:bg-white/5 transition-all"
          >
            <Bell className="w-4 h-4" />
            <span className="flex-1 text-left">SLA breaches</span>
            <SLACountBadge user={user} />
          </button>
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


function SLACountBadge({ user }) {
  const [count, setCount] = useState(null);
  useEffect(() => {
    if (!userCanAccess(user, "coach_activity")) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const { data } = await apiClient.get("/notifications/sla/count");
        if (!cancelled) setCount(data.unanswered_count);
      } catch {
        // Silently swallow — bell is a nice-to-have, not critical.
      }
    };
    tick();
    const id = setInterval(tick, 5 * 60 * 1000); // refresh every 5 min
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [user]);
  if (count === null) return null;
  if (count === 0) {
    return (
      <span
        className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300"
        data-testid="sla-bell-clear"
      >
        clear
      </span>
    );
  }
  return (
    <span
      className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-rose-500 text-white"
      data-testid="sla-bell-count"
    >
      {count}
    </span>
  );
}

