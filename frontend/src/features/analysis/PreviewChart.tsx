import { useMemo } from "react";
import {
  CartesianGrid,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import type { components } from "../../api/types";
import { PointDetails } from "./PointDetails";

type Series = components["schemas"]["PreviewSeries"];
const palette = ["var(--primary)", "#4c9cbd", "#ae81cf", "#be7758", "#689c89"];

export function PreviewChart({ series }: { series: Series[] }) {
  const plotted = useMemo(
    () =>
      series.map((s) => ({
        key: s.key,
        points: s.points.map((point) => ({
          point,
          seriesKey: s.key,
          measuredAt: Date.parse(`${point.measured_date}T00:00:00Z`),
          // Approximation is used only for chart coordinates; retain the API string alongside it.
          cfAxis: Number(point.cf),
        })),
      })),
    [series],
  );
  return (
    <section className="panel p-4 sm:p-6" aria-labelledby="raw-cf-title">
      <h2 id="raw-cf-title" className="text-xl font-semibold">
        Raw CF
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Each point is a recorded measurement. Series colours identify display groups. Exact values
        are in the table below.
      </p>
      <div
        className="mt-5 h-80 w-full"
        role="img"
        aria-label="Raw CF by measured date, grouped into the series listed below"
      >
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 12, right: 20, bottom: 24, left: 4 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="measuredAt"
              name="Measured date"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(value) => new Date(value).toISOString().slice(0, 10)}
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              minTickGap={50}
              label={{
                value: "Measured date",
                position: "bottom",
                fill: "var(--muted-foreground)",
              }}
            />
            <YAxis
              type="number"
              dataKey="cfAxis"
              name="CF"
              tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
              label={{
                value: "CF",
                angle: -90,
                position: "insideLeft",
                fill: "var(--muted-foreground)",
              }}
            />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                const entry = payload?.[0]?.payload as
                  (typeof plotted)[number]["points"][number] | undefined;
                return active && entry ? (
                  <PointDetails seriesKey={entry.seriesKey} point={entry.point} />
                ) : null;
              }}
            />
            {plotted.map((s, i) => (
              <Scatter
                key={s.key}
                name={s.key}
                data={s.points}
                fill={palette[i % palette.length]}
                isAnimationActive={false}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <ul
        aria-label="Display series"
        className="mt-4 flex max-h-28 flex-wrap gap-x-5 gap-y-2 overflow-auto text-sm"
      >
        {series.map((s, i) => (
          <li key={s.key} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="size-2.5 rounded-full"
              style={{ background: palette[i % palette.length] }}
            />
            {s.key}
          </li>
        ))}
      </ul>
    </section>
  );
}
