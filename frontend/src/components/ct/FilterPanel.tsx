import { useId, useState } from "react";
import { BarChart3, Check, ChevronDown, Gauge, GitCompare, LayoutGrid } from "lucide-react";
import type { SettingId } from "@/components/ct/SettingsPanel";

/**
 * Pickup-truck side profile (Ranger / Raptor are Ford pickups, not box
 * trucks) — simple silhouette: hood, cab, open bed, two wheels.
 */
function PickupIcon({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={style}
      aria-hidden="true"
    >
      {/* body: hood + cab + open bed */}
      <path d="M2 15h1l2.2-4.2A2 2 0 0 1 6.9 9.8H10V8.2A1.2 1.2 0 0 1 11.2 7h1.6A1.2 1.2 0 0 1 14 8.2v1.6h8V15h-1.4" />
      {/* cab window */}
      <path d="M10.8 9.8V8h1.4v1.8" />
      {/* bed divider */}
      <path d="M14 9.8V15" />
      {/* wheels */}
      <circle cx="6.5" cy="15" r="1.9" />
      <circle cx="17.9" cy="15" r="1.9" />
      {/* ground line between wheels */}
      <path d="M8.4 15h7.6" />
    </svg>
  );
}

/**
 * Filter panel — minimal dropdown style (Sixt reference, compact variant).
 * Each section is a collapsible dropdown with a chevron.
 *
 * Display switches the plant lens. Monthly Overview (and Monthly Detail)
 * use Paint Functional, then Month, then Vehicle Model. Color starts
 * collapsed; click to expand. Empty model and colour selections mean
 * every catalogue option is on.
 */

export type DisplayMode = "overview" | "detail" | "comparison" | "analysis";

/** Any selectable lens on the plant page — a Display mode or a Setting option. */
export type ActiveMode = DisplayMode | SettingId;

export type PaintFunction = "wavescan" | "film";

export type OverviewFilterProps = {
  paintFunction: PaintFunction;
  onPaintFunction: (value: PaintFunction) => void;
  modelOptions: string[];
  selectedModels: string[];
  onToggleModel: (code: string) => void;
  colorOptions: Array<{ color_name: string; family_code?: string | null }>;
  selectedColors: string[];
  onToggleColor: (name: string) => void;
  monthOptions: string[];
  selectedMonth: string | null;
  calendarMonth: string;
  onSelectMonth: (month: string) => void;
  onClear: () => void;
};

const DISPLAY_MODES = [
  { id: "overview", name: "Monthly Overview", icon: Gauge },
  { id: "detail", name: "Monthly Detail", icon: LayoutGrid },
  { id: "comparison", name: "Comparison", icon: GitCompare },
  { id: "analysis", name: "Analysis & Report", icon: BarChart3 },
] as const;

const PAINT_FUNCTIONS: Array<{ id: PaintFunction; name: string }> = [
  { id: "wavescan", name: "WaveScan" },
  { id: "film", name: "Film Thickness" },
];

function Section({
  label,
  open,
  onToggle,
  icon: Icon,
  children,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  icon?: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  children: React.ReactNode;
}) {
  const contentId = useId();
  return (
    <section className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={contentId}
        className="flex w-full items-center justify-between gap-2 py-3 text-left"
      >
        <span className="flex items-center gap-2">
          {Icon && <Icon className="size-3.5 shrink-0 text-muted-foreground" />}
          <span className="text-xs font-semibold text-muted-foreground">{label}</span>
        </span>
        <ChevronDown
          className="size-3.5 text-muted-foreground transition-transform duration-200"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
        />
      </button>
      {/* Animated collapse: grid-rows 0fr→1fr smoothly expands the body;
          content fades/slides in slightly after the shell starts moving. */}
      <div
        id={contentId}
        inert={!open}
        aria-hidden={!open}
        className="grid transition-[grid-template-rows] duration-200 ease-[cubic-bezier(.22,.9,.28,1)]"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      >
        <div className="min-h-0 overflow-hidden">
          <div
            className="pb-3 transition-opacity duration-150 ease-out"
            style={{
              opacity: open ? 1 : 0,
            }}
          >
            {children}
          </div>
        </div>
      </div>
    </section>
  );
}

