/**
 * Brand-styled page hero used on Launch / Cohort / Students-at-risk dashboards.
 *
 * Single component, three colour stories:
 *   - Launch     — navy → indigo, cyan accent
 *   - Cohort     — magenta → purple, pink accent
 *   - At Risk    — amber → orange, rose accent
 *
 * The giant rotated AYCI icon watermark is rendered top-right at ~7 % opacity.
 */
export default function HeroBanner({
  gradient,
  accentDot = "rgba(255,255,255,0.18)",
  eyebrow,
  eyebrowColor = "#FFFFFF",
  title,
  subtitle,
  actions,
  testid = "page-hero",
}) {
  return (
    <div
      className="relative overflow-hidden rounded-2xl px-4 py-4 sm:px-8 sm:py-10 shadow-sm border border-[var(--ayci-border)]"
      style={{ background: gradient }}
      data-testid={testid}
    >
      <img
        src="/ayci-icon.png"
        alt=""
        aria-hidden="true"
        className="absolute -top-10 -right-10 w-[180px] h-[180px] sm:w-[420px] sm:h-[420px] pointer-events-none select-none"
        style={{
          filter: "brightness(0) invert(1)",
          opacity: 0.07,
          transform: "rotate(18deg)",
        }}
      />
      <div
        className="absolute -bottom-24 -left-24 w-72 h-72 rounded-full pointer-events-none"
        style={{ background: `radial-gradient(closest-side, ${accentDot}, transparent)` }}
      />
      <div className="relative flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 sm:gap-4">
        <div className="min-w-0 flex-1">
          {eyebrow && (
            <div
              className="text-[10px] sm:text-[11px] font-display font-semibold tracking-[0.2em] sm:tracking-[0.25em] uppercase"
              style={{ color: eyebrowColor }}
              data-testid={`${testid}-eyebrow`}
            >
              {eyebrow}
            </div>
          )}
          <h1
            className="text-lg sm:text-3xl lg:text-4xl font-display font-bold text-white mt-1 leading-tight"
            data-testid={`${testid}-title`}
          >
            {title}
          </h1>
          {subtitle && (
            <p className="hidden sm:block text-white/75 text-xs sm:text-sm mt-1 max-w-2xl">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
      </div>
    </div>
  );
}

// Brand presets — keep in one place so every dashboard stays consistent.
export const HERO_PRESETS = {
  launch: {
    gradient: "linear-gradient(135deg, #182E87 0%, #4457B6 60%, #5b6dc7 100%)",
    accentDot: "rgba(1,217,220,0.25)",
    eyebrowColor: "#01D9DC",
  },
  cohort: {
    gradient: "linear-gradient(135deg, #7B1FA2 0%, #A6258F 55%, #C2185B 100%)",
    accentDot: "rgba(255,193,233,0.30)",
    eyebrowColor: "#FFC1E9",
  },
  at_risk: {
    gradient: "linear-gradient(135deg, #B45309 0%, #D97706 55%, #F59E0B 100%)",
    accentDot: "rgba(254,215,170,0.35)",
    eyebrowColor: "#FED7AA",
  },
  spotlight: {
    gradient: "linear-gradient(135deg, #0F766E 0%, #14B8A6 55%, #06B6D4 100%)",
    accentDot: "rgba(167,243,208,0.30)",
    eyebrowColor: "#A7F3D0",
  },
  leaderboard: {
    gradient: "linear-gradient(135deg, #7C2D12 0%, #C2410C 55%, #F59E0B 100%)",
    accentDot: "rgba(254,215,170,0.30)",
    eyebrowColor: "#FED7AA",
  },
};
