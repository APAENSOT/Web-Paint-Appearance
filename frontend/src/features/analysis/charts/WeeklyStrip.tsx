/**
 * AR05 weekly strip: one bar per week (the Out count); a flagged week carries its flag word
 * ("flagged", "missing") under its bar, not colour alone. The table below is the same numbers.
 */

import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";

type Evidence = AssistantAnswer["evidence"];

export function WeeklyStrip({ evidence }: { evidence: Evidence }) {
  const { columns, rows } = evidence;
  if (!rows.length) return null;
  const out = columns.indexOf("Out");
  const flag = columns.indexOf("Flag");
  const peak = Math.max(1, ...rows.map((r) => Number(r[out]) || 0));
  return (
    <div className="max-w-full overflow-x-auto">
      <ul className="flex h-28 items-end gap-2" aria-label="Out readings per week, as in the table">
        {rows.map((r) => {
          const n = Number(r[out]) || 0;
          const note = r[flag] ? cell(r[flag]) : "";
          const flagged = note !== "";
          return (
            <li
              key={String(r[0])}
              data-week={cell(r[0])}
              className="flex h-full flex-1 flex-col justify-end text-center text-xs"
            >
              <span>{n}</span>
              <span
                style={{
                  height: `${(n / peak) * 70}%`,
                  minHeight: 2,
                  background: flagged ? "var(--critical)" : "var(--primary)",
                }}
              />
              <span className="text-muted-foreground">{cell(r[0])}</span>
              <span className="font-semibold">{note || "\u00a0"}</span>
            </li>
          );
        })}
      </ul>
      <table className="mt-2 w-full border-collapse text-left text-xs">
        <caption className="sr-only">Readings and out readings per week</caption>
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
