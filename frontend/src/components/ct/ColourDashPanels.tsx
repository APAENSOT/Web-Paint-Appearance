import { ArrowDown, ArrowUp, Upload } from "lucide-react";
import {
  HOTSPOTS,
  SPEC_BAND,
  STATUS_COLOR,
  STATUS_LABEL,
  type BoxSeries,
  type ColourSummary,
} from "@/lib/ct/hotspots";

/**
 * Right column — two stacked dashboards (top summary / bottom point list).
 *
 * Concept: the top card is this colour's month score (mirrors the model card
 * on the plant dashboard: %, delta vs last month, uploads). The bottom card
 * lists every measurement point and stays in sync with the 3D stage —
 * clicking a row selects the same hotspot on the model.
 *
 * Function note: demo data from hotspots.ts. `selectedId`/`onSelect` are
 * shared with ModelStage and HotspotDetail via the route.
 */

export function SummaryCard({ summary, month }: { summary: ColourSummary; month: string }) {
  const up = summary.delta >= 0;
  return (
    <section className="panel animate-rise px-5 py-4" style={{ animationDelay: "120ms" }}>
      <div className="flex items-baseline justify-between">
        <p className="eyebrow">{summary.color}</p>
        <span className="eyebrow">{summary.metric}</span>
      </div>

      <div className="mt-2 flex items-end justify-between gap-3">
        <p className="num text-4xl font-bold leading-none">
          {summary.pct.toFixed(1)}
          <span className="ml-1 text-sm text-muted-foreground">%</span>
        </p>
        <span
          className="flex items-center gap-1 text-xs font-bold"
          style={{ color: up ? "var(--nominal)" : "var(--critical)" }}
        >
          {up ? <ArrowUp className="size-3.5" /> : <ArrowDown className="size-3.5" />}
          {Math.abs(summary.delta).toFixed(1)} pt
        </span>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">{month} · vs last month</p>

      <div
        aria-hidden
        className="mt-3 h-1.5 overflow-hidden rounded-full"
        style={{ backgroundColor: "var(--surface-2)" }}
      >
        <div
          className="h-full rounded-full transition-[width] duration-700"
          style={{ width: `${summary.pct}%`, backgroundColor: summary.accent }}
        />
      </div>

      <div className="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Upload className="size-3.5" />
        {summary.uploads} uploads this month
      </div>
    </section>
  );
}

