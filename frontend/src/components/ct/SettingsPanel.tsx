import type { ReactNode } from "react";
import { Car, Database, Ruler } from "lucide-react";

/**
 * Setting panel — same visual template as the Filter panel (gradient shell,
 * primary top hairline, eyebrow header) but without a reset action.
 *
 * Options are radio-style rows: Data, Standard, Model Detail. They pick the
 * configuration lens for the current plant view and share ONE exclusive
 * selection with the Filter panel's Display modes: only one function can be
 * active at a time, so picking a Setting clears the active Display mode and
 * vice versa. Selection state lives in the route (lifted), not here.
 */

const SETTINGS = [
  { id: "data", name: "Data", icon: Database },
  { id: "standard", name: "Standard", icon: Ruler },
  { id: "model", name: "Model Detail", icon: Car },
] as const;

export type SettingId = (typeof SETTINGS)[number]["id"];

export function SettingsPanel({
  active,
  onSelect,
  dataChildren,
  standardChildren,
  modelChildren,
}: {
  dataChildren?: ReactNode;
  standardChildren?: ReactNode;
  modelChildren?: ReactNode;
  active: SettingId | null;
  onSelect: (id: SettingId) => void;
}) {
  return (
    <aside
      className="panel w-[260px] animate-rise px-4 py-2"
      style={{
        background: `linear-gradient(180deg, var(--primary-soft) 0%, var(--color-panel) 30%)`,
        boxShadow: `inset 0 2px 0 var(--color-primary), var(--shadow-panel)`,
        animationDelay: "60ms",
      }}
    >
      <div className="border-b border-border py-3">
        <h2 className="text-base font-semibold tracking-tight">Setting</h2>
      </div>

      <ul className="space-y-0.5 py-3">
        {SETTINGS.map((s) => {
          const on = active === s.id;
          const Icon = s.icon;
          return (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onSelect(s.id)}
                aria-pressed={on}
                className="flex w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-1.5 py-1.5 text-left transition-all duration-200"
                style={{
                  backgroundColor: on ? "var(--primary-soft)" : "transparent",
                  boxShadow: on ? "inset 2px 0 0 var(--color-primary)" : "none",
                }}
              >
                <Icon
                  className="size-4 shrink-0"
                  style={{ color: on ? "var(--primary)" : "var(--muted-foreground)" }}
                />
                <span
                  className="flex-1 text-xs font-medium"
                  style={{ color: on ? "var(--foreground)" : "var(--muted-foreground)" }}
                >
                  {s.name}
                </span>
                {/* radio indicator — same as Display rows */}
                <span
                  className="grid size-3.5 shrink-0 place-items-center rounded-full border transition-all duration-200"
                  style={{
                    borderColor: on ? "var(--primary)" : "var(--input)",
                    boxShadow: on ? "0 0 8px var(--primary-soft)" : "none",
                  }}
                >
                  {on && (
                    <span
                      className="size-1.5 rounded-full"
                      style={{ backgroundColor: "var(--primary)" }}
                    />
                  )}
                </span>
              </button>
              {s.id === "data" && on && dataChildren}
              {s.id === "standard" && on && standardChildren}
              {s.id === "model" && on && modelChildren}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
