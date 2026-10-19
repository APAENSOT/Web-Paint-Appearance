import { useEffect, useRef, useState } from "react";
import { PLANTS, PLANT_KPI, dataUpdateLevel, type Plant } from "@/lib/ct/data";

const LEVEL_VAR: Record<string, string> = {
  nominal: "var(--nominal)",
  caution: "var(--caution)",
  critical: "var(--critical)",
};

function useCountUp(target: number, decimals: number) {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / 620);
      const e = 1 - Math.pow(1 - k, 3);
      setV(Number((a + (target - a) * e).toFixed(decimals)));
      if (k < 1) raf = requestAnimationFrame(step);
      else from.current = target;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, decimals]);
  return v;
}

/** One face of the tile — identical layout on both sides so the flip reads clean. */
function Face({
  code,
  pct,
  note,
  color,
}: {
  code: string;
  pct: number;
  note: string;
  color: string;
}) {
  return (
    <div className="flex h-full flex-col justify-between">
      <p className="eyebrow">{code}</p>
      <p className="num mt-2 text-3xl font-semibold leading-none tracking-tight text-foreground">
        {pct.toFixed(1)}
        <span className="ml-0.5 text-base text-muted-foreground">%</span>
      </p>
      {/* status bar: track + fill, with faint segment ticks so the fill
          reads like a gauge rather than a loading bar */}
      <div className="relative mt-2.5 h-[4px] w-full overflow-hidden rounded-full bg-[var(--surface-2)]">
        <div
          className="h-full rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${Math.min(100, Math.max(0, pct))}%`, backgroundColor: color }}
        />
        <div className="pointer-events-none absolute inset-0 flex justify-between px-0">
          {[25, 50, 75].map((x) => (
            <span
              key={x}
              className="absolute top-0 h-full w-px bg-[var(--panel)]"
              style={{ left: `${x}%` }}
            />
          ))}
        </div>
      </div>
      <p className="num mt-2 truncate text-[10px] text-muted-foreground">{note}</p>
    </div>
  );
}

function Cell({ plant, on }: { plant: Plant; on: boolean }) {
  const k = PLANT_KPI[plant.id];
  const productColor = LEVEL_VAR[plant.level];
  const feedColor = LEVEL_VAR[dataUpdateLevel(k.dataUpdatePct)];
  /* the number animates to whichever face is showing — same count-up as before */
  const v = useCountUp(on ? k.dataUpdatePct : k.monthlyPct, 1);

  return (
    <div className="relative flex-1 [perspective:900px]">
      <div
        className="relative h-[118px] w-full transition-transform duration-500 [transform-style:preserve-3d] ease-[cubic-bezier(0.32,0.72,0.24,1)]"
        style={{ transform: on ? "rotateY(180deg)" : "rotateY(0deg)" }}
      >
        <div className="panel absolute inset-0 overflow-hidden px-4 py-3 [backface-visibility:hidden]">
          <Face
            code={plant.code}
            pct={on ? k.monthlyPct : v}
            note={k.monthlyNote}
            color={productColor}
          />
        </div>
        <div
          className="panel absolute inset-0 overflow-hidden px-4 py-3 [backface-visibility:hidden]"
          style={{ transform: "rotateY(180deg)", borderColor: feedColor }}
        >
          <Face
            code={`${plant.code} · DATA UPDATE`}
            pct={on ? v : k.dataUpdatePct}
            note={`late ${k.lateCount} · missing ${k.missingCount} · sync ${plant.lastSyncMin}m`}
            color={feedColor}
          />
        </div>
      </div>
    </div>
  );
}

/**
 * KPI strip — one tile per plant with two faces. Front: month-to-date product
 * percentage, bar coloured by the plant's map status. Back (while that plant's
 * feed switch is on): data-entry timeliness, bar coloured by lateness.
 */
export function KpiStrip({ active }: { active: string[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      {PLANTS.map((p) => (
        <Cell key={p.id} plant={p} on={active.includes(p.id)} />
      ))}
    </div>
  );
}
