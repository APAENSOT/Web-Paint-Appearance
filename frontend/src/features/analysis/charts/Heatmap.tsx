/**
 * AR05 heat map: one row per colour (or layer), one column per layer (or side). Each cell
 * shows the dashboard's status word with the same tone dot as the report, the box that sets
 * it, and the move since last month. A real table, so screen readers get rows and headers.
 */

import { StatusChip, type Code } from "../AnalysisReportView";
import type { AssistantAnswer } from "../report-types";
import { EvidenceTable } from "./Table";

type Evidence = AssistantAnswer["evidence"];

export function Heatmap({ evidence }: { evidence: Evidence }) {
  const { columns, rows, cells } = evidence;
  if (!cells.length) return <EvidenceTable evidence={evidence} caption="Status per row" />;
  return (
    <div className="max-w-full overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-left text-xs">
        <caption className="sr-only">Status of each cell, with what sets it and the move</caption>
        <thead className="text-muted-foreground">
          <tr>
            {columns.map((h, i) => (
              <th
                key={h}
                scope="col"
                className={`px-1 py-1.5 font-medium ${i === 0 ? "w-[22%]" : ""}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cells.map((line, r) => (
            <tr key={String(rows[r]?.[0] ?? r)} className="border-t border-border align-top">
              <th scope="row" className="px-1 py-1.5 font-semibold break-words">
                {rows[r]?.[0]}
              </th>
              {line.map((c, i) => (
                <td
                  key={columns[i + 1]}
                  className="px-1 py-1.5 break-words [&_[data-tone]]:whitespace-normal"
                >
                  <StatusChip code={c.status_code as Code} word={c.word} />
                  {c.arrow && (
                    <span aria-label={c.arrow === "↑" ? "better" : "worse"}> {c.arrow}</span>
                  )}
                  {c.note && <div className="text-muted-foreground">{c.note}</div>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
