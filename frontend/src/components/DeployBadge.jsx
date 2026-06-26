// Renders a green/amber/grey pill comparing the running container SHA to
// the latest commit on GitHub. Use with useDeployVersion().
export default function DeployBadge({ version }) {
  if (!version?.commit || version.commit === "unknown") return null;
  const running = version.commit;
  if (version.matches_head === true) {
    return (
      <span
        className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-mono text-[10px]"
        title={`Running v${running} - matches latest commit on main. Deploy is up to date.`}
        data-testid="deploy-badge"
      >
        ✓ deploy up to date · v{running}
      </span>
    );
  }
  if (version.matches_head === false) {
    return (
      <span
        className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-900 border border-amber-300 font-mono text-[10px]"
        title={`Running v${running} but GitHub main is at v${version.github_head}. Render didn't pick up the latest push - go to Render → Manual Deploy → "Clear build cache & deploy".`}
        data-testid="deploy-badge"
      >
        ⚠ deploy stale · running v{running}, main v{version.github_head}
      </span>
    );
  }
  return (
    <span
      className="text-[var(--ayci-ink-muted)] font-mono text-[10px]"
      title={`Running container SHA: ${version.commit_full || running}. (Couldn't reach GitHub to verify it matches main.)`}
      data-testid="deploy-badge"
    >
      · v{running}
    </span>
  );
}
