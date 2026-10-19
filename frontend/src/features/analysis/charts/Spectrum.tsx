/**
 * AR05 spectrum: the colour's median per band as a line, the plant median as a dashed line,
 * high bands labelled. Values come from the rows (Band, Colour, Plant, Gap, High); the table repeats them.
 */

import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";
import { EvidenceTable } from "./Table";

type Evidence = AssistantAnswer["evidence"];
const W = 320;
const H = 120;
const PAD = 16;

export function Spectrum({ evidence }: { evidence: Evidence }) {
  const bands = evidence.rows
    .map((r) => ({
      band: cell(r[0]),
      colour: Number(r[1]),
      plant: Number(r[2]),
      high: r[4] === "high",
    }))
    .filter((b) => Number.isFinite(b.colour) && Number.isFinite(b.plant));
  if (!bands.length)
    return <EvidenceTable evidence={evidence} caption="Colour and plant medians" />;
  const all = bands.flatMap((b) => [b.colour, b.plant]);
  const lo = Math.min(...all);
  const span = Math.max(...all) - lo || 1;
  const x = (i: number) =>
    PAD + (bands.length === 1 ? (W - 2 * PAD) / 2 : (i / (bands.length - 1)) * (W - 2 * PAD));
  const y = (v: number) => H - PAD - ((v - lo) / span) * (H - 2 * PAD);
  const path = (pick: (b: (typeof bands)[number]) => number) =>
    bands.map((b, i) => `${i ? "L" : "M"}${x(i)},${y(pick(b))}`).join(" ");
  return (
    <div className="max-w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-32 w-full max-w-md"
        role="img"
        aria-label="Median per band for the colour (solid) and the plant (dashed), high bands labelled, as in the table"
      >
        <path
          data-line="Plant"
          d={path((b) => b.plant)}
          fill="none"
          stroke="var(--muted-foreground)"
          strokeDasharray="4 3"
        />
        <path
          data-line="Colour"
          d={path((b) => b.colour)}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={2}
        />
        {bands.map((b, i) => (
          <g key={b.band}>
            <circle cx={x(i)} cy={y(b.colour)} r={2.5} fill="var(--primary)" />
            {b.high && (
              <text
                data-high={b.band}
                x={x(i)}
                y={y(b.colour) - 6}
                textAnchor="middle"
                fontSize={9}
                fill="var(--critical)"
              >
                high
              </text>
            )}
            <text
              x={x(i)}
              y={H - 3}
              textAnchor="middle"
              fontSize={9}
              fill="var(--muted-foreground)"
            >
              {b.band}
            </text>
          </g>
        ))}
      </svg>
      <EvidenceTable evidence={evidence} caption="Colour and plant medians per band" />
    </div>
  );
}
