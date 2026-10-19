import { STATUS_COLOR, STATUS_LABEL, type Hotspot } from "@/lib/ct/hotspots";
import { useCountUp } from "@/lib/ct/use-count-up";

/**
 * Left panel — detail of the selected 3D hotspot.
 *
 * Concept: mirrors the "Flatcar Details" card of the reference — the point's
 * identity up top, then its wave scan / film thickness readings and this
 * month's score for that point.
 *
 * Function note: values are demo data from HOTSPOTS. Every figure count-ups
 * from the previously selected point (useCountUp) so switching markers reads
 * like an instrument settling rather than a hard cut.
 */

function Row({ label, value, unit }: { label: string; value: number; unit?: string }) {
  const v = useCountUp(value);
  return (
    <div className="flex items-baseline justify-between border-b border-border py-2.5 last:border-0">
      <span className="eyebrow">{label}</span>
      <span className="num text-lg font-bold">
        {v >= 0 && value < 0 ? "" : ""}
        {v.toFixed(1)}
        {unit && <span className="ml-0.5 text-xs text-muted-foreground">{unit}</span>}
      </span>
    </div>
  );
}

export function HotspotDetail({ spot }: { spot: Hotspot }) {
  const statusColor = STATUS_COLOR[spot.status];
  const pct = useCountUp(spot.pct);

  return (
    <section
      className="panel animate-rise flex flex-col px-5 py-4"
      style={{ animationDelay: "60ms" }}
    >
      <p className="eyebrow">Measure Point</p>
      <h2 key={spot.id} className="animate-swap mt-1 text-2xl font-bold tracking-tight">
        {spot.label}
      </h2>

      <div
        className="mt-3 flex items-center gap-2 rounded-[var(--radius-sm)] border border-border px-3 py-2 transition-colors"
        style={{
          transitionDuration: "var(--dur-base)",
          background: `linear-gradient(135deg, color-mix(in oklab, ${statusColor} 10%, transparent), transparent 75%)`,
        }}
      >
        <span
          className="size-2 shrink-0 rounded-full"
          style={{ backgroundColor: statusColor, boxShadow: `0 0 8px ${statusColor}` }}
        />
        <span className="text-xs font-bold tracking-[0.08em]" style={{ color: statusColor }}>
          {STATUS_LABEL[spot.status]}
        </span>
        <span className="num ml-auto text-sm font-bold" style={{ color: statusColor }}>
          {pct.toFixed(1)}%
        </span>
      </div>

      <div className="mt-2">
        <Row label="Wave Scan" value={spot.waveScan} unit="%" />
        <Row label="Film Thickness" value={spot.filmThickness} unit="%" />
        <Row label="vs Last Month" value={spot.delta} unit="pt" />
      </div>

      <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground">
        Readings for this body point this month. Pick another marker on the model, a box in the zone
        charts, or use ← / → to step through points.
      </p>
    </section>
  );
}
