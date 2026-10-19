import { useState, useRef } from "react";
import { MonthlyDistribution } from "./MonthlyDistribution";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import type { components } from "@/api/types";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
type Stats = components["schemas"]["ComparisonUngradedStats"];
type MonthBox = components["schemas"]["OverviewBox"] | components["schemas"]["FilmOverviewBox"];
type Group = components["schemas"]["ComparisonGroupMean"];
export interface BoxEntry {
  key: string;
  itemId?: string;
  itemName?: string;
  month?: string;
  label: string;
  orientation: "H" | "V";
  color?: string;
  caption?: string;
  n?: number;
  box?: Stats | MonthBox | null;
  group?: Group;
  selected?: number;
}
export function boxLines(box: Stats | MonthBox): [string, string | null][] {
  if ("ford" in box)
    return [
      ["Standard", box.ford ?? null],
      ["Minimum", box.minimum ?? null],
    ];
  if ("lo" in box)
    return [
      [box.lo_label ?? "Floor", box.lo],
      [box.hi_label ?? "Ceiling", box.hi],
      [box.target_label ?? "Target", box.target],
    ];
  return [];
}
export function plotDomain(values: (string | null | undefined)[]): [number, number] {
  const numbers = values
    .filter((v): v is string => v != null)
    .map(Number)
    .filter(Number.isFinite);
  if (!numbers.length) return [0, 100];
  const lo = Math.min(...numbers),
    hi = Math.max(...numbers),
    pad = Math.max((hi - lo) * 0.12, 1);
  return [lo - pad, hi + pad];
}
function exact(value: string | null | undefined) {
  return value ?? "Not measured";
}
export function Contributions({
  value,
}: {
  value: Group | components["schemas"]["ComparisonProfileMetric"];
}) {
  return (
    <div className="studio-contributions">
      <p>
        Equal-month mean: <strong className="num">{exact(value.mean)}</strong>
      </p>
      <p>
        Contributing months: {value.contributing_month_count} (
        {value.contributing_months.join(", ") || "None"})
      </p>
      <p>Missing months: {value.missing_months.join(", ") || "None"}</p>
      <table>
        <thead>
          <tr>
            <th>Month</th>
            <th>Mean</th>
            <th>n</th>
          </tr>
        </thead>
        <tbody>
          {value.monthly.map((m) => (
            <tr key={m.month}>
              <th>{m.month}</th>
              <td className="num">{exact(m.mean)}</td>
              <td>{m.n}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function BoxStage({
  entries,
  title,
  monthly = false,
}: {
  entries: BoxEntry[];
  title: string;
  monthly?: boolean;
}) {
  const [detail, setDetail] = useState<BoxEntry | null>(null);
  const opener = useRef<HTMLElement | SVGElement | null>(null);
  const openDetail = (entry: BoxEntry) => {
    const active = document.activeElement;
    opener.current = active instanceof HTMLElement || active instanceof SVGElement ? active : null;
    setDetail(entry);
  };
  const domain = plotDomain(
    entries.flatMap((e) =>
      e.group
        ? [e.group.mean]
        : e.box
          ? [
              e.box.box_min,
              e.box.box_max,
              e.box.whisker_lo,
              e.box.whisker_hi,
              e.box.mean,
              ...e.box.outliers,
              ...boxLines(e.box).map((l) => l[1]),
            ]
          : [],
    ),
  );
  const y = (v: string | number) => 222 - ((Number(v) - domain[0]) / (domain[1] - domain[0])) * 190;
  return (
    <section aria-label={title} className="studio-stage">
      <h2>{title}</h2>
      <p className="cv-muted">
        Individual distributions and supplied means.
        {entries.some((e) => e.group) ? " Diamonds identify temporary group means." : ""}
        {monthly ? " Scroll within each plot for all colours and months." : ""}
      </p>
      <div className={monthly ? "monthly-distributions" : "studio-pair"}>
        {(["H", "V"] as const).map((orientation) => {
          const orientationRows = entries.filter((e) => e.orientation === orientation);
          const colors = [...new Set(orientationRows.map((e) => e.color ?? ""))];
          return (
            <section
              key={orientation}
              className="studio-panel"
              aria-label={`${orientation === "H" ? "Horizontal" : "Vertical"} distributions`}
            >
              <h3>{orientation === "H" ? "Horizontal" : "Vertical"}</h3>
              {monthly ? (
                <MonthlyDistribution
                  entries={entries}
                  orientation={orientation}
                  onDetail={openDetail}
                />
              ) : (
                colors.map((color) => {
                  const rows = orientationRows.filter((e) => (e.color ?? "") === color);
                  const width = Math.max(440, rows.length * 95 + 60);
                  return (
                    <section
                      className="studio-colour-row"
                      key={color}
                      aria-label={color || "Selected vehicles"}
                    >
                      {color && <h4>{color}</h4>}
                      <div
                        className="studio-chart-scroll"
                        tabIndex={0}
                        aria-label={`${orientation} chart scroll`}
                      >
                        <svg
                          role="img"
                          aria-label={`${title}, ${orientation}. Exact values and gaps in the controls below.`}
                          viewBox={`0 0 ${width} 275`}
                          style={{ width, height: 275 }}
                        >
                          {[0, 1, 2, 3, 4].map((t) => {
                            const tick = domain[0] + ((domain[1] - domain[0]) * t) / 4;
                            return (
                              <g key={t}>
                                <line
                                  x1={48}
                                  x2={width - 8}
                                  y1={y(tick)}
                                  y2={y(tick)}
                                  stroke="var(--border)"
                                />
                                <text
                                  x={43}
                                  y={y(tick) + 4}
                                  textAnchor="end"
                                  fill="var(--muted-foreground)"
                                  fontSize={10}
                                >
                                  {Number(tick.toPrecision(3))}
                                </text>
                              </g>
                            );
                          })}
                          {rows.map((entry, index) => {
                            const x = 95 + index * 95,
                              box = entry.box,
                              group = entry.group;
                            return (
                              <g
                                key={entry.key}
                                onClick={() => setDetail(entry)}
                                data-testid={group ? "studio-group-marker" : "studio-month-box"}
                              >
                                {group ? (
                                  group.mean == null ? (
                                    <text
                                      x={x}
                                      y={135}
                                      textAnchor="middle"
                                      fill="var(--muted-foreground)"
                                      fontSize={11}
                                    >
                                      Unavailable
                                    </text>
                                  ) : (
                                    <>
                                      <path
                                        d={`M${x} ${y(group.mean) - 7} l7 7 l-7 7 l-7 -7 Z`}
                                        fill="var(--primary)"
                                      />
                                      <text
                                        x={x}
                                        y={y(group.mean) - 14}
                                        textAnchor="middle"
                                        fontSize={12}
                                        fill="var(--foreground)"
                                      >
                                        {group.mean}
                                      </text>
                                    </>
                                  )
                                ) : !box || entry.n === 0 ? (
                                  <text
                                    x={x}
                                    y={135}
                                    textAnchor="middle"
                                    fill="var(--muted-foreground)"
                                    fontSize={11}
                                  >
                                    Not measured
                                  </text>
                                ) : (
                                  <>
                                    {boxLines(box).map(([label, value]) =>
                                      value == null ? null : (
                                        <line
                                          key={label}
                                          x1={x - 32}
                                          x2={x + 32}
                                          y1={y(value)}
                                          y2={y(value)}
                                          stroke="var(--muted-foreground)"
                                          strokeDasharray="4 3"
                                        >
                                          <title>
                                            {label}: {value}
                                          </title>
                                        </line>
                                      ),
                                    )}
                                    {entry.n === 1 ? (
                                      <circle
                                        cx={x}
                                        cy={y(box.mean)}
                                        r={5}
                                        fill="var(--foreground)"
                                      />
                                    ) : (
                                      <>
                                        <line
                                          x1={x}
                                          x2={x}
                                          y1={y(box.whisker_lo)}
                                          y2={y(box.whisker_hi)}
                                          stroke="var(--foreground)"
                                        />
                                        {[box.whisker_lo, box.whisker_hi].map((v, i) => (
                                          <line
                                            key={i}
                                            x1={x - 11}
                                            x2={x + 11}
                                            y1={y(v)}
                                            y2={y(v)}
                                            stroke="var(--foreground)"
                                          />
                                        ))}
                                        <rect
                                          x={x - 17}
                                          width={34}
                                          y={y(box.q3)}
                                          height={Math.max(2, y(box.q1) - y(box.q3))}
                                          fill="var(--surface-2)"
                                          stroke="var(--foreground)"
                                        />
                                        <line
                                          x1={x - 17}
                                          x2={x + 17}
                                          y1={y(box.median)}
                                          y2={y(box.median)}
                                          stroke="var(--foreground)"
                                        />
                                      </>
                                    )}
                                    {box.outliers.map((v, i) => (
                                      <circle
                                        key={i}
                                        cx={x}
                                        cy={y(v)}
                                        r={3}
                                        fill="var(--foreground)"
                                      />
                                    ))}
                                    <text
                                      x={x}
                                      y={y(box.whisker_hi) - 10}
                                      textAnchor="middle"
                                      fontSize={11}
                                      fill="var(--foreground)"
                                    >
                                      {box.mean}
                                    </text>
                                  </>
                                )}
                                <text
                                  x={x}
                                  y={247}
                                  textAnchor="middle"
                                  fill="var(--foreground)"
                                  fontSize={10}
                                >
                                  {entry.caption ?? (group ? "Group mean" : "Vehicle")}
                                </text>
                                <title>
                                  {entry.label}: {exact(group?.mean ?? box?.mean)}
                                </title>
                              </g>
                            );
                          })}
                        </svg>
                      </div>
                      <div className="studio-box-controls">
                        {rows.map((e) => (
                          <button
                            key={e.key}
                            className="studio-box-control"
                            onClick={() => setDetail(e)}
                          >
                            <strong>{e.label}</strong>
                            <span className="num">
                              {e.group
                                ? `Group mean ${exact(e.group.mean)}`
                                : `Mean ${exact(e.box?.mean)}`}
                            </span>
                            {e.group ? (
                              <span>
                                {e.group.contributing_month_count} contributing / {e.selected}{" "}
                                selected
                              </span>
                            ) : (
                              <span>
                                {e.n == null ? "Not measured" : `n ${e.n}`}{" "}
                                {e.box && "status" in e.box
                                  ? ` / ${e.box.status ?? "Status unavailable"}`
                                  : ""}
                              </span>
                            )}
                          </button>
                        ))}
                      </div>
                    </section>
                  );
                })
              )}
              {!orientationRows.length && (
                <p className="cv-empty">No {orientation} series returned.</p>
              )}
            </section>
          );
        })}
      </div>
      <Dialog
        open={!!detail}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
      >
        <DialogContent
          className="cv-detail"
          aria-describedby={undefined}
          onCloseAutoFocus={(event) => {
            if (monthly) {
              event.preventDefault();
              opener.current?.focus();
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {detail?.label} / {detail?.orientation}
            </DialogTitle>
          </DialogHeader>
          {detail?.group ? (
            <>
              <p>
                {detail.group.metric.toUpperCase()} / {detail.group.layer_code ?? "WaveScan"}
              </p>
              <p>{detail.selected} selected member months</p>
              <Contributions value={detail.group} />
            </>
          ) : detail?.box ? (
            <>
              {"model_code" in detail.box && (
                <p>
                  {detail.box.model_code} / {detail.box.color_name} / {detail.box.orient}
                  {"layer_code" in detail.box ? ` / ${detail.box.layer_code}` : " / CF"}
                </p>
              )}
              <p>n {detail.n}</p>
              <dl className="studio-stats">
                {(
                  [
                    "mean",
                    "box_min",
                    "q1",
                    "median",
                    "q3",
                    "box_max",
                    "whisker_lo",
                    "whisker_hi",
                  ] as const
                ).map((k) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd className="num">{detail.box![k]}</dd>
                  </div>
                ))}
                <div>
                  <dt>Outliers</dt>
                  <dd>{detail.box.outliers.join(", ") || "None"}</dd>
                </div>
                {"status" in detail.box && (
                  <div>
                    <dt>Status</dt>
                    <dd>{detail.box.status ?? "Unavailable"}</dd>
                  </div>
                )}
                {boxLines(detail.box)
                  .filter(([, v]) => v != null)
                  .map(([label, v]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{v}</dd>
                    </div>
                  ))}
                {"standard_scope" in detail.box && (
                  <div>
                    <dt>Standard scope</dt>
                    <dd>{detail.box.standard_scope}</dd>
                  </div>
                )}
                {"below_minimum" in detail.box && (
                  <div>
                    <dt>Below minimum</dt>
                    <dd>
                      {detail.box.below_minimum
                        .map(
                          (v) =>
                            `${v.measurement_id}: ${v.cf} / ${v.checkzone ?? "Zone not recorded"} / ${v.measured_date ?? "Date not recorded"}`,
                        )
                        .join("; ") || "None"}
                    </dd>
                  </div>
                )}
              </dl>
            </>
          ) : (
            <p>Not measured</p>
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}
export interface ProfileLine {
  id: string;
  label: string;
  orientation: "H" | "V" | null;
  values: { metric: string; value: string | null; detail: React.ReactNode }[];
}
const strokes = ["#8dd9dc", "#f6ba65", "#ba9bea", "#e6a6b4", "#9bc69b"];
export function ProfilePair({
  lines,
  title,
  focusLocations = false,
}: {
  lines: ProfileLine[];
  title: string;
  focusLocations?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<{ id: string; metric: string } | null>(null);
  const domain = plotDomain(
    lines.filter((l) => l.orientation != null).flatMap((l) => l.values.map((v) => v.value)),
  );
  const focused = lines.find((l) => l.id === selected?.id);
  const value = focused?.values.find((v) => v.metric === selected?.metric);
  return (
    <div className="studio-profile" aria-label={title}>
      {focusLocations && (
        <div className="studio-toolbar">
          <button className="cv-button" onClick={() => setSelected(null)}>
            Show all locations
          </button>
          <p className="cv-muted">
            Measured dots; curves join exact points. Select a location to focus.
          </p>
        </div>
      )}
      <label className="studio-search">
        Search location or source
        <input className="cv-input" value={search} onChange={(e) => setSearch(e.target.value)} />
      </label>
      <div className="studio-pair">
        {(["H", "V"] as const).map((o) => {
          const oriented = lines.filter((l) => l.orientation === o);
          const metrics = oriented[0]?.values.map((v) => v.metric) ?? [
            "du",
            "wa",
            "wb",
            "wc",
            "wd",
            "we",
          ];
          const rows = metrics.map((metric) =>
            Object.fromEntries([
              ["metric", metric.toUpperCase()],
              ...oriented.map((l) => [
                l.id,
                l.values.find((v) => v.metric === metric)?.value == null
                  ? null
                  : Number(l.values.find((v) => v.metric === metric)!.value),
              ]),
            ]),
          );
          return (
            <section
              className="studio-panel"
              key={o}
              aria-label={`${o === "H" ? "Horizontal" : "Vertical"} DU-WE`}
            >
              <h3>{o === "H" ? "Horizontal" : "Vertical"} / DU-WE</h3>
              <div
                className="studio-profile-plot"
                role="img"
                aria-label={`${title}, ${o}, ${oriented.length} distinct location/source lines. Null readings break lines. Select a legend entry for exact values.`}
              >
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={rows} margin={{ top: 20, right: 15, left: -15, bottom: 8 }}>
                    <CartesianGrid stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="metric" tick={{ fontSize: 10 }} />
                    <YAxis
                      domain={domain}
                      tickFormatter={(v) => String(Number(Number(v).toPrecision(3)))}
                      tick={{ fontSize: 10 }}
                    />
                    {oriented.map((l, i) => (
                      <Line
                        key={l.id}
                        dataKey={l.id}
                        type="monotone"
                        stroke={strokes[i % strokes.length]}
                        strokeOpacity={focusLocations && focused && focused.id !== l.id ? 0.18 : 1}
                        strokeWidth={focusLocations && focused?.id === l.id ? 2.5 : 1.5}
                        strokeDasharray={i % 3 === 0 ? undefined : i % 3 === 1 ? "5 3" : "2 3"}
                        connectNulls={false}
                        isAnimationActive={false}
                        dot={(props: {
                          cx?: number;
                          cy?: number;
                          index?: number;
                          value?: number | null;
                        }) =>
                          props.value == null ? (
                            <g />
                          ) : (
                            <circle
                              key={props.index}
                              cx={props.cx}
                              cy={props.cy}
                              data-testid="profile-measured-dot"
                              data-line={l.id}
                              data-metric={metrics[props.index ?? 0]}
                              data-exact={l.values[props.index ?? 0]?.value}
                              r={focusLocations && focused?.id === l.id ? 5 : 4}
                              opacity={focusLocations && focused && focused.id !== l.id ? 0.18 : 1}
                              fill={strokes[i % strokes.length]}
                              onClick={() =>
                                setSelected({ id: l.id, metric: metrics[props.index ?? 0] })
                              }
                            />
                          )
                        }
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {!oriented.length && <p>Not measured</p>}
              <div className="studio-legend">
                {oriented
                  .map((l, i) => ({ l, i }))
                  .filter(({ l }) => l.label.toLowerCase().includes(search.toLowerCase()))
                  .map(({ l, i }) => (
                    <button
                      key={l.id}
                      className="cv-button"
                      aria-pressed={selected?.id === l.id}
                      onClick={() => setSelected({ id: l.id, metric: l.values[0]?.metric ?? "du" })}
                    >
                      <span aria-hidden style={{ color: strokes[i % strokes.length] }}>
                        {i % 3 === 0 ? "● ━" : i % 3 === 1 ? "◆ ┄" : "■ ···"}
                      </span>{" "}
                      {l.label}
                    </button>
                  ))}
              </div>
            </section>
          );
        })}
      </div>
      {!!lines.filter((l) => l.orientation == null).length && (
        <details>
          <summary>Unproved orientation locations</summary>
          {lines
            .filter((l) => l.orientation == null)
            .map((l) => (
              <button
                className="cv-button"
                key={l.id}
                onClick={() => setSelected({ id: l.id, metric: l.values[0]?.metric ?? "du" })}
              >
                {l.label}
              </button>
            ))}
        </details>
      )}
      {focused && (
        <section className="studio-panel" aria-label="Profile exact values">
          <h3>
            {focused.label} / {focused.orientation ?? "Unproved orientation"}
          </h3>
          <div className="studio-toolbar">
            {focused.values.map((v) => (
              <button
                className="cv-button"
                key={v.metric}
                aria-pressed={value?.metric === v.metric}
                onClick={() => setSelected({ id: focused.id, metric: v.metric })}
              >
                {v.metric.toUpperCase()} {exact(v.value)}
              </button>
            ))}
          </div>
          {value?.detail}
        </section>
      )}
    </div>
  );
}
