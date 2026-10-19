export function DataChildrenNav({
  canManage,
  view,
  onSelect,
}: {
  canManage: boolean;
  view: "upload" | "history";
  onSelect: (view: "upload" | "history") => void;
}) {
  return (
    <nav aria-label="Data views" className="ml-3 mt-2 space-y-1 border-l border-border pl-3 pb-2">
      {(canManage ? (["upload", "history"] as const) : (["history"] as const)).map((item) => (
        <button
          key={item}
          type="button"
          aria-pressed={view === item}
          onClick={() => onSelect(item)}
          className="block w-full rounded-sm px-2 py-2 text-left text-xs text-muted-foreground aria-pressed:bg-[var(--primary-soft)] aria-pressed:font-semibold aria-pressed:text-foreground"
        >
          {item === "upload" ? "Upload Data" : "Measurement History"}
        </button>
      ))}
    </nav>
  );
}
