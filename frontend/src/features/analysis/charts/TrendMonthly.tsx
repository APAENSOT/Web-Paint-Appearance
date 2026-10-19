/**
 * AR05 monthly trend: the box's monthly mean over up to six months, each point labelled with
 * the status word, dashed limit lines. The table below is the same numbers (and the fallback).
 */

import {
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";

type Evidence = AssistantAnswer["evidence"];
const TICK = { fontSize: 11, fill: "var(--muted-foreground)" };

export function TrendMonthly({ evidence }: { evidence: Evidence }) {
  const { columns, rows, limits } = evidence;
  const data = rows
    .filter((r) => typeof r[1] === "number")
    .map((r) => ({ x: cell(r[0]), y: r[1] as number, word: cell(r[2]) }));
  return (
    <div className="max-w-full overflow-x-auto">
      {data.length > 0 && (
        <div
          className="h-48 w-full"
          role="img"
          aria-label="Monthly mean with the status word and the box limits"
        >
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 20, right: 24, bottom: 4, left: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="x" tick={TICK} tickFormatter={(x: string) => x.slice(0, 3)} />
              <YAxis tick={TICK} width={44} domain={["auto", "auto"]} />
              {limits?.lo != null && (
                <ReferenceLine y={limits.lo} stroke="var(--critical)" strokeDasharray="4 4" />
              )}
              {limits?.hi != null && (
                <ReferenceLine y={limits.hi} stroke="var(--critical)" strokeDasharray="4 4" />
              )}
              <Line dataKey="y" stroke="var(--primary)" dot={{ r: 3 }} isAnimationActive={false}>
                <LabelList dataKey="word" position="top" fontSize={11} />
              </Line>
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <table className="mt-2 w-full border-collapse text-left text-xs">
        <caption className="sr-only">Monthly mean and status</caption>
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
              {r.map((v, i) => (
                <td key={columns[i]} className="px-1 py-1">
                  {cell(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
