import { NavLink, Link } from "react-router-dom";
import { apiClient } from "@/lib/api";

/**
 * NavLink (or plain Link) that prefetches the destination page's primary
 * API endpoint on hover. Endpoints are issued via the shared apiClient so
 * they hit the backend stale-while-revalidate cache and become instant by
 * the time the user clicks.
 *
 * Debounced 200 ms - quick mouse fly-overs don't fire requests.
 *
 * Map of route → endpoint(s) is intentionally tiny: we only prefetch the
 * "page-load expensive" endpoints, not every endpoint a page may call.
 */
const PREFETCH_MAP = {
  "/launches": ["/launches"],
  "/interviews": ["/interviews/upcoming?academy_days=7&private_days=14"],
  "/at-risk": ["/students/at-risk"],
  "/cohort": ["/cohorts/labels"],
  "/coach-activity": ["/coach-activity/summary"],
  "/": ["/scorecard"],
};

const triggered = new Set(); // session-level dedupe

function prefetch(to) {
  const paths = PREFETCH_MAP[to];
  if (!paths) return;
  for (const p of paths) {
    const key = `${to}::${p}`;
    if (triggered.has(key)) return; // already warmed this session
    triggered.add(key);
    apiClient
      .get(p, { timeout: 30000 })
      .catch(() => {
        // Best-effort - swallow errors; user will see the real one on click
        triggered.delete(key);
      });
  }
}

export function PrefetchNavLink({ to, children, prefetchDelay = 200, ...rest }) {
  let timer;
  const onEnter = () => {
    clearTimeout(timer);
    timer = setTimeout(() => prefetch(to), prefetchDelay);
  };
  const onLeave = () => clearTimeout(timer);
  return (
    <NavLink to={to} onMouseEnter={onEnter} onMouseLeave={onLeave} onFocus={onEnter} {...rest}>
      {children}
    </NavLink>
  );
}

export function PrefetchLink({ to, children, prefetchDelay = 200, ...rest }) {
  let timer;
  const onEnter = () => {
    clearTimeout(timer);
    timer = setTimeout(() => prefetch(to), prefetchDelay);
  };
  const onLeave = () => clearTimeout(timer);
  return (
    <Link to={to} onMouseEnter={onEnter} onMouseLeave={onLeave} onFocus={onEnter} {...rest}>
      {children}
    </Link>
  );
}
