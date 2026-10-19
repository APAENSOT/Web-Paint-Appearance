/**
 * AR05 point bars: per point, car A and car B as two bars on one scale; "A out" / "B out" are words,
 * not colour alone. A value of "—" (point not measured) draws no bar. The table carries the same numbers.
 */

import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";

type Evidence = AssistantAnswer["evidence"];

export function PointBars({ evidence }: { evidence: Evidence }) {
  const { columns, rows } = evidence;
  const data = rows.map((r) => ({
    key: `${cell(r[0])} ${cell(r[1])}`,
    a: Number(r[2]),
    b: Number(r[3]),
    out: cell(r[4]),
  }));
  const max = Math.max(...data.flatMap((x) => [x.a, x.b]).filter(Number.isFinite), 0) || 1;
  const bar = (v: number, cls: string) =>
    Number.isFinite(v) ? (
      <div className={`h-2 ${cls}`} style={{ width: `${(v / max) * 100}%` }} />
    ) : null;
  if (!data.length) return null;
  return (
    <div className="max-w-full overflow-x-auto">
      <div role="img" aria-label="Car A and car B values at each point, as in the table">
        {data.map((x) => (
          <div key={x.key} data-point={x.key} className="flex items-center gap-2 py-0.5 text-xs">
            <span className="w-32 shrink-0 truncate">{x.key}</span>
            <div className="w-40 space-y-0.5">
              {bar(x.a, "bg-primary/60")}
              {bar(x.b, "bg-primary")}
            </div>
            <span className="text-muted-foreground">{x.out}</span>
          </div>
        ))}
      </div>
      <table className="mt-2 w-full border-collapse text-left text-xs">
        <caption className="sr-only">Car A and car B at each point</caption>
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
            <tr key={`${cell(r[0])}|${cell(r[1])}`} className="border-t border-border">
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
