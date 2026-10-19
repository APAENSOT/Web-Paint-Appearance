export type StudioMode = "colours" | "points";
export type ModelDetailView = "model" | "point-check" | "colours" | "inspection";

export function ModelStudioNav({
  mode,
  disabled,
  canEditPoints,
  onSelect,
}: {
  mode: ModelDetailView;
  disabled: boolean;
  canEditPoints: boolean;
  onSelect: (mode: ModelDetailView) => void;
}) {
  return (
    <nav
      aria-label="Model Detail views"
      className="ml-3 mt-2 space-y-1 border-l border-border pl-3 pb-2"
    >
      {(
        [
          ["model", "Model"],
          ...(canEditPoints ? ([["point-check", "Point Check"]] as const) : []),
          ["colours", "Colours"],
          ["inspection", "Inspection points"],
        ] as const
      ).map(([id, label]) => (
        <button
          type="button"
          key={id}
          data-testid={`model-detail-nav-${id}`}
          disabled={disabled}
          aria-pressed={mode === id}
          onClick={() => onSelect(id)}
          className="block min-h-11 w-full rounded-sm px-2 py-2 text-left text-xs text-muted-foreground transition-colors aria-pressed:bg-[var(--primary-soft)] aria-pressed:font-semibold aria-pressed:text-foreground disabled:opacity-50"
        >
          {label}
        </button>
      ))}
    </nav>
  );
}
