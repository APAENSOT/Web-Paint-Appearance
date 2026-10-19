/**
 * AR05 scatter: one dot per paired car and the fitted line (slope and intercept from the card).
 * Without points the table alone shows; the table always carries the same numbers.
 */

import type { AssistantAnswer } from "../report-types";
import { EvidenceTable } from "./Table";

type Evidence = AssistantAnswer["evidence"];
const W = 320;
const H = 140;
const PAD = 18;

export function Scatter({ evidence }: { evidence: Evidence }) {
  const { points, card, columns } = evidence;
  const dots = points.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  const table = <EvidenceTable evidence={evidence} caption="Paired cars" />;
  if (!dots.length) return table;
  const xs = dots.map((p) => p.x);
  const ys = dots.map((p) => p.y);
  const [x0, y0] = [Math.min(...xs), Math.min(...ys)];
  const [sx, sy] = [Math.max(...xs) - x0 || 1, Math.max(...ys) - y0 || 1];
  const px = (v: number) => PAD + ((v - x0) / sx) * (W - 2 * PAD);
  const py = (v: number) => H - PAD - ((v - y0) / sy) * (H - 2 * PAD);
  const num = (label: string) =>
    Number.parseFloat(card.find((c) => c.label === label)?.value ?? "");
  const [slope, icpt] = [num("Slope"), num("Intercept")];
  const fit = Number.isFinite(slope) && Number.isFinite(icpt);
  return (
    <div className="max-w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-36 w-full max-w-md"
        role="img"
        aria-label={`${columns[2]} against ${columns[1]} for each paired car, with the fitted line, as in the table`}
      >
        {fit && (
          <line
            data-line="Fit"
            x1={px(x0)}
            y1={py(icpt + slope * x0)}
            x2={px(x0 + sx)}
            y2={py(icpt + slope * (x0 + sx))}
            stroke="var(--muted-foreground)"
            strokeDasharray="4 3"
          />
        )}
        {dots.map((p) => (
          <circle
            key={`${p.label}-${p.x}-${p.y}`}
            data-dot={p.label ?? ""}
            cx={px(p.x)}
            cy={py(p.y)}
            r={3}
            fill="var(--primary)"
          />
        ))}
      </svg>
      <p className="text-xs text-muted-foreground">
        {columns[1]} across, {columns[2]} up
      </p>
      {table}
    </div>
  );
}