export function HotspotListCard({
  selectedId,
  onSelect,
}: {
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <section
      className="panel animate-rise flex min-h-0 flex-1 flex-col px-5 py-4"
      style={{ animationDelay: "200ms" }}
    >
      <p className="eyebrow">Measure Points</p>
      <div
        aria-hidden
        className="mt-3 h-px"
        style={{
          background:
            "linear-gradient(90deg, var(--color-primary), var(--color-border) 45%, transparent)",
        }}
      />
      <ul className="mt-2 min-h-0 flex-1 overflow-y-auto">
        {HOTSPOTS.map((s) => {
          const on = s.id === selectedId;
          const color = STATUS_COLOR[s.status];
          return (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onSelect(s.id)}
                aria-pressed={on}
                className="flex w-full items-center gap-3 rounded-[var(--radius-sm)] px-2.5 py-2.5 text-left transition-colors hover:bg-[var(--surface-2)]"
                style={
                  on
                    ? {
                        background: `linear-gradient(90deg, color-mix(in oklab, ${color} 10%, transparent), transparent 80%)`,
                        boxShadow: `inset 2px 0 0 ${color}`,
                      }
                    : undefined
                }
              >
                <span
                  className="size-2 shrink-0 rounded-full"
                  style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}` }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-bold">{s.label}</span>
                  <span className="block text-[10px] tracking-[0.08em] text-muted-foreground">
                    {STATUS_LABEL[s.status]}
                  </span>
                </span>
                <span className="num text-sm font-bold">{s.pct.toFixed(1)}%</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * Boxplot card — this month's film-thickness distribution per body point.
 *
 * Concept: one card per panel zone (horizontal on top, vertical below).
 * Each box is a five-number summary; the shaded band is the spec window.
 * Box stroke/fill follows the point's feed status (Update / Late /
 * Missing) so engineers spot drift by colour before reading numbers.
 *
 * Function note: pure SVG, no chart lib. Scale is fixed at 72–102 % of
 * spec so both cards stay comparable. Demo data from hotspots.ts.
 */
const PLOT = { w: 400, h: 190, padL: 34, padR: 10, padT: 10, padB: 26, min: 72, max: 102 };

export function BoxplotCard({
  title,
  series,
  month,
  delay,
  selectedId,
  onSelect,
  onHover,
}: {
  title: string;
  series: BoxSeries[];
  month: string;
  delay: string;
  /** measure point currently selected on the 3D stage */
  selectedId?: string;
  onSelect?: (id: string) => void;
  onHover?: (id: string | null) => void;
}) {
  const { w, h, padL, padR, padT, padB, min, max } = PLOT;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const y = (v: number) => padT + innerH - ((v - min) / (max - min)) * innerH;
  const ticks = [80, 90, 100];
  const bandY = y(SPEC_BAND.high);
  const bandH = y(SPEC_BAND.low) - bandY;

  return (
    <section
      className="panel animate-rise flex min-h-0 flex-1 flex-col px-5 py-4"
      style={{ animationDelay: delay }}
    >
      <div className="flex items-baseline justify-between">
        <p className="eyebrow">{title}</p>
        <span className="eyebrow">{month}</span>
      </div>
      <p className="mt-0.5 text-[10px] tracking-[0.08em] text-muted-foreground">
        FILM THICKNESS · % OF SPEC
      </p>

      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="mt-2 min-h-0 w-full flex-1"
        role="img"
        aria-label={`${title} boxplot`}
      >
        {/* spec band */}
        <rect
          x={padL}
          y={bandY}
          width={innerW}
          height={bandH}
          fill="var(--color-primary)"
          opacity={0.07}
        />
        <line
          x1={padL}
          x2={w - padR}
          y1={bandY}
          y2={bandY}
          stroke="var(--color-primary)"
          strokeWidth={1}
          strokeDasharray="3 4"
          opacity={0.35}
        />
        <line
          x1={padL}
          x2={w - padR}
          y1={y(SPEC_BAND.low)}
          y2={y(SPEC_BAND.low)}
          stroke="var(--color-primary)"
          strokeWidth={1}
          strokeDasharray="3 4"
          opacity={0.35}
        />

        {/* gridlines + y labels */}
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={padL}
              x2={w - padR}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--color-border)"
              strokeWidth={1}
            />
            <text
              x={padL - 6}
              y={y(t) + 3}
              textAnchor="end"
              fontSize={9}
              fill="var(--muted-foreground)"
              className="num"
            >
              {t}
            </text>
          </g>
        ))}

        {/* boxes */}
        {series.map((s, i) => {
          const cx = padL + (innerW * (i + 0.5)) / series.length;
          const bw = Math.min(34, innerW / series.length / 2.4);
          const color = STATUS_COLOR[s.status];
          const on = s.id === selectedId;
          return (
            <g
              key={s.id}
              onClick={() => onSelect?.(s.id)}
              onPointerEnter={() => onHover?.(s.id)}
              onPointerLeave={() => onHover?.(null)}
              style={{ cursor: onSelect ? "pointer" : "default" }}
              opacity={selectedId && !on ? 0.5 : 1}
            >
              {/* hit + selection column */}
              <rect
                x={cx - innerW / series.length / 2}
                y={padT}
                width={innerW / series.length}
                height={innerH}
                fill={on ? color : "transparent"}
                fillOpacity={on ? 0.07 : 0}
              />
              {/* whisker */}
              <line x1={cx} x2={cx} y1={y(s.max)} y2={y(s.q3)} stroke={color} strokeWidth={1.5} />
              <line x1={cx} x2={cx} y1={y(s.q1)} y2={y(s.min)} stroke={color} strokeWidth={1.5} />
              <line
                x1={cx - bw / 2.4}
                x2={cx + bw / 2.4}
                y1={y(s.max)}
                y2={y(s.max)}
                stroke={color}
                strokeWidth={1.5}
              />
              <line
                x1={cx - bw / 2.4}
                x2={cx + bw / 2.4}
                y1={y(s.min)}
                y2={y(s.min)}
                stroke={color}
                strokeWidth={1.5}
              />
              {/* box */}
              <rect
                x={cx - bw / 2}
                y={y(s.q3)}
                width={bw}
                height={Math.max(2, y(s.q1) - y(s.q3))}
                fill={color}
                fillOpacity={0.16}
                stroke={color}
                strokeWidth={1.5}
                rx={2}
                className="animate-grow-y"
                style={{ transformOrigin: `${cx}px ${y(s.median)}px` }}
              />
              {/* median */}
              <line
                x1={cx - bw / 2}
                x2={cx + bw / 2}
                y1={y(s.median)}
                y2={y(s.median)}
                stroke={color}
                strokeWidth={2.5}
              />
              <text
                x={cx}
                y={h - padB + 13}
                textAnchor="middle"
                fontSize={9}
                fontWeight={on ? 800 : 700}
                fill="var(--foreground)"
              >
                {s.label}
              </text>
              <text
                x={cx}
                y={h - padB + 23}
                textAnchor="middle"
                fontSize={8}
                fill="var(--muted-foreground)"
                className="num"
              >
                {s.median.toFixed(1)}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
        <span
          aria-hidden
          className="inline-block h-2 w-4 rounded-sm"
          style={{ background: "var(--color-primary)", opacity: 0.25 }}
        />
        spec window {SPEC_BAND.low}–{SPEC_BAND.high}%
      </div>
    </section>
  );
}
