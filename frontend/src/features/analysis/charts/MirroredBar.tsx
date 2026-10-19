/**
 * AR05 mirrored bars: per panel, the left median bar grows left and the right median bar grows right
 * from one centre line, with the gap and its verdict word. The table carries the same numbers.
 */

import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";
import { EvidenceTable } from "./Table";

type Evidence = AssistantAnswer["evidence"];

export function MirroredBar({ evidence }: { evidence: Evidence }) {
  const { columns, rows } = evidence;
  const data = rows
    .map((r) => ({
      panel: cell(r[0]),
      l: Number(r[1]),
      r: Number(r[2]),
      d: cell(r[3]),
      v: cell(r[4]),
    }))
    .filter((x) => Number.isFinite(x.l) && Number.isFinite(x.r));
  if (!data.length) return <EvidenceTable evidence={evidence} caption="Left and right per panel" />;
  const max = Math.max(...data.map((x) => Math.max(x.l, x.r))) || 1;
  return (
    <div className="max-w-full overflow-x-auto">
      <div role="img" aria-label="Left and right medians for each panel, as in the table">
        {data.map((x) => (
          <div
            key={x.panel}
            data-panel={x.panel}
            className="flex items-center gap-2 py-0.5 text-xs"
          >
            <span className="w-28 shrink-0 truncate">{x.panel}</span>
            <div className="flex h-3 w-24 justify-end">
              <div className="bg-primary/60" style={{ width: `${(x.l / max) * 100}%` }} />
            </div>
            <div className="h-3 w-24">
              <div className="bg-primary" style={{ width: `${(x.r / max) * 100}%` }} />
            </div>
            <span className="text-muted-foreground">{`Δ ${x.d} · ${x.v}`}</span>
          </div>
        ))}
      </div>
      <table className="mt-2 w-full border-collapse text-left text-xs">
        <caption className="sr-only">Left and right medians for each panel</caption>
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
