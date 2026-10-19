import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";

type Evidence = AssistantAnswer["evidence"];

/** The evidence rows as a plain table: every chart's fallback and its text twin. */
export function EvidenceTable({ evidence, caption }: { evidence: Evidence; caption: string }) {
  const { columns, rows } = evidence;
  return (
    <table className="mt-2 w-full border-collapse text-left text-xs">
      <caption className="sr-only">{caption}</caption>
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
          // by index: first cells repeat (Scatter cars, LimitCard layers, CarBars car numbers)
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
  );
}
