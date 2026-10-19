/**
 * AR05 breakdown: one small panel per dimension (Point, Side, Week, Car), horizontal bars of the
 * top 5 places by Out count. The table below carries every row, so no colour or bar stands alone.
 */

import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";

type Evidence = AssistantAnswer["evidence"];
const TOP = 5;

export function Breakdown({ evidence }: { evidence: Evidence }) {
  const { columns, rows } = evidence;
  if (!rows.length) return null;
  const by = new Map<string, (typeof rows)[number][]>();
  for (const r of rows) by.set(cell(r[0]), [...(by.get(cell(r[0])) ?? []), r]);
  const peak = Math.max(1, ...rows.map((r) => Number(r[2]) || 0));
  return (
    <div className="max-w-full overflow-x-auto">
      <div
        className="grid gap-3 sm:grid-cols-2"
        role="img"
        aria-label="Out readings by place, as in the table"
      >
        {[...by].map(([dim, rs]) => (
          <div key={dim} data-dimension={dim} className="text-xs">
            <div className="mb-1 font-medium">{dim}</div>
            {rs.slice(0, TOP).map((r) => {
              const n = Number(r[2]) || 0;
              return (
                <div key={cell(r[1])} className="flex items-center gap-2 py-0.5">
                  <span className="w-20 shrink-0 truncate">{cell(r[1])}</span>
                  <div className="h-2 bg-primary" style={{ width: `${(n / peak) * 100}%` }} />
                  <span className="text-muted-foreground">{n}</span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <table className="mt-2 w-full border-collapse text-left text-xs">
        <caption className="sr-only">Out readings by place</caption>
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
