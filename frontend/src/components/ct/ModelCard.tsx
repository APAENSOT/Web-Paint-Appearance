import { ArrowDownRight, ArrowUpRight, Upload } from "lucide-react";
import rangerIgnite from "@/assets/models/ranger.png";

/**
 * ModelCard — one paint-colour record for a vehicle model, laid out like the
 * Sixt "vehicle card" reference: title top-left, two pills under it, the
 * vehicle floating over a soft radial light pool, then the headline figure.
 *
 * Mapping vs the rental reference:
 *   price/day      → this month's paint score (%) for that colour
 *   total price    → month-over-month delta (green up / red down) vs last month
 *   extra info row → upload count = how many times data was fed this month
 *
 * Decoration: each card carries an `accent` (the paint colour). It drives the
 * top hairline, the faint vertical tint of the card body, the light pool
 * under the vehicle, the hover glow shadow, and the colour swatch in the
 * pill — so every colour record reads as its own "paint" at a glance.
 *
 * Function note: the whole card is a button — it will route into the
 * per-colour deep dashboard. Wire `onSelect` to navigate when that route lands.
 */

export interface ModelCardData {
  id: string;
  /** e.g. "Ford P703 Ranger" */
  title: string;
  /** measurement pill, e.g. "Wave Scan" */
  metric: string;
  /** colour pill, e.g. "Ignite Orange" */
  color: string;
  /** paint-colour accent, hex — drives card tint, light pool, swatch, glow */
  accent: string;
  /** this month's score, % */
  pct: number;
  /** delta vs previous month, percentage points (sign matters) */
  delta: number;
  /** number of data uploads this month */
  uploads: number;
  image: string;
}

export const RANGER_IGNITE_IMG = rangerIgnite;

/** mix a hex accent against transparency (oklab keeps hue honest) */
const tint = (hex: string, pct: number) => `color-mix(in oklab, ${hex} ${pct}%, transparent)`;

function Pill({ children, swatch }: { children: React.ReactNode; swatch?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-[11px] font-medium leading-none text-muted-foreground">
      {swatch && (
        <span
          aria-hidden
          className="size-2 rounded-full"
          style={{ backgroundColor: swatch, boxShadow: `0 0 6px ${tint(swatch, 70)}` }}
        />
      )}
      {children}
    </span>
  );
}

export function ModelCard({
  data,
  month,
  prevMonth,
  onSelect,
}: {
  data: ModelCardData;
  month: string;
  prevMonth: string;
  onSelect?: (id: string) => void;
}) {
  const up = data.delta >= 0;
  const Arrow = up ? ArrowUpRight : ArrowDownRight;
  const deltaColor = up ? "var(--nominal)" : "var(--critical)";

  return (
    <button
      type="button"
      onClick={() => onSelect?.(data.id)}
      className="panel group flex h-full w-full cursor-pointer flex-col overflow-hidden p-4 pb-4 text-left transition-[transform,box-shadow] duration-300 ease-[cubic-bezier(.22,.9,.28,1)] hover:-translate-y-1"
      style={{
        background: `linear-gradient(180deg, ${tint(data.accent, 10)} 0%, var(--color-panel) 55%)`,
        boxShadow: `inset 0 2px 0 ${data.accent}, var(--shadow-panel)`,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = `inset 0 2px 0 ${data.accent}, 0 16px 36px -14px ${tint(data.accent, 55)}, var(--shadow-panel)`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = `inset 0 2px 0 ${data.accent}, var(--shadow-panel)`;
      }}
    >
      {/* title + pills */}
      <h3 className="text-base font-bold leading-tight tracking-tight">{data.title}</h3>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Pill>{data.metric}</Pill>
        <Pill swatch={data.accent}>{data.color}</Pill>
      </div>

      {/* vehicle over a light pool tinted by the paint colour — bleeds to
          the card's side edges so the truck fills the frame; the image is
          height-capped + centred so it never collides with the stats row */}
      <div className="relative -mx-4 mt-3 flex h-56 items-center justify-center pb-4">
        <div
          aria-hidden
          className="absolute inset-x-8 bottom-14 h-28 rounded-[50%] blur-xl transition-all duration-300 group-hover:opacity-100 group-hover:blur-lg"
          style={{
            background: `radial-gradient(50% 50% at 50% 50%, ${tint(data.accent, 26)}, transparent 70%)`,
            opacity: 0.85,
          }}
        />
        <img
          src={data.image}
          alt={`${data.title} in ${data.color}`}
          loading="lazy"
          className="relative z-10 max-h-full w-auto object-contain px-1 transition-transform duration-300 group-hover:scale-[1.05] group-hover:-rotate-1"
        />
      </div>

      {/* headline figure — % / month */}
      <div className="mt-1 flex items-end justify-between border-t border-border pt-3">
        <div>
          <p className="num text-3xl font-bold leading-none">
            {data.pct.toFixed(1)}
            <span className="ml-0.5 text-sm text-muted-foreground">%</span>
            <span className="ml-1 text-sm font-medium text-muted-foreground">/ {month}</span>
          </p>
          <p
            className="mt-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-bold"
            style={{
              color: deltaColor,
              backgroundColor: `color-mix(in oklab, ${deltaColor} 12%, transparent)`,
            }}
          >
            <Arrow className="size-3.5" />
            {Math.abs(data.delta).toFixed(1)}%
            <span className="font-medium text-muted-foreground">from {prevMonth}</span>
          </p>
        </div>

        {/* upload count for this colour this month */}
        <div
          className="flex items-center gap-1.5 rounded-full px-2.5 py-1"
          style={{ backgroundColor: tint(data.accent, 12), color: "var(--muted-foreground)" }}
        >
          <Upload className="size-3.5" />
          <span className="num text-sm font-bold text-foreground">{data.uploads}</span>
        </div>
      </div>
    </button>
  );
}