export function FilterPanel({
  active,
  onActiveChange,
  overview,
}: {
  active: ActiveMode;
  onActiveChange: (mode: ActiveMode) => void;
  overview?: OverviewFilterProps;
}) {
  const [open, setOpen] = useState<Set<string>>(
    new Set(["Display", "Paint Functional", "Vehicle Model", "Month"]),
  );
  const showOverviewFilters = (active === "overview" || active === "detail") && overview;
  // Comparison shares Paint Functional (it picks the deck's measurement), not the other filters.
  const showPaint = showOverviewFilters || active === "comparison";

  const toggle = (set: Set<string>, id: string, apply: (s: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    apply(next);
  };

  const toggleOpen = (id: string) => toggle(open, id, setOpen);

  return (
    <aside
      className="panel w-[260px] animate-rise self-start px-4 py-2"
      style={{
        background: `linear-gradient(180deg, var(--primary-soft) 0%, var(--color-panel) 30%)`,
        boxShadow: `inset 0 2px 0 var(--color-primary), var(--shadow-panel)`,
      }}
    >
      <div className="flex items-baseline justify-between border-b border-border py-3">
        <h2 className="text-base font-semibold tracking-tight">Filter</h2>
        {showOverviewFilters && (
          <button
            type="button"
            onClick={() => overview?.onClear()}
            className="text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            Clear all filters
          </button>
        )}
      </div>

      {/* Display — view-mode switch (radio rows) */}
      <Section label="Display" open={open.has("Display")} onToggle={() => toggleOpen("Display")}>
        <ul className="space-y-0.5">
          {DISPLAY_MODES.map((m) => {
            const on = active === m.id;
            const Icon = m.icon;
            return (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => onActiveChange(m.id)}
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
                    {m.name}
                  </span>
                  {/* radio indicator */}
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
              </li>
            );
          })}
        </ul>
      </Section>

      {showPaint && overview && (
        <div className="animate-rise" style={{ animationDelay: "60ms" }}>
          <Section
            label="Paint Functional"
            open={open.has("Paint Functional")}
            onToggle={() => toggleOpen("Paint Functional")}
          >
            <ul className="space-y-0.5">
              {PAINT_FUNCTIONS.map((fn) => {
                const on = overview.paintFunction === fn.id;
                return (
                  <li key={fn.id}>
                    <button
                      type="button"
                      onClick={() => overview.onPaintFunction(fn.id)}
                      aria-pressed={on}
                      className="flex w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-1.5 py-1.5 text-left transition-all duration-200"
                      style={{
                        backgroundColor: on ? "var(--primary-soft)" : "transparent",
                        boxShadow: on ? "inset 2px 0 0 var(--color-primary)" : "none",
                      }}
                    >
                      <span
                        className="flex-1 text-xs font-medium"
                        style={{ color: on ? "var(--foreground)" : "var(--muted-foreground)" }}
                      >
                        {fn.name}
                      </span>
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
                  </li>
                );
              })}
            </ul>
          </Section>

          {(active === "overview" || active === "detail") && (
            <Section label="Month" open={open.has("Month")} onToggle={() => toggleOpen("Month")}>
              {overview.monthOptions.length === 0 ? (
                <p className="px-1 pb-2 text-[11px] text-muted-foreground">
                  This month has no measurements.
                </p>
              ) : null}
              <ul className="space-y-0.5">
                {overview.monthOptions.map((month) => {
                  const on = overview.selectedMonth === month;
                  return (
                    <li key={month}>
                      <button
                        type="button"
                        onClick={() => overview.onSelectMonth(month)}
                        aria-pressed={on}
                        className="flex w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-1.5 py-1.5 text-left transition-all duration-200"
                        style={{
                          backgroundColor: on ? "var(--primary-soft)" : "transparent",
                          boxShadow: on ? "inset 2px 0 0 var(--color-primary)" : "none",
                        }}
                      >
                        <span
                          className="flex-1 text-xs font-medium"
                          style={{ color: on ? "var(--foreground)" : "var(--muted-foreground)" }}
                        >
                          {month}
                        </span>
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
                    </li>
                  );
                })}
              </ul>
            </Section>
          )}

          {showOverviewFilters && (
            <>
              <Section
                label="Vehicle Model"
                open={open.has("Vehicle Model")}
                onToggle={() => toggleOpen("Vehicle Model")}
              >
                <ul className="space-y-0.5">
                  {overview.modelOptions.map((code) => {
                    const on =
                      overview.selectedModels.length === 0 ||
                      overview.selectedModels.includes(code);
                    return (
                      <li key={code}>
                        <button
                          type="button"
                          onClick={() => overview.onToggleModel(code)}
                          aria-pressed={on}
                          className="flex w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-1.5 py-1.5 text-left transition-all duration-200"
                          style={{
                            backgroundColor: on ? "var(--primary-soft)" : "transparent",
                            boxShadow: on ? "inset 2px 0 0 var(--color-primary)" : "none",
                          }}
                        >
                          <PickupIcon
                            className="size-4 shrink-0"
                            style={{ color: on ? "var(--primary)" : "var(--muted-foreground)" }}
                          />
                          <span
                            className="flex-1 text-xs font-medium"
                            style={{ color: on ? "var(--foreground)" : "var(--muted-foreground)" }}
                          >
                            {code}
                          </span>
                          {on && <Check className="size-3.5" style={{ color: "var(--primary)" }} />}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </Section>

              <Section label="Color" open={open.has("Color")} onToggle={() => toggleOpen("Color")}>
                <ul className="space-y-0.5">
                  {overview.colorOptions.map((color) => {
                    const on =
                      overview.selectedColors.length === 0 ||
                      overview.selectedColors.includes(color.color_name);
                    return (
                      <li key={color.color_name}>
                        <button
                          type="button"
                          onClick={() => overview.onToggleColor(color.color_name)}
                          aria-pressed={on}
                          className="group flex w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-1.5 py-1.5 text-left transition-all duration-200"
                          style={{
                            backgroundColor: on ? "var(--primary-soft)" : "transparent",
                            boxShadow: on ? "inset 2px 0 0 var(--color-primary)" : "none",
                          }}
                        >
                          <span
                            className="grid size-3.5 shrink-0 place-items-center rounded-[2px] border transition-all duration-200"
                            style={{
                              borderColor: on ? "var(--primary)" : "var(--input)",
                              backgroundColor: on ? "var(--primary)" : "transparent",
                              boxShadow: on
                                ? "0 0 8px var(--primary-soft), 0 0 2px var(--primary)"
                                : "none",
                            }}
                          >
                            {on && (
                              <Check
                                className="size-2.5"
                                style={{ color: "var(--primary-foreground)" }}
                              />
                            )}
                          </span>
                          <span
                            className="text-xs font-medium"
                            style={{ color: on ? "var(--foreground)" : "var(--muted-foreground)" }}
                          >
                            {color.color_name}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </Section>
            </>
          )}
        </div>
      )}
    </aside>
  );
}
