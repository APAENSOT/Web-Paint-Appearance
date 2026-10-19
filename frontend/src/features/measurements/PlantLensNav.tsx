import type { CSSProperties, ComponentType } from "react";
import { BarChart3, Car, Database, Gauge, GitCompare, LayoutGrid, Ruler } from "lucide-react";
import { DISPLAY_LENSES, panelChrome, SETTING_LENSES, type PlantLens } from "./plant-lens";

const DISPLAY_ICONS = {
  overview: Gauge,
  detail: LayoutGrid,
  comparison: GitCompare,
  analysis: BarChart3,
} as const;

const SETTING_ICONS = {
  data: Database,
  standard: Ruler,
  model: Car,
} as const;

function LensRow({
  name,
  pressed,
  onSelect,
  icon: Icon,
}: {
  name: string;
  pressed: boolean;
  onSelect: () => void;
  icon: ComponentType<{ className?: string; style?: CSSProperties }>;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={pressed}
      className="flex w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-1.5 py-1.5 text-left transition-all duration-200"
      style={{
        backgroundColor: pressed ? "var(--primary-soft)" : "transparent",
        boxShadow: pressed ? "inset 2px 0 0 var(--color-primary)" : "none",
      }}
    >
      <Icon
        className="size-4 shrink-0"
        style={{ color: pressed ? "var(--primary)" : "var(--muted-foreground)" }}
      />
      <span
        className="flex-1 text-xs font-medium"
        style={{ color: pressed ? "var(--foreground)" : "var(--muted-foreground)" }}
      >
        {name}
      </span>
      <span
        className="grid size-3.5 shrink-0 place-items-center rounded-full border transition-all duration-200"
        style={{
          borderColor: pressed ? "var(--primary)" : "var(--input)",
          boxShadow: pressed ? "0 0 8px var(--primary-soft)" : "none",
        }}
      >
        {pressed && (
          <span className="size-1.5 rounded-full" style={{ backgroundColor: "var(--primary)" }} />
        )}
      </span>
    </button>
  );
}

export function PlantLensNav({
  lens,
  onLensChange,
}: {
  lens: PlantLens;
  onLensChange: (next: PlantLens) => void;
}) {
  return (
    <div className="flex w-full flex-col gap-3 lg:w-[260px] lg:shrink-0">
      <aside className="panel px-4 py-2" style={panelChrome}>
        <div className="border-b border-border py-3">
          <h2 className="text-base font-semibold tracking-tight">Filter</h2>
        </div>
        <nav aria-label="Plant display" className="py-3">
          <p className="eyebrow mb-2">Display</p>
          <ul className="space-y-0.5">
            {DISPLAY_LENSES.map((item) => (
              <li key={item.id}>
                <LensRow
                  name={item.name}
                  pressed={lens === item.id}
                  onSelect={() => onLensChange(item.id)}
                  icon={DISPLAY_ICONS[item.id]}
                />
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <aside className="panel px-4 py-2" style={panelChrome}>
        <div className="border-b border-border py-3">
          <h2 className="text-base font-semibold tracking-tight">Setting</h2>
        </div>
        <nav aria-label="Plant setting" className="py-3">
          <ul className="space-y-0.5">
            {SETTING_LENSES.map((item) => (
              <li key={item.id}>
                <LensRow
                  name={item.name}
                  pressed={lens === item.id}
                  onSelect={() => onLensChange(item.id)}
                  icon={SETTING_ICONS[item.id]}
                />
              </li>
            ))}
          </ul>
        </nav>
      </aside>
    </div>
  );
}
