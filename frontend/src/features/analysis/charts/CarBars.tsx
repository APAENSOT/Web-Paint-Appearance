/**
 * AR05 car bars: one horizontal bar per car (points out against points measured), worst first.
 * The table below carries the same numbers.
 */

import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";

type Evidence = AssistantAnswer["evidence"];

export function CarBars({ evidence }: { evidence: Evidence }) {
  const { columns, rows } = evidence;
  if (!rows.length) return null;
  const peak = Math.max(1, ...rows.map((r) => Number(r[2]) || 0));
  return (
    <div className="max-w-full overflow-x-auto">
      <div role="img" aria-label="Points out per car, as in the table">
        {rows.map((r, i) => {
          const out = Number(r[1]) || 0;
          const all = Number(r[2]) || 0;
          return (
            <div key={i} data-car={cell(r[0])} className="flex items-center gap-2 py-0.5 text-xs">
              <span className="w-20 shrink-0 truncate">{cell(r[0])}</span>
              <div className="relative h-2 w-40 bg-muted">
                <div
                  className="absolute inset-y-0 left-0 bg-primary/30"
                  style={{ width: `${(all / peak) * 100}%` }}
                />
                <div
                  className="absolute inset-y-0 left-0 bg-primary"
                  style={{ width: `${(out / peak) * 100}%` }}
                />
              </div>
              <span className="text-muted-foreground">
                {out} of {all}
              </span>
            </div>
          );
        })}
      </div>
      <table className="mt-2 w-full border-collapse text-left text-xs">
        <caption className="sr-only">Points out per car</caption>
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
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border">
              {r.map((c, j) => (
                <td key={columns[j]} className="px-1 py-1">
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
