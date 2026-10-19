/**
 * AR05: the answer's chart, picked by evidence.kind. AR04's ranked bar and trend
 * line moved here unchanged; a kind without a chart yet renders the table only.
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { evidenceCell as cell } from "../report-slides";
import { Breakdown } from "./Breakdown";
import { BoxplotGroup } from "./BoxplotGroup";
import { BoxplotPair } from "./BoxplotPair";
import { CarBars } from "./CarBars";
import { Distribution } from "./Distribution";
import { Heatmap } from "./Heatmap";
import { LimitCard } from "./LimitCard";
import { MirroredBar } from "./MirroredBar";
import { PointBars } from "./PointBars";
import { Scatter } from "./Scatter";
import { Shift } from "./Shift";
import { Spectrum } from "./Spectrum";
import { Stat } from "./Stat";
import { StatusGrid } from "./StatusGrid";
import { TrendMonthly } from "./TrendMonthly";
import { WeeklyStrip } from "./WeeklyStrip";
import type { AssistantAnswer } from "../report-types";

type Evidence = AssistantAnswer["evidence"];
export const TOP = 5;
/** Kinds whose chart prints the evidence rows as its own table, so the card adds no second one. */
export const OWN_TABLE = new Set([
  "heatmap",
  "grid",
  "trend_monthly",
  "boxplot_pair",
  "boxplot_group",
  "mirrored_bar",
  "point_bars",
  "breakdown",
  "car_bars",
  "distribution",
  "weekly_strip",
  "limit_card",
  "stat",
  "spectrum",
  "scatter",
]);
const TICK = { fontSize: 11, fill: "var(--muted-foreground)" };

/** The ranked bar per evidence column set the API sends: which column is the bar, which name it. */
const BAR: Record<string, { value: string; label: string[] }> = {
  "Box|Status|Out|n": { value: "Out", label: ["Box"] }, // summary
  "Box|Status|Capability|Out|n": { value: "Out", label: ["Box"] }, // colours
  "Point|Out|Measured|Plant normal": { value: "Out", label: ["Point"] }, // points
  "Model|Colour|Band|Change|Verdict|Layer": { value: "Change", label: ["Model", "Colour", "Band"] }, // bands
  "Box|Expected out of 30|Basis|Now": { value: "Expected out of 30", label: ["Box"] }, // next-month risk
  "Band|ρ|n": { value: "ρ", label: ["Band"] }, // CF drivers
  "Box|Change|Verdict|Now": { value: "Change", label: ["Box"] }, // went well
};

