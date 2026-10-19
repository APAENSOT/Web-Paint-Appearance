import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LabelList,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { plotDomain } from "../StudioCharts";
import { pointStatusLabel, sampleRows, type PointRead } from "./display";

const guideColor = (kind: string) =>
  kind === "standard" || kind === "target" ? "var(--success, #6ab9a0)" : "var(--primary)";
const shortValue = (value: string | number) =>
  Number(value).toLocaleString(undefined, { maximumFractionDigits: 2, useGrouping: false });
export function PointCharts({ data }: { data: PointRead }) {
  const rows = sampleRows(data.samples),
    box = data.box;
  const measured = rows.filter((r) => r.value !== null);
  const [readingKey, setReadingKey] = useState<string | null>(null);
  const activeReading = rows.find(
    (r) => `${data.point_key}:${data.metric}:${r.vehicleId}:${r.reading}` === readingKey,
  );
  const guides = data.reference_lines ?? [];
  const range = plotDomain([...measured.map((r) => r.value), ...guides.map((l) => l.value)]);
  const y = (v: string) => 238 - ((Number(v) - range[0]) / (range[1] - range[0])) * 210;
  let column = 0;
  const sampleColumns = data.samples.map((sample) => {
    const start = column;
    column += Math.max(1, sample.readings.length);
    return start;
  });
  const width = Math.max(460, 185 + column * 74);
  const readingX = (sample: number, reading = 0) => 180 + (sampleColumns[sample] + reading) * 74;
  const sampleX = (i: number) =>
    readingX(i) + ((Math.max(1, data.samples[i].readings.length) - 1) * 74) / 2;
  const trend = rows.map((r, i) => ({
    ...r,
    slot: String(i + 1),
    numericValue: r.value === null ? null : Number(r.value),
    tick: `${r.date.slice(5)} · ${r.sample}.${r.reading}`,
  }));
  return (
    <div
      className="monthly-chart-content"
      data-status={data.status ?? "UNCLASSIFIED"}
      key={`${data.point_key}-${data.metric}`}
    >
      <section className="monthly-chart" aria-label="Point reading distribution">
        <div className="monthly-section-title">
          <h4>Monthly distribution</h4>
          <div className="monthly-point-summary">
            {data.status && (
              <span data-status={data.status}>
                {pointStatusLabel(data.status, data.domain, data.metric)}
              </span>
            )}
            <small>
              {data.reading_count} readings · {data.unit}
            </small>
          </div>
        </div>
        <div className="monthly-standard-legend">
          <span>
            Current Standard · {data.orientation ?? "orientation unavailable"} ·{" "}
            {data.standard_scope ?? "NONE"}
          </span>
          {guides.map((l) => (
            <span key={l.kind} style={{ color: guideColor(l.kind) }}>
              {l.label}:{" "}
              <strong>
                {l.value} {data.unit}
              </strong>
            </span>
          ))}
          {!guides.length && <span>No applicable reference line for this measurement.</span>}
        </div>
        {box ? (
          <>
            <div
              className="monthly-distribution-scroll"
              tabIndex={0}
              role="region"
              aria-label="Dated reading chart; scroll for every sample"
            >
              <svg
                className="monthly-dated-boxplot"
                width={width}
                height={290}
                role="img"
                aria-label={`Monthly boxplot with all ${data.reading_count} readings by sample date and current Standard guides. Median ${box.median}.`}
              >
                {[0, 1, 2, 3, 4].map((t) => {
                  const n = range[0] + ((range[1] - range[0]) * t) / 4;
                  return (
                    <g key={t}>
                      <line
                        x1={48}
                        x2={width - 12}
                        y1={y(String(n))}
                        y2={y(String(n))}
                        stroke="var(--border)"
                      />
                      <text x={40} y={y(String(n)) + 4} textAnchor="end">
                        {Number(n.toPrecision(3))}
                      </text>
                    </g>
                  );
                })}
                {guides.map((l) => (
                  <line
                    key={l.kind}
                    x1={48}
                    x2={width - 12}
                    y1={y(l.value)}
                    y2={y(l.value)}
                    stroke={guideColor(l.kind)}
                    strokeDasharray="5 4"
                  >
                    <title>
                      {l.label}: {l.value} {data.unit}
                    </title>
                  </line>
                ))}
                <line
                  x1={88}
                  x2={88}
                  y1={y(box.whisker_lo)}
                  y2={y(box.whisker_hi)}
                  stroke="var(--point-status, var(--primary))"
                  strokeWidth={2}
                />
                {[box.whisker_lo, box.whisker_hi].map((v, i) => (
                  <line
                    key={i}
                    x1={77}
                    x2={99}
                    y1={y(v)}
                    y2={y(v)}
                    stroke="var(--point-status, var(--primary))"
                    strokeWidth={2}
                  />
                ))}
                <rect
                  x={70}
                  y={y(box.q3)}
                  width={36}
                  height={Math.max(1, y(box.q1) - y(box.q3))}
                  fill="color-mix(in srgb, var(--point-status, var(--primary)) 20%, transparent)"
                  stroke="var(--point-status, var(--primary))"
                />
                <line
                  x1={70}
                  x2={106}
                  y1={y(box.median)}
                  y2={y(box.median)}
                  stroke="var(--point-status, var(--primary))"
                  strokeWidth={3}
                />
                <g className="monthly-mean-marker">
                  <circle cx={88} cy={y(box.mean)} r={4} fill="var(--foreground)" />
                  <text x={88} y={18} textAnchor="middle">
                    Avg {shortValue(box.mean)}
                  </text>
                </g>
                <text x={88} y={260} textAnchor="middle">
                  Month
                </text>
                {data.samples.map((s, i) => (
                  <g key={s.vehicle_id}>
                    <text x={sampleX(i)} y={260} textAnchor="middle">
                      {s.measured_date.slice(5)}
                    </text>
                    <text x={sampleX(i)} y={278} textAnchor="middle">
                      #{i + 1}
                    </text>
                    {!s.readings.length && (
                      <text x={sampleX(i)} y={229} textAnchor="middle">
                        —
                      </text>
                    )}
                    {s.readings.map((r, j) => {
                      const x = readingX(i, j);
                      const dotY = y(r.value);
                      const key = `${data.point_key}:${data.metric}:${s.vehicle_id}:${j + 1}`;
                      return (
                        <g
                          key={j}
                          className="monthly-reading-mark"
                          role="button"
                          tabIndex={0}
                          aria-label={`Sample ${i + 1} reading ${j + 1}: ${r.value} ${data.unit}`}
                          aria-pressed={readingKey === key}
                          onClick={() => setReadingKey(key)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setReadingKey(key);
                            }
                          }}
                        >
                          <rect
                            x={x - 22}
                            y={dotY - 25}
                            width={44}
                            height={44}
                            fill="transparent"
                          />
                          <circle
                            cx={x}
                            cy={dotY}
                            r={4}
                            fill="var(--primary)"
                            stroke="var(--panel)"
                          >
                            <title>
                              Sample {i + 1}, {s.measured_date}: {r.value} {data.unit};{" "}
                              {s.serial_no ||
                                s.car_label ||
                                s.job_nos?.join(", ") ||
                                "Identity not supplied"}
                              ; reading {j + 1}
                            </title>
                          </circle>
                          <text
                            x={x}
                            y={dotY - 10}
                            textAnchor="middle"
                            className="monthly-reading-value"
                          >
                            {shortValue(r.value)}
                          </text>
                        </g>
                      );
                    })}
                  </g>
                ))}
              </svg>
            </div>
            {activeReading && (
              <p className="monthly-selected-reading" role="status">
                Sample {activeReading.sample}.{activeReading.reading} · {activeReading.date}
                <br />
                <strong>
                  {activeReading.value} {data.unit}
                </strong>{" "}
                · {activeReading.identity}
              </p>
            )}
            <dl className="monthly-box-values">
              {[
                ["Mean", box.mean],
                ["Median", box.median],
                ["Q1", box.q1],
                ["Q3", box.q3],
                ["Lower whisker", box.whisker_lo],
                ["Upper whisker", box.whisker_hi],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd title={value}>{shortValue(value)}</dd>
                </div>
              ))}
            </dl>
            <p className="monthly-help">
              Box: monthly middle 50% · Whiskers: Tukey 1.5 IQR · Dots and labels: every reading by
              dated sample. Select a dot for its exact stored value. Status uses box average and the
              current Standard.
            </p>
          </>
        ) : (
          <p className="monthly-empty">
            No {data.metric.toUpperCase()} readings at this point in {data.month}. Missing values
            are not zero.
          </p>
        )}
      </section>
      <details className="monthly-exact-samples" open>
        <summary>Sample details and exact readings ({data.sample_count})</summary>
        <div
          className="monthly-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="All monthly point samples"
        >
          <table>
            <thead>
              <tr>
                <th>Sample</th>
                <th>Measured date</th>
                <th>Identity</th>
                <th>
                  {data.metric.toUpperCase()} ({data.unit})
                </th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.vehicleId}-${r.reading}`}>
                  <td>
                    {r.sample}
                    {r.source ? `.${r.reading}` : ""}
                  </td>
                  <td>{r.date}</td>
                  <td>{r.identity}</td>
                  <td className="num">{r.value ?? "Not measured"}</td>
                  <td>
                    {r.source ? (
                      <>
                        {r.source.source_file ?? `Load ${r.source.load_id ?? "unavailable"}`}
                        <br />
                        {r.source.source_sheet ?? ""} · row {r.source.source_row ?? "unavailable"}
                        {r.source.measurement_id != null && (
                          <> · measurement {r.source.measurement_id}</>
                        )}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <section className="monthly-chart" aria-label="Point sample progression">
        <div className="monthly-section-title">
          <h4>Sample progression</h4>
          <span>{data.unit}</span>
        </div>
        {measured.length > 0 && (
          <div className="monthly-progression">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trend} margin={{ left: 0, right: 22, top: 24, bottom: 30 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="slot"
                  stroke="var(--muted-foreground)"
                  fontSize={11}
                  tickFormatter={(slot) => trend[Number(slot) - 1]?.tick ?? slot}
                  interval="preserveStartEnd"
                  angle={-25}
                  textAnchor="end"
                />
                <YAxis
                  domain={range}
                  stroke="var(--muted-foreground)"
                  width={45}
                  tickFormatter={(v) => String(Number(Number(v).toPrecision(3)))}
                  fontSize={11}
                />
                {guides.map((l) => (
                  <ReferenceLine
                    key={l.kind}
                    y={Number(l.value)}
                    stroke={guideColor(l.kind)}
                    strokeDasharray="5 4"
                  />
                ))}
                <Tooltip
                  content={({ active, payload }) => {
                    const r = payload?.[0]?.payload;
                    return active && r ? (
                      <div className="monthly-tooltip">
                        Sample {r.sample}.{r.reading} · {r.date}
                        <br />
                        {r.identity}
                        <br />
                        {r.value ?? "Not measured"} {data.unit}
                      </div>
                    ) : null;
                  }}
                />
                <Line
                  type="linear"
                  dataKey="numericValue"
                  stroke="var(--primary)"
                  strokeWidth={2}
                  dot={{ r: 4, fill: "var(--primary)" }}
                  activeDot={{ r: 6 }}
                  connectNulls={false}
                  isAnimationActive={false}
                >
                  {trend.length <= 20 && (
                    <LabelList
                      dataKey="numericValue"
                      position="top"
                      fill="var(--foreground)"
                      fontSize={11}
                      formatter={(value: unknown) =>
                        typeof value === "number" ? shortValue(value) : ""
                      }
                    />
                  )}
                </Line>
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        <p className="monthly-help">
          Each reading is connected in sample order; missing samples break the line. Dates identify
          samples, not test times. Same-day order follows the source data.{" "}
          {data.sample_count - data.checked_sample_count} samples have no selected-metric reading.
        </p>
      </section>
    </div>
  );
}
