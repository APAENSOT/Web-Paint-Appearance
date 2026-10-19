/**
 * AR05 boxplot pair: two boxes (whiskers, quartile box, median, mean dot) on one scale, n under each,
 * dashed limit lines with their values. Plain SVG; the table below carries the same numbers.
 */

import { evidenceCell as cell, fmt } from "../report-slides";
import type { AssistantAnswer } from "../report-types";
import { EvidenceTable } from "./Table";

type Evidence = AssistantAnswer["evidence"];

const W = 320;
const H = 150;
const PAD = 8;
const MID = 18;

/** `width` widens the drawing for BoxplotGroup, which shows one box per family. */
export function BoxplotPair({ evidence, width = W }: { evidence: Evidence; width?: number }) {
  const { groups, limits, columns, rows } = evidence;
  const full = groups.filter((g) => g.q1 != null && g.median != null && g.q3 != null);
  if (full.length < 2)
    return <EvidenceTable evidence={evidence} caption="Quartiles and mean of each group" />;
  const lines = [
    limits?.lo != null ? { v: limits.lo, word: "Lower limit" } : null,
    limits?.hi != null ? { v: limits.hi, word: "Upper limit" } : null,
  ].filter((l) => l !== null);
  const all = [...full.flatMap((g) => [g.low ?? g.q1!, g.high ?? g.q3!]), ...lines.map((l) => l.v)];
  const lo = Math.min(...all);
  const span = Math.max(...all) - lo || 1;
  const y = (v: number) => H - MID - PAD - ((v - lo) / span) * (H - MID - 2 * PAD);
  const slot = (width - 2 * PAD) / full.length;
  return (
    <div className="max-w-full overflow-x-auto">
      <div className="guide-group-values">
        {full.map((g) => (
          <div key={g.label}>
            <p className="font-semibold break-words">{g.label}</p>
            <p className="mt-2 text-xs text-muted-foreground">Typical reading (median)</p>
            <p className="mt-1 text-2xl font-semibold num">{fmt(g.median!)}</p>
            <p className="text-xs text-muted-foreground">{g.n} readings</p>
          </div>
        ))}
      </div>
      <p className="my-4 text-xs text-muted-foreground">
        Values use the units in the finding above. Compare typical readings here and the spread in
        the plot below.
      </p>
      <svg
        viewBox={`0 0 ${width} ${H}`}
        className="h-56 w-full"
        style={{ maxWidth: width * 1.8 }}
        role="img"
        aria-label="Box plots side by side on one scale, as in the table"
      >
        {lines.map((l) => (
          <g key={l.word}>
            <line
              x1={PAD}
              x2={width - PAD}
              y1={y(l.v)}
              y2={y(l.v)}
              stroke="var(--critical)"
              strokeDasharray="4 4"
            />
            <text x={PAD} y={y(l.v) - 2} fontSize={10} fill="var(--muted-foreground)">
              {`${l.word} ${l.v}`}
            </text>
          </g>
        ))}
        {full.map((g, i) => {
          const cx = PAD + slot * (i + 0.5);
          const bw = Math.min(48, slot / 2);
          return (
            <g key={g.label} data-box={g.label}>
              <line
                x1={cx}
                x2={cx}
                y1={y(g.low ?? g.q1!)}
                y2={y(g.high ?? g.q3!)}
                stroke="var(--foreground)"
              />
              <rect
                x={cx - bw / 2}
                y={y(g.q3!)}
                width={bw}
                height={Math.max(1, y(g.q1!) - y(g.q3!))}
                fill="var(--primary)"
                fillOpacity={0.25}
                stroke="var(--primary)"
              />
              <line
                x1={cx - bw / 2}
                x2={cx + bw / 2}
                y1={y(g.median!)}
                y2={y(g.median!)}
                stroke="var(--foreground)"
                strokeWidth={2}
              />
              {g.mean != null && <circle cx={cx} cy={y(g.mean)} r={2.5} fill="var(--foreground)" />}
              <text
                x={cx}
                y={H - 4}
                fontSize={10}
                textAnchor="middle"
                fill="var(--muted-foreground)"
              >
                {`${g.label} · n ${g.n}`}
              </text>
            </g>
          );
        })}
      </svg>
      <table className="mt-2 w-full border-collapse text-left text-xs">
        <caption className="sr-only">Quartiles and mean of each group</caption>
        <thead className="text-muted-foreground">
          <tr>
            {columns.map((h) => (
              <th key={h} scope="col" className="px-1 py-1 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r[0])} className="border-t border-border">
              {r.map((c, i) => (
                <td key={columns[i]} className="px-1 py-1">
                  {cell(c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
