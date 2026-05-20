import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api";

export function useDeployVersion() {
  const [version, setVersion] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let ver = null;
      try {
        const { data } = await apiClient.get("/version");
        ver = data || null;
      } catch {
        return;
      }
      if (ver?.repo && ver?.branch && ver.commit_full) {
        try {
          const ghRes = await fetch(
            `https://api.github.com/repos/${ver.repo}/commits/${ver.branch}`,
            { headers: { Accept: "application/vnd.github+json" } },
          );
          if (ghRes.ok) {
            const ghJson = await ghRes.json();
            const head = ghJson?.sha || "";
            ver.github_head = head ? head.slice(0, 7) : null;
            ver.matches_head = head ? head === ver.commit_full : null;
          }
        } catch { /* leave matches_head unset */ }
      }
      if (!cancelled) setVersion(ver);
    })();
    return () => { cancelled = true; };
  }, []);

  return version;
}
