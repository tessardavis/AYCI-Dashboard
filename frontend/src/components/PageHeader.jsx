export default function PageHeader({ eyebrow, title, description, right }) {
  return (
    <div className="flex items-start justify-between gap-6 mb-8">
      <div>
        {eyebrow && (
          <div className="text-[11px] uppercase tracking-[0.2em] text-[var(--ayci-accent)] font-semibold mb-2">
            {eyebrow}
          </div>
        )}
        <h1 className="font-display text-3xl lg:text-4xl font-extrabold tracking-tight text-[var(--ayci-ink)]">
          {title}
        </h1>
        {description && (
          <p className="text-sm text-[var(--ayci-ink-muted)] mt-2 max-w-2xl">{description}</p>
        )}
      </div>
      {right}
    </div>
  );
}
