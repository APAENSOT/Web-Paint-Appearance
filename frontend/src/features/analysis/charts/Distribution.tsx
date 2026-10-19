/**
 * AR05 distribution: a histogram of the box's readings with dashed limit lines and the mean marked.
 * Positions come from the bin labels ("a–b") and the Mean card row; the table carries the same counts.
 */

import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";
import { EvidenceTable } from "./Table";

type Evidence = AssistantAnswer["evidence"];
const W = 320;
const H = 90;

export function Distribution({ evidence }: { evidence: Evidence }) {
  const { columns, rows, limits, card } = evidence;
  const bins = rows
    .map((r) => {
      const [a, b] = cell(r[0]).split("–").map(Number);
      return { label: cell(r[0]), a, b, n: Number(r[1]) };
    })
    .filter((x) => Number.isFinite(x.a) && Number.isFinite(x.b) && Number.isFinite(x.n));
  if (!bins.length) return <EvidenceTable evidence={evidence} caption="Readings per bin" />;
  const lo = bins[0].a;
  const span = bins[bins.length - 1].b - lo || 1;
  const x = (v: number) => ((v - lo) / span) * W;
  const top = Math.max(...bins.map((b) => b.n), 1);
  const mean = Number.parseFloat(card.find((c) => c.label === "Mean")?.value ?? "");
  const line = (v: number | null | undefined, name: string, dash: boolean) =>
    v != null && v >= lo && v <= lo + span ? (
      <line
        key={name}
        data-line={name}
        x1={x(v)}
        x2={x(v)}
        y1={0}
        y2={H}
        stroke={dash ? "var(--critical)" : "var(--foreground)"}
        strokeWidth={dash ? 1 : 2}
        strokeDasharray={dash ? "4 3" : undefined}
      />
    ) : null;
  return (
    <div className="max-w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-24 w-full max-w-md"
        role="img"
        aria-label="Histogram of the readings with the box limits (dashed) and the mean, as in the table"
      >
        {bins.map((b) => (
          <rect
            key={b.label}
            data-bin={b.label}
            x={x(b.a) + 1}
            width={Math.max(x(b.b) - x(b.a) - 2, 1)}
            y={H - (b.n / top) * H}
            height={(b.n / top) * H}
            fill="var(--primary)"
          />
        ))}
        {line(limits?.lo, "Lower limit", true)}
        {line(limits?.hi, "Upper limit", true)}
        {line(mean, "Mean", false)}
      </svg>
      <p className="text-xs text-muted-foreground">
        {card.map((c) => `${c.label} ${c.value}`).join(" · ")}
        {limits?.lo != null && ` · Lower limit ${limits.lo}`}
        {limits?.hi != null && ` · Upper limit ${limits.hi}`}
      </p>
      <table className="mt-2 w-full border-collapse text-left text-xs">
        <caption className="sr-only">Readings per value range</caption>
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
            <tr key={cell(r[0])} className="border-t border-border">
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