/** One small chart matched to the topic: ranked bar, or trend line with its limits. */
export function EvidenceChart({
  evidence,
  periods,
}: {
  evidence: Evidence;
  periods?: { before: string; now: string };
}) {
  const { kind, columns, rows, limits } = evidence;
  if (kind === "trend" && evidence.series.length) {
    return (
      <div
        className="h-48 w-full"
        role="img"
        aria-label="Daily mean this month with the box limits"
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={evidence.series} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              dataKey="x"
              tick={TICK}
              tickFormatter={(x: string) => x.slice(5)}
              minTickGap={24}
            />
            <YAxis tick={TICK} width={44} domain={["auto", "auto"]} />
            {limits?.lo != null && (
              <ReferenceLine
                y={limits.lo}
                stroke="var(--critical)"
                strokeDasharray="4 4"
                label={{
                  value: "Lower limit",
                  fill: "var(--muted-foreground)",
                  fontSize: 11,
                  position: "insideBottomLeft",
                }}
              />
            )}
            {limits?.hi != null && (
              <ReferenceLine
                y={limits.hi}
                stroke="var(--critical)"
                strokeDasharray="4 4"
                label={{
                  value: "Upper limit",
                  fill: "var(--muted-foreground)",
                  fontSize: 11,
                  position: "insideTopLeft",
                }}
              />
            )}
            <Line dataKey="y" stroke="var(--primary)" dot={{ r: 2 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }
  // Called, not mounted: null then means "drew nothing", which the card turns into an open table.
  // The charts are hook-free; one that needs a hook must decide emptiness before it.
  if (kind === "heatmap") return Heatmap({ evidence });
  if (kind === "grid") return StatusGrid({ evidence });
  if (kind === "trend_monthly") return TrendMonthly({ evidence });
  if (kind === "boxplot_pair") return BoxplotPair({ evidence });
  if (kind === "boxplot_group") return BoxplotGroup({ evidence });
  if (kind === "mirrored_bar") return MirroredBar({ evidence });
  if (kind === "point_bars") return PointBars({ evidence });
  if (kind === "breakdown") return Breakdown({ evidence });
  if (kind === "car_bars") return CarBars({ evidence });
  if (kind === "distribution") return Distribution({ evidence });
  if (kind === "weekly_strip") return WeeklyStrip({ evidence });
  if (kind === "limit_card") return LimitCard({ evidence });
  if (kind === "stat") return Stat({ evidence });
  if (kind === "spectrum") return Spectrum({ evidence });
  if (kind === "scatter") return Scatter({ evidence });
  if (kind === "shift") return Shift({ evidence, periods });
  if (kind !== "bar" && kind !== "table") return null;
  const bar = BAR[columns.join("|")];
  if (!bar) return null; // an unknown column set: the table alone
  const at = columns.indexOf(bar.value);
  const name = bar.label.map((l) => columns.indexOf(l));
  const data = rows
    .slice(0, TOP)
    .filter((r) => r[at] !== null && r[at] !== "" && Number.isFinite(Number(r[at])))
    .map((r) => ({
      name: name.map((i) => cell(r[i])).join(" "),
      value: Number(r[at]),
      measured:
        bar.value === "Out" && columns.includes("n")
          ? r[columns.indexOf("n")]
          : bar.value === "Out" && columns.includes("Measured")
            ? r[columns.indexOf("Measured")]
            : null,
      status: columns.includes("Status") ? cell(r[columns.indexOf("Status")]) : null,
    }));
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => Math.abs(d.value)), 1);
  return (
    <div
      className="guide-ranked-chart w-full"
      role="img"
      aria-label={`${columns[at]} for the top ${data.length}, as in the table: ${data.map((d) => `${d.name}: ${d.value}${d.measured != null ? ` of ${cell(d.measured)} readings` : ""}`).join("; ")}`}
    >
      <p className="mb-4 text-sm text-muted-foreground">
        {columns[at] === "Out" ? "Readings outside the standard" : columns[at]}
        {rows.length > TOP ? ` · First ${TOP} results in report order` : ""}
      </p>
      <ol className="grid gap-5">
        {data.map((d, i) => (
          <li key={`${d.name}-${i}`} className="guide-ranked-row">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
              <span className="min-w-0 flex-1 basis-48 font-medium">{d.name}</span>
              <span className="num font-semibold">
                {d.value > 0 && columns[at] === "Change" ? "+" : ""}
                {d.value}
                {d.measured != null ? (
                  <span className="font-normal text-muted-foreground">
                    {" "}
                    of {cell(d.measured)} readings
                  </span>
                ) : columns[at] === "Expected out of 30" ? (
                  <span className="font-normal text-muted-foreground"> of the next 30</span>
                ) : null}
              </span>
            </div>
            <div className="guide-bar-track" aria-hidden="true">
              <span
                className={i === 0 ? "guide-bar guide-bar--lead" : "guide-bar"}
                style={{ width: `${(Math.abs(d.value) / max) * 100}%` }}
              />
            </div>
            {d.status && <p className="mt-1 text-xs text-muted-foreground">{d.status}</p>}
          </li>
        ))}
      </ol>
      <p className="mt-4 text-xs text-muted-foreground">
        Bar length compares values on one scale
        {data.some((d) => d.value < 0) ? "; the printed sign shows direction" : ""}. It does not
        show a pass rate.
      </p>
    </div>
  );
}
