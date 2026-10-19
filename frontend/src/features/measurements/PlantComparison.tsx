import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent,
} from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouter } from "@tanstack/react-router";
import {
  CartesianGrid,
  ComposedChart,
  Customized,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChevronDown,
  Check,
  FileDown,
  GripVertical,
  ImageDown,
  Link2,
  Lock,
  Plus,
  RotateCcw,
  Search,
  Star,
  Table2,
  X,
} from "lucide-react";
import type { components } from "@/api/types";
import { ApiError } from "@/api/client";
import { queryOptions } from "@tanstack/react-query";
import {
  api,
  comparisonPointsOptions,
  comparisonVehicleVisualsOptions,
  comparisonVehiclesOptions,
} from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import {
  displayMean,
  integerDomain,
  integerTicks,
  statusLabel,
  type OverviewBox,
} from "./overview-display";
import {
  FILM_LAYERS,
  statusPresentation,
  type FilmOverviewData,
} from "@/features/filmthickness/film-overview-display";
import {
  DOMAIN_LABEL,
  MAX_CARS,
  MAX_MONTHS,
  METRIC_ORDER,
  PANELS,
  SPECTRUM,
  addCard,
  blockReason,
  byWeek,
  carLabel,
  carMonth,
  emptyBench,
  isEmpty,
  locationStyles,
  metricLabel,
  monthValue,
  monthModel,
  moveSlot,
  profileRows,
  neighbour,
  presetMonths,
  removeSlot,
  retargetMonths,
  spectrumRows,
  toShared,
  traces,
  type Bench,
  type Car,
  type Card,
  type Domain,
  type Metric,
  type Orient,
  type Panel,
  type SharedBench,
  type SlotKind,
  type Trace,
} from "./comparison-bench";
import { chartPng, download, fileName, toCsv, type TableData } from "./chart-export";
import "./comparison-bench.css";
import "./comparison-filter-polish.css";
import { dayText, weekText } from "./day-text";

type Overview = components["schemas"]["WavescanOverviewOut"];
type Tone = "nominal" | "caution" | "critical" | "over" | "neutral";
type Spec = { label: string; value: string; tone: Tone; dash: string };
/** One boxplot, normalised from the WaveScan or Film overview so one chart draws both. */
type Box = {
  layer: string | null;
  model_code: string;
  color_name: string;
  orient: Orient;
  n: number;
  q1: string;
  median: string;
  q3: string;
  whisker_lo: string;
  whisker_hi: string;
  box_min: string;
  box_max: string;
  outliers: string[];
  mean: string;
  tone: Tone;
  statusText: string;
  specs: Spec[];
};
type MonthBoxes = { colors: string[]; boxes: Box[] };
type MonthData = { month: string; data: MonthBoxes; model?: string };
type Marker = {
  id: string;
  n: number;
  label: string;
  color: string;
  month: string;
  value: number;
  mean: string;
};
type Scale = ((value: string) => number) & { bandwidth?: () => number };
type NumericScale = ((value: number) => number) & { range?: () => number[] };
type Axes = {
  xAxisMap?: Record<string, { scale?: Scale; bandwidth?: number }>;
  yAxisMap?: Record<string, { scale?: NumericScale; y?: number; height?: number }>;
};

const PAGE = 50;
const WEEKS = [
  [1, "1–7"],
  [2, "8–14"],
  [3, "15–21"],
  [4, "22–28"],
  [5, "29–end"],
] as const;
// Validated categorical palette (dataviz reference); car n and pin n share slot n.
const slotColor = (n: number) => `var(--series-${n})`;
const carContext = (car: Car) =>
  `${car.color ?? "No colour"} · ${dayText(car.measured_date, car.date_is_month_only)}`;

function monthParts(month: string): [string, string] {
  const [year, number] = month.split("-").map(Number);
  if (!year || !number) return [month, ""];
  return [new Date(year, number - 1, 1).toLocaleString("en-US", { month: "short" }), String(year)];
}
const monthName = (month: string) => monthParts(monthValue(month)).join(" ");
const shortDate = (date: string, monthOnly?: boolean) =>
  monthOnly
    ? dayText(date, true)
    : new Date(`${date}T00:00:00`).toLocaleString("en-US", { day: "numeric", month: "short" });

const TONE: Record<Tone, string> = {
  nominal: "var(--nominal)",
  caution: "var(--caution)",
  critical: "var(--critical)",
  over: "var(--film-over)",
  neutral: "var(--muted-foreground)",
};
const TONE_RANK: Tone[] = ["critical", "over", "caution", "nominal"];
const STATUS_ATTR: Partial<Record<Tone, string>> = {
  critical: "FAIL",
  over: "OVER",
  caution: "WARNING",
  nominal: "PASS",
};

const waveTone = (s: OverviewBox["status"]): Tone =>
  s === "PASS" ? "nominal" : s === "WARNING" ? "caution" : s === "FAIL" ? "critical" : "neutral";
const waveBoxes = (d: Overview): MonthBoxes => ({
  colors: d.color_options.map((o) => o.color_name),
  boxes: d.boxes.map((b) => ({
    ...b,
    layer: null,
    tone: waveTone(b.status),
    statusText: statusLabel(b.status),
    specs: [
      ...(b.ford != null
        ? [{ label: "Standard", value: b.ford, tone: "nominal" as const, dash: "4 3" }]
        : []),
      ...(b.minimum != null
        ? [{ label: "Minimum", value: b.minimum, tone: "critical" as const, dash: "4 3" }]
        : []),
    ],
  })),
});
const filmBoxes = (d: FilmOverviewData): MonthBoxes => ({
  colors: d.color_sequence.map((e) => e.color_name),
  boxes: d.boxes.map((b) => {
    const status = statusPresentation(b);
    const spec = (value: string | null, label: string, tone: Tone, dash: string) =>
      value == null || b.standard_scope === "NONE" ? [] : [{ label, value, tone, dash }];
    return {
      ...b,
      layer: b.layer_code,
      orient: b.orient === "H" ? ("Horizontal" as const) : ("Vertical" as const),
      tone: status.colour as Tone,
      statusText: status.text,
      specs: [
        ...spec(b.lo, b.lo_label ?? "Minimum", "critical", "6 4"),
        ...spec(b.hi, b.hi_label ?? "Maximum", "over", "2 4"),
        ...spec(b.target, b.target_label ?? "Target", "nominal", "8 3 2 3"),
      ],
    };
  }),
});
/** Month boxplots for either domain, normalised; shared by the deck cards and the bench charts. */
const monthBoxesOptions = (code: string, domain: Domain, month: string) =>
  queryOptions({
    queryKey: ["comparison", "month-boxes", code, domain, month],
    queryFn: async ({ signal }) =>
      domain === "WAVESCAN"
        ? waveBoxes(await api().wavescanOverview(code, { month }, signal))
        : filmBoxes(await api().filmOverview(code, { month }, signal)),
    staleTime: Infinity,
    retry: false,
  });
const layerLabel = (layer: string) => FILM_LAYERS.find((l) => l.code === layer)?.label ?? layer;

function chartDomain(boxes: Box[], extra: number[]): [number, number] {
  const values = [
    ...extra,
    ...boxes.flatMap((box) =>
      [
        box.whisker_lo,
        box.whisker_hi,
        box.box_min,
        box.box_max,
        ...box.specs.map((s) => s.value),
        ...box.outliers,
      ].map(Number),
    ),
  ].filter(Number.isFinite);
  if (!values.length) return [0, 100];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = Math.max((hi - lo) * 0.12, 2);
  return integerDomain(lo - pad, hi + pad);
}

const diamond = (x: number, y: number, r: number) =>
  `M${x},${y - r} L${x + r},${y} L${x},${y + r} L${x - r},${y} Z`;

/** Split a colour name over at most two lines that fit `max` characters. */
function wrapName(name: string, max: number): string[] {
  if (name.length <= max) return [name];
  const lines: string[] = [];
  let line = "";
  for (const word of name.split(" ")) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > max && line) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  lines.push(line);
  const fit = (l: string) => (l.length > max ? `${l.slice(0, Math.max(1, max - 1))}…` : l);
  return lines.length > 2 ? [fit(lines[0]), fit(`${lines[1]}…`)] : lines.map(fit);
}

function GroupedLayer({
  xAxisMap,
  yAxisMap,
  colors,
  months,
  entries,
  markers,
  orient,
  baseline,
  onColor,
}: Axes & {
  colors: string[];
  months: MonthData[];
  entries: Array<{ month: string; box: Box }>;
  markers: Marker[];
  orient: Orient;
  baseline: string | null;
  onColor: (color: string) => void;
}) {
  const xScale = Object.values(xAxisMap ?? {})[0]?.scale;
  const yAxis = Object.values(yAxisMap ?? {})[0];
  const yScale = yAxis?.scale;
  if (!xScale || !yScale) return null;
  const step = colors.length > 1 ? Math.abs(xScale(colors[1]) - xScale(colors[0])) : 340;
  const bandwidth = xScale.bandwidth?.() ?? 0;
  const slot = bandwidth > 0 ? bandwidth : step;
  const center = (color: string) => xScale(color) + (bandwidth > 0 ? slot / 2 : 0);
  const boxOf = (month: string, color: string) =>
    entries.find((e) => e.month === month && e.box.color_name === color)?.box;
  // Only months with a box for that colour get a column: no blank gaps.
  const present = (color: string) => months.filter(({ month }) => boxOf(month, color));
  const columns = Math.max(1, ...colors.map((c) => present(c).length));
  // Everything is sized from the panel width, so more months or colours pack tighter, never scroll.
  const single = colors.length === 1;
  const groupWidth = Math.min(slot * 0.9, columns * (single ? 140 : 78));
  const monthWidth = groupWidth / columns;
  const boxWidth = Math.max(6, Math.min(single ? 40 : 24, monthWidth * 0.55));
  const showMean = monthWidth >= 30;
  const showStatus = monthWidth >= 54;
  const nameChars = Math.max(4, Math.floor((slot * 0.95) / 5.6));
  const bottom =
    typeof yAxis.y === "number" && typeof yAxis.height === "number"
      ? yAxis.y + yAxis.height
      : Math.max(...(yScale.range?.() ?? [0]));
  const y = (value: string | number) => yScale(Number(value));
  return (
    <g>
      {colors.map((color) => (
        <text
          key={color}
          className="cmp-colour-label"
          role="button"
          tabIndex={0}
          aria-label={single ? `Show all colours` : `Focus ${color}`}
          x={center(color)}
          y={bottom + 16}
          textAnchor="middle"
          fontSize={10}
          fill="var(--foreground)"
          onClick={() => onColor(color)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onColor(color);
            }
          }}
        >
          {wrapName(color, nameChars).map((line, i) => (
            <tspan key={i} x={center(color)} dy={i ? 12 : 0}>
              {line}
            </tspan>
          ))}
          <title>
            {single ? `${color}: click to show all colours` : `${color}: click to focus`}
          </title>
        </text>
      ))}
      {baseline &&
        colors.map((color) => {
          const base = boxOf(baseline, color);
          const list = present(color);
          if (!base || list.length < 2) return null;
          const left = center(color) - (list.length * monthWidth) / 2;
          const top = Math.min(y(base.q1), y(base.q3));
          return (
            <g key={`base-${color}`} data-testid="comparison-baseline" aria-hidden>
              <rect
                x={left + 2}
                y={top}
                width={list.length * monthWidth - 4}
                height={Math.max(Math.abs(y(base.q3) - y(base.q1)), 2)}
                fill="var(--foreground)"
                fillOpacity={0.06}
                rx={3}
              />
              <line
                x1={left + 2}
                x2={left + list.length * monthWidth - 2}
                y1={y(base.median)}
                y2={y(base.median)}
                stroke="var(--foreground)"
                strokeOpacity={0.35}
                strokeDasharray="1 3"
              />
            </g>
          );
        })}
      {colors.flatMap((color) => {
        const list = present(color);
        const start = center(color) - (list.length * monthWidth) / 2;
        return list.map(({ month }, index) => {
          const box = boxOf(month, color)!;
          const cx = start + monthWidth * (index + 0.5);
          const name = monthParts(month)[0];
          const label = monthWidth >= 26 ? name : name.charAt(0);
          const colorStroke = TONE[box.tone];
          const top = Math.min(y(box.q1), y(box.q3));
          const height = Math.max(Math.abs(y(box.q3) - y(box.q1)), 2);
          const median = y(box.median);
          return (
            <g key={`${color}-${month}`} data-testid={`comparison-box-${month}-${color}-${orient}`}>
              {box.specs.map((spec) => (
                <line
                  key={spec.label}
                  x1={cx - monthWidth * 0.35}
                  x2={cx + monthWidth * 0.35}
                  y1={y(spec.value)}
                  y2={y(spec.value)}
                  stroke={TONE[spec.tone]}
                  strokeDasharray={spec.dash}
                  strokeWidth={1.5}
                />
              ))}
              <line
                x1={cx}
                x2={cx}
                y1={y(box.whisker_hi)}
                y2={top}
                stroke={colorStroke}
                strokeWidth={1.5}
              />
              <line
                x1={cx}
                x2={cx}
                y1={top + height}
                y2={y(box.whisker_lo)}
                stroke={colorStroke}
                strokeWidth={1.5}
              />
              {[box.whisker_hi, box.whisker_lo].map((value, i) => (
                <line
                  key={i}
                  x1={cx - boxWidth / 3}
                  x2={cx + boxWidth / 3}
                  y1={y(value)}
                  y2={y(value)}
                  stroke={colorStroke}
                  strokeWidth={1.5}
                />
              ))}
              <rect
                x={cx - boxWidth / 2}
                y={top}
                width={boxWidth}
                height={height}
                fill={colorStroke}
                fillOpacity={0.16}
                stroke={colorStroke}
                strokeWidth={1.5}
                rx={2}
              />
              <line
                x1={cx - boxWidth / 2}
                x2={cx + boxWidth / 2}
                y1={median}
                y2={median}
                stroke={colorStroke}
                strokeWidth={2}
              />
              {box.outliers.map((value, i) => (
                <circle key={i} cx={cx} cy={y(value)} r={2.5} fill={colorStroke} />
              ))}
              <text
                x={cx}
                y={bottom + 45}
                textAnchor="middle"
                fontSize={10}
                fontWeight={month === baseline ? 700 : 400}
                textDecoration={month === baseline ? "underline" : undefined}
                fill="var(--foreground)"
              >
                {label}
              </text>
              {showStatus && (
                <text x={cx} y={bottom + 61} textAnchor="middle" fontSize={10} fill={colorStroke}>
                  {box.statusText}
                </text>
              )}
              {showMean && (
                <text
                  data-testid="comparison-mean"
                  x={cx}
                  y={top - 8}
                  textAnchor="middle"
                  fontSize={monthWidth >= 40 ? 10 : 9}
                  fill="var(--foreground)"
                  stroke="var(--color-panel)"
                  strokeWidth={3}
                  paintOrder="stroke"
                  aria-label={`Mean ${displayMean(box.mean)}`}
                >
                  {displayMean(box.mean)}
                </text>
              )}
              <title>{`${monthName(month)}${month === baseline ? " (baseline)" : ""} ${color}: ${box.statusText}, mean ${displayMean(box.mean)}, n ${box.n}`}</title>
            </g>
          );
        });
      })}
      {markers.map((m) => {
        if (!colors.includes(m.color)) return null;
        const list = present(m.color);
        const width = Math.max(list.length, 1) * monthWidth;
        const left = center(m.color) - width / 2;
        const index = list.findIndex((d) => d.month === m.month);
        // A car whose own month has no box here is drawn across its colour group instead.
        const x = index >= 0 ? left + monthWidth * (index + 0.5) + boxWidth / 2 + 8 : left + width;
        const yy = y(m.value);
        return (
          <g key={m.id} data-testid="comparison-car-marker" className="cmp-marker">
            {index < 0 && (
              <line
                x1={left}
                x2={left + width}
                y1={yy}
                y2={yy}
                stroke={slotColor(m.n)}
                strokeDasharray="2 3"
                strokeWidth={1.25}
              />
            )}
            <path
              d={diamond(x, yy, 5.5)}
              fill={slotColor(m.n)}
              stroke="var(--color-panel)"
              strokeWidth={1.5}
            />
            <text
              x={x + 8}
              y={yy + 3.5}
              fontSize={10}
              fontWeight={600}
              fill="var(--foreground)"
              stroke="var(--color-panel)"
              strokeWidth={3}
              paintOrder="stroke"
            >
              {m.n}
            </text>
            <title>{`Car ${m.n} · ${m.label} · ${m.color} · ${monthName(m.month)}: mean CF ${displayMean(m.mean)}`}</title>
          </g>
        );
      })}
    </g>
  );
}

function DataTable({ table, label }: { table: TableData; label: string }) {
  return (
    <div className="cmp-table-wrap">
      <table className="cmp-table" aria-label={label}>
        <thead>
          <tr>
            {table.columns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className={j > 1 && cell != null && cell !== "" ? "num" : undefined}>
                  {cell ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Table toggle, CSV and PNG for one chart. The PNG redraws the chart's own SVG. */
function ChartTools({
  title,
  table,
  legend,
  chart,
  view,
  onView,
}: {
  title: string;
  table: TableData;
  legend?: Array<{ label: string; color: string }>;
  chart: React.RefObject<HTMLElement | null>;
  view: "chart" | "table";
  onView: (view: "chart" | "table") => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const png = async () => {
    const svg = chart.current?.querySelector<SVGSVGElement>("svg.recharts-surface");
    if (!svg) return setError("Show the chart first.");
    setBusy(true);
    setError("");
    try {
      download(await chartPng(svg, title, legend), fileName(title, "png"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The image could not be made.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="cmp-tools">
      <button
        type="button"
        className="cmp-tool"
        aria-pressed={view === "table"}
        onClick={() => onView(view === "table" ? "chart" : "table")}
      >
        <Table2 aria-hidden /> Table
      </button>
      <button
        type="button"
        className="cmp-tool"
        onClick={() =>
          download(new Blob([toCsv(table)], { type: "text/csv" }), fileName(title, "csv"))
        }
      >
        <FileDown aria-hidden /> CSV
      </button>
      <button
        type="button"
        className="cmp-tool"
        disabled={busy || view === "table"}
        onClick={() => void png()}
      >
        <ImageDown aria-hidden /> {busy ? "Saving…" : "PNG"}
      </button>
      {error && (
        <span className="cmp-tools__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

function OrientChart({
  model,
  orient,
  months,
  markers,
  hidden,
  baseline,
  layer,
  onColor,
}: {
  model: string;
  orient: Orient;
  months: MonthData[];
  markers: Marker[];
  hidden: string[];
  baseline: string | null;
  /** Film layer code; null for WaveScan CF. */
  layer: string | null;
  onColor: (color: string) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  const [view, setView] = useState<"chart" | "table">("chart");
  const entries = months.flatMap(({ month, data }) =>
    data.boxes
      .filter(
        (box) =>
          box.model_code === model &&
          box.orient === orient &&
          box.layer === layer &&
          !hidden.includes(box.color_name),
      )
      .map((box) => ({ month, box })),
  );
  const shown = markers.filter((m) => !hidden.includes(m.color));
  // Monthly Overview keeps the API's colour order (paint family order); so does this chart.
  const colors = colourOrder(months, [
    ...entries.map(({ box }) => box.color_name),
    ...shown.map((m) => m.color),
  ]);
  const boxes = entries.map(({ box }) => box);
  const domain = chartDomain(
    boxes,
    shown.map((m) => m.value),
  );
  const measure = layer ? `${layerLabel(layer)} thickness` : "CF";
  const title = `${model} ${orient} ${measure} by colour and month`;
  const limits = [...new Set(boxes.flatMap((b) => b.specs.map((s) => s.label)))];
  const table: TableData = {
    columns: [
      "Month",
      "Colour",
      "n",
      "Mean",
      "Median",
      "Q1",
      "Q3",
      "Whisker low",
      "Whisker high",
      "Limits",
      "Status",
    ],
    rows: [
      ...colors.flatMap((color) =>
        entries
          .filter((e) => e.box.color_name === color)
          .map(({ month, box }) => [
            `${monthName(month)}${month === baseline ? " (baseline)" : ""}`,
            color,
            box.n,
            box.mean,
            box.median,
            box.q1,
            box.q3,
            box.whisker_lo,
            box.whisker_hi,
            box.specs.map((sp) => `${sp.label} ${sp.value}`).join("; "),
            box.statusText,
          ]),
      ),
      ...shown.map((m) => [
        `Car ${m.n} · ${m.label} (${monthName(m.month)})`,
        m.color,
        null,
        m.mean,
      ]),
    ],
  };
  return (
    <section className="cmp-chart" aria-label={`${model} ${orient}`} ref={ref}>
      <div className="cmp-chart__head">
        <h3>
          {model} · {orient}
        </h3>
        <p>
          {limits.length > 0 && `Dashed: ${limits.join(" / ")}`}
          {shown.length > 0 && (
            <>
              {" · "}
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                <path d={diamond(5, 5, 4.5)} fill="currentColor" />
              </svg>{" "}
              car mean
            </>
          )}
          {baseline && ` · Band: ${monthName(baseline)} Q1–Q3`}
        </p>
        {colors.length > 0 && (
          <ChartTools title={title} table={table} chart={ref} view={view} onView={setView} />
        )}
      </div>
      {!colors.length ? (
        <p className="cmp-chart__empty">
          There are no active {orient} readings for this selection.
        </p>
      ) : view === "table" ? (
        <DataTable table={table} label={title} />
      ) : (
        <div className="h-80" role="img" aria-label={title}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={colors.map((color_name) => ({ color_name }))}
              margin={{ top: 24, right: 22, bottom: 12, left: 8 }}
            >
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="color_name"
                interval={0}
                height={80}
                scale="band"
                tick={false}
                tickLine={false}
                axisLine={{ stroke: "var(--border)" }}
              />
              <YAxis
                domain={domain}
                ticks={integerTicks(domain)}
                interval={0}
                allowDecimals={false}
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                label={{
                  value: layer ? "µm" : "CF",
                  angle: -90,
                  position: "insideLeft",
                  fill: "var(--muted-foreground)",
                }}
              />
              <Customized
                component={(props: Axes) => (
                  <GroupedLayer
                    {...props}
                    colors={colors}
                    months={months}
                    entries={entries}
                    markers={shown}
                    orient={orient}
                    baseline={baseline}
                    onColor={onColor}
                  />
                )}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

/** The API's plant colour order (paint family order, as Monthly Overview), limited to `present`. */
function colourOrder(months: MonthData[], present: string[]) {
  const order = [...new Set([...months.flatMap(({ data }) => data.colors), ...present])];
  return order.filter((c) => present.includes(c));
}

type LineBy = "car" | "location";

const polygon = (x: number, y: number, r: number, sides: number, turn = -Math.PI / 2) =>
  Array.from({ length: sides }, (_, i) => {
    const a = turn + (i * 2 * Math.PI) / sides;
    return `${x + r * Math.cos(a)},${y + r * Math.sin(a)}`;
  }).join(" ");

/** Point shape per body panel: colour carries the car, shape carries where on the body. */
function PanelMark({
  panel,
  x,
  y,
  r = 4,
  fill,
  edge,
}: {
  panel: Panel;
  x: number;
  y: number;
  r?: number;
  fill: string;
  edge?: string;
}) {
  const common = { fill, stroke: edge, strokeWidth: edge ? 1.5 : 0 };
  const arm = r * 0.42;
  switch (panel) {
    case "Hood":
      return <circle cx={x} cy={y} r={r} {...common} />;
    case "Roof":
      return (
        <rect x={x - r * 0.88} y={y - r * 0.88} width={r * 1.76} height={r * 1.76} {...common} />
      );
    case "Fender":
      return <polygon points={polygon(x, y + r * 0.15, r * 1.2, 3)} {...common} />;
    case "Door":
      return <polygon points={polygon(x, y, r * 1.2, 4)} {...common} />;
    case "Pillar":
      return (
        <polygon
          points={`${x - arm},${y - r} ${x + arm},${y - r} ${x + arm},${y - arm} ${x + r},${y - arm} ${x + r},${y + arm} ${x + arm},${y + arm} ${x + arm},${y + r} ${x - arm},${y + r} ${x - arm},${y + arm} ${x - r},${y + arm} ${x - r},${y - arm} ${x - arm},${y - arm}`}
          {...common}
        />
      );
    case "Box":
      return <polygon points={polygon(x, y - r * 0.15, r * 1.2, 3, Math.PI / 2)} {...common} />;
    case "Gate":
      return <polygon points={polygon(x, y, r * 1.08, 6, 0)} {...common} />;
    case "Bumper":
      return <polygon points={polygon(x, y, r * 1.1, 5)} {...common} />;
    default:
      return <circle cx={x} cy={y} r={r * 0.85} fill="none" stroke={fill} strokeWidth={1.75} />;
  }
}
type LegendEntry = {
  key: string;
  label: string;
  color?: string;
  dash?: string;
  panel?: Panel;
  count: number;
};

function SpectrumPanel({
  orient,
  list,
  metrics,
  by,
  cars,
  slotOf,
  focus,
  kind,
  onToggle,
  hover,
  setHover,
}: {
  orient: Orient;
  list: Trace[];
  metrics: Metric[];
  by: LineBy;
  cars: Car[];
  slotOf: (id: string) => number;
  /** Highlighted locations (location mode); empty means all at full strength. */
  focus: string[];
  kind: string;
  onToggle: (key: string) => void;
  hover: string | null;
  setHover: (key: string | null) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  const [view, setView] = useState<"chart" | "table">("chart");
  const rows = spectrumRows(list, metrics);
  const byKey = new Map(list.map((t) => [t.key, t]));
  const entity = (t: Trace) => (by === "car" ? t.vehicle_id : t.location);
  const styles = locationStyles(list);
  const colorOf = (t: Trace) =>
    slotColor(by === "car" ? slotOf(t.vehicle_id) : (styles.get(t.location)?.slot ?? 1));
  const dashOf = (t: Trace) => {
    const locationDash = styles.get(t.location)?.dash;
    const carDash = [undefined, "7 4", "2 3", "10 3 2 3", "12 5", "4 3 1 3", "1 4", "8 2"][
      slotOf(t.vehicle_id) - 1
    ];
    return by === "car"
      ? locationDash
      : locationDash
        ? `${locationDash} ${carDash ?? "12 0"}`
        : carDash;
  };
  const emphasised = (t: Trace) =>
    hover ? entity(t) === hover : by === "car" || !focus.length || focus.includes(t.location);
  const panels = PANELS.filter((p) => list.some((t) => t.panel === p));
  const legend: LegendEntry[] =
    by === "car"
      ? cars
          .filter((c) => list.some((t) => t.vehicle_id === c.vehicle_id))
          .map((c) => ({
            key: c.vehicle_id,
            label: `${slotOf(c.vehicle_id)} · ${carLabel(c)} · ${c.model} · ${carContext(c)}`,
            color: slotColor(slotOf(c.vehicle_id)),
            count: list.filter((t) => t.vehicle_id === c.vehicle_id).length,
          }))
      : panels.flatMap((panel) =>
          [
            ...new Map(
              list.filter((t) => t.panel === panel).map((t) => [t.location, t] as const),
            ).values(),
          ]
            .sort((a, b) => a.point_no - b.point_no)
            .map((t) => ({
              key: t.location,
              label: t.locationLabel,
              color: colorOf(t),
              dash: dashOf(t),
              panel,
              count: list.filter((x) => x.location === t.location).length,
            })),
        );
  // Context lines first so emphasised ones paint on top.
  const ordered = [...list].sort((a, b) => Number(emphasised(a)) - Number(emphasised(b)));
  const carOf = (id: string) => cars.find((c) => c.vehicle_id === id);
  const title = `${orient} ${kind}`;
  const table: TableData = {
    columns: ["Car", "Location", "Panel", ...metrics.map(metricLabel)],
    rows: list.map((t) => {
      const car = carOf(t.vehicle_id);
      return [
        `${slotOf(t.vehicle_id)} · ${car ? carLabel(car) : ""}`,
        t.locationLabel,
        t.panel,
        ...metrics.map((m) => t.values[m] ?? null),
      ];
    }),
  };
  const pngLegend = legend.filter((e) => e.color).map((e) => ({ label: e.label, color: e.color! }));
  return (
    <section className="cmp-chart" aria-label={title} ref={ref}>
      <div className="cmp-chart__head">
        <h3>{orient}</h3>
        <p>
          {list.length} measured {list.length === 1 ? "row" : "rows"}, one raw line each
        </p>
        <ChartTools
          title={title}
          table={table}
          legend={pngLegend}
          chart={ref}
          view={view}
          onView={setView}
        />
      </div>
      {view === "table" ? (
        <DataTable table={table} label={title} />
      ) : (
        <div className="cmp-spectrum">
          <div className="cmp-legend-col">
            <ul className="cmp-legend" aria-label={`${orient} lines`}>
              {legend.map((e, i) => (
                <li key={e.key}>
                  {e.panel && e.panel !== legend[i - 1]?.panel && (
                    <span className="cmp-legend__group">
                      <svg width="12" height="12" aria-hidden>
                        <PanelMark panel={e.panel} x={6} y={6} r={4} fill="var(--foreground)" />
                      </svg>
                      {e.panel}
                    </span>
                  )}
                  <button
                    type="button"
                    aria-pressed={by === "location" ? focus.includes(e.key) : undefined}
                    title={
                      by === "location"
                        ? focus.includes(e.key)
                          ? "Stop highlighting"
                          : "Highlight this location"
                        : "Hide this car"
                    }
                    data-dim={hover && hover !== e.key ? true : undefined}
                    onMouseEnter={() => setHover(e.key)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(e.key)}
                    onBlur={() => setHover(null)}
                    onClick={() => onToggle(e.key)}
                  >
                    <svg width="18" height="8" aria-hidden>
                      <line
                        x1="1"
                        x2="17"
                        y1="4"
                        y2="4"
                        stroke={e.color ?? "var(--muted-foreground)"}
                        strokeWidth={2.5}
                        strokeDasharray={e.dash}
                      />
                    </svg>
                    <span className="cmp-legend__label">{e.label}</span>
                    {e.count > 1 && <span className="cmp-legend__count num">{e.count}</span>}
                  </button>
                </li>
              ))}
            </ul>
            {by === "car" && (
              <div className="cmp-shapes" aria-label="Point shape by panel">
                {panels.map((p) => (
                  <span key={p}>
                    <svg width="12" height="12" aria-hidden>
                      <PanelMark panel={p} x={6} y={6} r={4} fill="var(--foreground)" />
                    </svg>
                    {p}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div
            className="h-80 min-w-0"
            role="img"
            aria-label={`${orient} spectrum, ${list.length} lines`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 12, right: 18, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="var(--border)" strokeOpacity={0.6} vertical={false} />
                <XAxis
                  dataKey="metric"
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  axisLine={{ stroke: "var(--border)" }}
                  tickLine={false}
                  padding={{ left: 12, right: 12 }}
                />
                <YAxis
                  domain={[0, "auto"]}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  axisLine={false}
                  tickLine={false}
                  width={40}
                />
                <Tooltip
                  cursor={{ stroke: "var(--border)" }}
                  isAnimationActive={false}
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    const hits = payload
                      .filter((p) => typeof p.value === "number")
                      .map((p) => ({ t: byKey.get(String(p.dataKey))!, v: p.value as number }))
                      .filter(({ t }) => t && emphasised(t))
                      .sort((a, b) => b.v - a.v);
                    return (
                      <div className="cmp-tip">
                        <b>{label}</b>
                        {hits.length === 0 && <span>Hover a line to read its values.</span>}
                        {hits.slice(0, 8).map(({ t, v }) => (
                          <span key={t.key} className="cmp-tip__row">
                            <svg width="12" height="12" aria-hidden>
                              <PanelMark panel={t.panel} x={6} y={6} r={4} fill={colorOf(t)} />
                            </svg>
                            <span className="cmp-tip__identity">
                              <span>{`${slotOf(t.vehicle_id)} · ${t.locationLabel}`}</span>
                              <span>
                                {carOf(t.vehicle_id) ? carContext(carOf(t.vehicle_id)!) : ""}
                              </span>
                            </span>
                            <b className="num">{v}</b>
                          </span>
                        ))}
                        {hits.length > 8 && <span>+{hits.length - 8} more</span>}
                      </div>
                    );
                  }}
                />
                {ordered.map((t) => {
                  const on = emphasised(t);
                  const hot = hover !== null && entity(t) === hover;
                  return (
                    <Line
                      key={t.key}
                      dataKey={t.key}
                      type="monotone"
                      stroke={colorOf(t)}
                      strokeDasharray={dashOf(t)}
                      strokeWidth={hot ? 2.75 : on ? 1.75 : 1}
                      strokeOpacity={hover ? (hot ? 1 : 0.1) : on ? 0.95 : 0.12}
                      dot={
                        on && (!hover || hot)
                          ? (p: { cx?: number; cy?: number; index?: number }) =>
                              p.cx == null || p.cy == null ? (
                                <g key={`${t.key}-${p.index}`} />
                              ) : (
                                <PanelMark
                                  key={`${t.key}-${p.index}`}
                                  panel={t.panel}
                                  x={p.cx}
                                  y={p.cy}
                                  fill={colorOf(t)}
                                />
                              )
                          : false
                      }
                      activeDot={
                        on
                          ? (p: { cx?: number; cy?: number }) => (
                              <PanelMark
                                panel={t.panel}
                                x={p.cx ?? 0}
                                y={p.cy ?? 0}
                                r={5.5}
                                fill={colorOf(t)}
                                edge="var(--color-panel)"
                              />
                            )
                          : false
                      }
                      connectNulls={false}
                      isAnimationActive={false}
                      onMouseEnter={() => setHover(entity(t))}
                      onMouseLeave={() => setHover(null)}
                      onClick={() => by === "location" && onToggle(t.location)}
                    />
                  );
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </section>
  );
}

function DotProfile({
  orient,
  list,
  metric,
  cars,
  slotOf,
}: {
  orient: Orient;
  list: Trace[];
  metric: Metric;
  cars: Car[];
  slotOf: (id: string) => number;
}) {
  const ref = useRef<HTMLElement>(null);
  const [view, setView] = useState<"chart" | "table">("chart");
  const { rows, keys } = profileRows(
    list,
    metric,
    cars.map((c) => c.vehicle_id),
  );
  if (!rows.length)
    return (
      <p className="cmp-chart__empty">No {metricLabel(metric)} readings for the selected cars.</p>
    );
  const label = (key: string) => {
    const car = cars.find((c) => key.startsWith(`${c.vehicle_id}#`))!;
    return `${slotOf(car.vehicle_id)} · ${carLabel(car)} · ${carContext(car)}`;
  };
  const title = `${orient} ${metricLabel(metric)} by location`;
  const table: TableData = {
    columns: ["Location", "Car", metricLabel(metric)],
    rows: rows.flatMap((row) =>
      keys.filter((k) => row[k] != null).map((k) => [row.location, label(k), row[k]]),
    ),
  };
  const used = [...new Set(keys.map((k) => k.slice(0, k.indexOf("#"))))];
  return (
    <section className="cmp-chart" aria-label={`${orient} location profile`} ref={ref}>
      <div className="cmp-chart__head">
        <h3>
          {orient} · {metricLabel(metric)}
        </h3>
        <p>Raw readings by location. Locations nobody measured are left out.</p>
        <ChartTools
          title={title}
          table={table}
          legend={used.map((id) => ({ label: label(`${id}#0`), color: slotColor(slotOf(id)) }))}
          chart={ref}
          view={view}
          onView={setView}
        />
      </div>
      {view === "table" ? (
        <DataTable table={table} label={title} />
      ) : (
        <div className="h-80" role="img" aria-label={`${metricLabel(metric)} by location`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 16, right: 22, bottom: 8, left: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeOpacity={0.6} vertical={false} />
              <XAxis
                dataKey="location"
                // Fits the panel: past ~40 locations, label every other one (all stay plotted).
                interval={rows.length > 40 ? Math.ceil(rows.length / 40) - 1 : 0}
                angle={-60}
                textAnchor="end"
                height={64}
                tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                axisLine={{ stroke: "var(--border)" }}
                tickLine={false}
              />
              <YAxis
                domain={["auto", "auto"]}
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                axisLine={false}
                tickLine={false}
                width={44}
              />
              <Tooltip
                cursor={{ stroke: "var(--border)" }}
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
              />
              {keys.map((key) => {
                const n = slotOf(key.slice(0, key.indexOf("#")));
                // A car's repeat rows at one location are dots only; the first row is its line.
                const repeat = !key.endsWith("#0");
                return (
                  <Line
                    key={key}
                    dataKey={key}
                    name={label(key)}
                    stroke={slotColor(n)}
                    strokeWidth={2}
                    strokeOpacity={repeat ? 0 : 1}
                    dot={{ r: 4, fill: slotColor(n), strokeWidth: 0 }}
                    activeDot={{ r: 5 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

function ProfileSection({
  code,
  domain,
  cars,
  filmLayer,
  onFilmLayerChange,
}: {
  code: string;
  domain: Domain;
  cars: Car[];
  filmLayer: Metric;
  onFilmLayerChange: (metric: Metric) => void;
}) {
  const defaults: Metric[] = domain === "FILMTHICKNESS" ? ["ecoat"] : SPECTRUM[domain];
  const [picked, setPicked] = useState<Metric[]>(defaults);
  const [by, setBy] = useState<LineBy>("location");
  const [excluded, setExcluded] = useState<string[]>([]);
  const [focus, setFocus] = useState<string[]>([]);
  const [hover, setHover] = useState<string | null>(null);
  const [hiddenPanels, setHiddenPanels] = useState<Panel[]>([]);
  const selected =
    domain === "FILMTHICKNESS"
      ? [filmLayer]
      : METRIC_ORDER[domain].filter((m) => picked.includes(m));
  const ids = cars.map((c) => c.vehicle_id);
  const carModels = [
    ...new Set(cars.map((car) => car.model).filter((m): m is string => Boolean(m))),
  ];
  const jobs = carModels.flatMap((carModel) =>
    selected.map((metric) => ({ model: carModel, metric })),
  );
  const queries = useQueries({
    queries: jobs.map(({ model, metric }) =>
      comparisonPointsOptions(code, {
        domain,
        model,
        metric,
        vehicle_id: cars.filter((car) => car.model === model).map((car) => car.vehicle_id),
      }),
    ),
  });
  const pending = queries.some((q) => q.isPending);
  const failed = queries.find((q) => q.isError);
  const included = ids.filter((id) => !excluded.includes(id));
  const all =
    pending || failed
      ? []
      : carModels
          .flatMap((model) =>
            traces(
              queries.flatMap((q, i) =>
                jobs[i].model === model ? [{ metric: jobs[i].metric, points: q.data! }] : [],
              ),
            ),
          )
          .map((trace) => {
            const carModel = cars.find((car) => car.vehicle_id === trace.vehicle_id)?.model;
            return carModels.length > 1
              ? {
                  ...trace,
                  key: `${carModel}|${trace.key}`,
                  location: `${carModel}|${trace.location}`,
                  locationLabel: `${carModel} · ${trace.locationLabel}`,
                }
              : trace;
          })
          .filter((t) => included.includes(t.vehicle_id));
  // Body panels on these cars; unticking one thins a busy chart (Film has ~100 locations).
  const bodyPanels = PANELS.filter((p) => all.some((t) => t.panel === p));
  const list = all.filter((t) => !hiddenPanels.includes(t.panel));
  const slotOf = (id: string) => ids.indexOf(id) + 1;
  const toggleCar = (id: string) =>
    setExcluded(excluded.includes(id) ? excluded.filter((x) => x !== id) : [...excluded, id]);
  const toggleFocus = (location: string) =>
    setFocus(focus.includes(location) ? focus.filter((l) => l !== location) : [...focus, location]);
  const isSpectrum = selected.length > 1;
  const isDefault =
    selected.length === defaults.length && defaults.every((m) => selected.includes(m));
  const kind = domain === "WAVESCAN" ? "structure spectrum" : "layer profile";
  const panels = (["Horizontal", "Vertical"] as const)
    .map((orient) => ({ orient, list: list.filter((t) => t.orient === orient) }))
    .filter((p) => p.list.length > 0);
  return (
    <section className="cmp-profile" aria-label="Car profile">
      <header className="cmp-analysis-heading">
        <h3>Inspect car readings</h3>
        <p className="cmp-hint">
          {domain === "WAVESCAN"
            ? "Choose measurements, then highlight a location to follow it across cars."
            : "Choose one paint layer. Each car has a consistent colour across its measured locations."}
        </p>
      </header>
      <div className="cmp-profile__controls">
        <Chips
          label={domain === "FILMTHICKNESS" ? "Paint layer" : "Metrics"}
          options={METRIC_ORDER[domain]}
          selected={selected}
          render={metricLabel}
          onChange={(next) =>
            domain === "FILMTHICKNESS"
              ? onFilmLayerChange(next.find((m) => !selected.includes(m)) ?? selected[0])
              : setPicked(next)
          }
        />
        {!isDefault && (
          <button
            type="button"
            className="cmp-link"
            onClick={() =>
              domain === "FILMTHICKNESS" ? onFilmLayerChange("ecoat") : setPicked(defaults)
            }
          >
            {domain === "WAVESCAN" ? "Reset to du–We" : "Reset to E-coat"}
          </button>
        )}
        {isSpectrum && (
          <div className="cmp-chips" role="group" aria-label="Colour lines by">
            <span className="cmp-field-label">Colour by</span>
            {(["car", "location"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className="cmp-chip"
                aria-pressed={by === value}
                onClick={() => {
                  setBy(value);
                  setFocus([]);
                }}
              >
                {value === "car" ? "Car" : "Location"}
              </button>
            ))}
          </div>
        )}
        {bodyPanels.length > 1 && (
          <Chips
            label="Panels"
            options={bodyPanels}
            selected={bodyPanels.filter((p) => !hiddenPanels.includes(p))}
            onChange={(shown) => setHiddenPanels(bodyPanels.filter((p) => !shown.includes(p)))}
          />
        )}
        {cars.length > 1 && (
          <Chips
            label="Cars"
            options={ids}
            selected={included}
            render={(id) =>
              `${slotOf(id)} · ${carLabel(cars[slotOf(id) - 1])} · ${cars[slotOf(id) - 1].model} · ${carContext(cars[slotOf(id) - 1])}`
            }
            swatch={(id) => slotColor(slotOf(id))}
            onChange={(next) => setExcluded(ids.filter((id) => !next.includes(id)))}
          />
        )}
      </div>
      {carModels.length > 1 && (
        <p className="cmp-hint">
          Comparing {carModels.join(" / ")}. Each model keeps its own point identities; matching
          walk numbers do not imply matching locations.
        </p>
      )}
      {isSpectrum && by === "location" && (
        <div className="cmp-car-patterns" aria-label="Car line patterns">
          {cars.map((car) => (
            <span key={car.vehicle_id}>
              <svg width="32" height="12" aria-hidden="true">
                <line
                  x1="0"
                  x2="32"
                  y1="6"
                  y2="6"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeDasharray={
                    [undefined, "7 4", "2 3", "10 3 2 3", "12 5", "4 3 1 3", "1 4", "8 2"][
                      slotOf(car.vehicle_id) - 1
                    ]
                  }
                />
              </svg>
              {slotOf(car.vehicle_id)} · {carLabel(car)} · {car.model} · {carContext(car)}
            </span>
          ))}
        </div>
      )}
      {selected.length === 0 ? (
        <p className="cmp-chart__empty">Pick at least one metric.</p>
      ) : pending ? (
        <LoadingState>Loading car readings…</LoadingState>
      ) : failed ? (
        <ApiErrorState error={failed.error!} retry={() => void failed.refetch()} />
      ) : panels.length === 0 ? (
        <p className="cmp-chart__empty">The selected cars have no readings for these metrics.</p>
      ) : !isSpectrum ? (
        // One metric: x = location, so Horizontal and Vertical panels get their own chart.
        panels.map(({ orient, list: rows }) => (
          <DotProfile
            key={orient}
            orient={orient}
            list={rows}
            metric={selected[0]}
            cars={cars.filter((c) => included.includes(c.vehicle_id))}
            slotOf={slotOf}
          />
        ))
      ) : (
        <>
          {by === "location" && (
            <p className="cmp-hint">
              Each location has its own colour; the point shape shows its panel. Click locations to
              highlight them{focus.length > 0 && " "}
              {focus.length > 0 && (
                <button type="button" className="cmp-link" onClick={() => setFocus([])}>
                  Clear highlight
                </button>
              )}
            </p>
          )}
          {panels.map(({ orient, list: rows }) => (
            <SpectrumPanel
              key={orient}
              orient={orient}
              list={rows}
              metrics={selected}
              by={by}
              cars={cars}
              slotOf={slotOf}
              focus={focus}
              kind={kind}
              onToggle={by === "car" ? toggleCar : toggleFocus}
              hover={hover}
              setHover={setHover}
            />
          ))}
        </>
      )}
    </section>
  );
}

type Filters = { domain: Domain; model: string; colors: string[]; weeks: number[]; q: string };
const deckQuery = (month: string, { domain, model, colors, weeks, q }: Filters) => ({
  domain,
  month: [month],
  model,
  color: colors.length ? colors : undefined,
  period: weeks.length ? weeks.map((w) => `${month}-W${w}`) : undefined,
  q: q || undefined,
});

function CarCard({
  car,
  onBench,
  onAdd,
  onLift,
  onDrop,
}: {
  car: Car;
  onBench: boolean;
  onAdd: (card: Card) => void;
  onLift: (card: Card | null) => void;
  onDrop: () => void;
}) {
  const card: Card = { kind: "car", car };
  const label = carLabel(car);
  return (
    <li>
      <article
        className="cmp-car"
        data-on={onBench || undefined}
        data-incomplete={car.incomplete || undefined}
        draggable
        onDragStart={(e) => lift(e, label, () => onLift(card))}
        onDragEnd={() => onDrop()}
      >
        <GripVertical className="cmp-grip" aria-hidden />
        <div className="cmp-car__body">
          <span className="cmp-car__serial">{label}</span>
          <span className="cmp-car__meta">
            {car.color ?? "No colour"} · {shortDate(car.measured_date, car.date_is_month_only)}
          </span>
          {car.incomplete && (
            <span className="cmp-car__flag">
              {car.point_count}/{car.expected_point_count ?? "?"} points
            </span>
          )}
        </div>
        <button
          type="button"
          className="cmp-icon-btn"
          aria-label={onBench ? `${label} is on the bench` : `Add ${label} to bench`}
          disabled={onBench}
          onClick={() => onAdd(card)}
        >
          <Plus aria-hidden />
        </button>
      </article>
    </li>
  );
}

function lift(e: DragEvent, label: string, then: () => void) {
  e.dataTransfer.effectAllowed = "copyMove";
  e.dataTransfer.setData("text/plain", label); // Firefox starts no drag without data
  then();
}

function MonthColumn({
  code,
  month,
  filters,
  layer,
  bench,
  onAdd,
  onLift,
}: {
  code: string;
  month: string;
  filters: Filters;
  layer: string;
  bench: Bench;
  onAdd: (card: Card) => void;
  onLift: (card: Card | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pages, setPages] = useState(1);
  const { domain, model, colors } = filters;
  const query = deckQuery(month, filters);
  const filterKey = JSON.stringify(query);
  useEffect(() => setPages(1), [filterKey]);
  const count = useQuery({
    ...comparisonVehiclesOptions(code, { ...query, limit: 1, offset: 0 }),
    enabled: !!model,
  });
  const overview = useQuery(monthBoxesOptions(code, domain, month));
  const pageQueries = useQueries({
    queries: open
      ? Array.from({ length: pages }, (_, i) => ({
          ...comparisonVehiclesOptions(code, { ...query, limit: PAGE, offset: PAGE * i }),
          enabled: !!model,
        }))
      : [],
  });
  const cars = pageQueries.flatMap((p) => p.data?.items ?? []);
  const total = count.data?.page.total;
  const boxes = (overview.data?.boxes ?? []).filter(
    (b) =>
      b.model_code === model &&
      (domain === "WAVESCAN" || b.layer === layer) &&
      (!colors.length || colors.includes(b.color_name)),
  );
  const worst = TONE_RANK.map((tone) => boxes.find((b) => b.tone === tone)).find(Boolean);
  const [name, year] = monthParts(month);
  const card: Card = { kind: "month", month, model, domain };
  const onBench =
    bench.domain === domain &&
    bench.months.some((key) => monthValue(key) === month && monthModel(bench, key) === model);
  const loadingMore = pageQueries.some((p) => p.isFetching);
  const pageError = pageQueries.find((p) => p.isError);
  return (
    <div className="cmp-col" role="listitem">
      <article
        className="cmp-month"
        data-status={worst ? STATUS_ATTR[worst.tone] : undefined}
        data-on={onBench || undefined}
        draggable={!!model}
        onDragStart={(e) => lift(e, `${name} ${year}`, () => onLift(card))}
        onDragEnd={() => onLift(null)}
        aria-label={`${name} ${year}`}
      >
        <GripVertical className="cmp-grip" aria-hidden />
        <header className="cmp-month__head">
          <span className="cmp-month__name">{name}</span>
          <span className="cmp-month__year">{year}</span>
          {worst && <span className="cmp-status">{worst.statusText}</span>}
        </header>
        <p className="cmp-month__count">
          <span className="num">{count.isPending ? "…" : (total ?? 0)}</span> cars
        </p>
        <div
          className="cmp-pips"
          role="img"
          aria-label={
            boxes.length
              ? `${boxes.length} boxes: ${boxes.filter((b) => b.tone === "critical").length} fail, ${boxes.filter((b) => b.tone === "caution").length} acceptable`
              : "No boxes for this filter"
          }
        >
          {boxes.slice(0, 24).map((b) => (
            <span
              key={`${b.color_name}-${b.orient}`}
              className="cmp-pip"
              style={{ background: TONE[b.tone] }}
              title={`${b.color_name} ${b.orient}: ${b.statusText}, mean ${displayMean(b.mean)}`}
            />
          ))}
        </div>
        <div className="cmp-month__actions">
          <button
            type="button"
            className="cmp-btn cmp-btn--primary"
            disabled={onBench}
            onClick={() => onAdd(card)}
            aria-label={
              onBench ? `${name} ${year} is on the bench` : `Add ${name} ${year} to bench`
            }
          >
            {onBench ? (
              "On bench"
            ) : (
              <>
                <Plus aria-hidden /> Month
              </>
            )}
          </button>
          <button
            type="button"
            className="cmp-btn"
            aria-expanded={open}
            aria-controls={`cmp-cars-${month}`}
            onClick={() => setOpen(!open)}
            disabled={!total}
          >
            Cars <ChevronDown aria-hidden className="cmp-chev" />
          </button>
        </div>
      </article>
      {open && (
        <div className="cmp-cars" id={`cmp-cars-${month}`}>
          {pageQueries[0]?.isPending ? (
            <p className="cmp-cars__note">Loading cars…</p>
          ) : (
            byWeek(cars).map(({ week, cars: group }) => (
              <section key={week} aria-label={weekText(week)}>
                <h4 className="cmp-week">
                  {weekText(week)} <span>{group.length}</span>
                </h4>
                <ul>
                  {group.map((car) => (
                    <CarCard
                      key={car.vehicle_id}
                      car={car}
                      onBench={bench.cars.some((c) => c.vehicle_id === car.vehicle_id)}
                      onAdd={onAdd}
                      onLift={onLift}
                      onDrop={() => onLift(null)}
                    />
                  ))}
                </ul>
              </section>
            ))
          )}
          {pageError && (
            <ApiErrorState error={pageError.error!} retry={() => void pageError.refetch()} />
          )}
          {total != null && cars.length > 0 && cars.length < total && (
            <button
              type="button"
              className="cmp-btn cmp-more"
              disabled={loadingMore}
              onClick={() => setPages(pages + 1)}
            >
              {loadingMore ? "Loading…" : `Show more (${total - cars.length} left)`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Chips<T extends string | number>({
  label,
  options,
  selected,
  render,
  swatch,
  onChange,
}: {
  label: string;
  options: readonly T[];
  selected: T[];
  render?: (value: T) => string;
  swatch?: (value: T) => string;
  onChange: (next: T[]) => void;
}) {
  return (
    <div className="cmp-chips" role="group" aria-label={label}>
      <span className="cmp-field-label">{label}</span>
      {options.map((value) => {
        const on = selected.includes(value);
        return (
          <button
            key={value}
            type="button"
            className="cmp-chip"
            aria-pressed={on}
            onClick={() =>
              onChange(on ? selected.filter((v) => v !== value) : [...selected, value])
            }
          >
            {swatch && <i className="cmp-swatch" style={{ background: swatch(value) }} />}
            {on && <Check aria-hidden="true" className="cmp-selection-check" />}
            {render ? render(value) : value}
          </button>
        );
      })}
    </div>
  );
}

export function PlantComparison({
  code,
  bench,
  onBenchChange,
  shared,
  domain,
  onDomainChange,
}: {
  code: string;
  bench: Bench;
  onBenchChange: (bench: Bench) => void;
  shared?: SharedBench;
  /** Deck measurement; the left panel's Paint Functional switch shows the same value. */
  domain: Domain;
  onDomainChange: (domain: Domain) => void;
}) {
  const router = useRouter();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState("");
  const [switchingModel, setSwitchingModel] = useState(false);
  const modelSwitchId = useRef(0);
  const benchRef = useRef(bench);
  benchRef.current = bench;
  const [colors, setColors] = useState<string[]>([]);
  const [weeks, setWeeks] = useState<number[]>([]);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [dragging, setDragging] = useState<Card | null>(null);
  const [slotDrag, setSlotDrag] = useState<{ kind: SlotKind; key: string } | null>(null);
  const [notice, setNotice] = useState<{
    text: string;
    undo?: Bench;
    pickOnUndo?: string;
    warn?: boolean;
  } | null>(null);
  const [hidden, setHidden] = useState<string[]>([]);
  const [layer, setLayer] = useState<string>("ECOAT"); // as Monthly Overview's film default
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);
  // Opened from a shared link: rebuild the bench once, re-reading cars by ID, then drop the param.
  const sharedKey = shared ? JSON.stringify(shared) : "";
  useEffect(() => {
    if (!shared) return;
    let live = true;
    (async () => {
      let cars: Car[] = [];
      try {
        if (shared.cars.length) {
          const groups = [
            ...new Set(shared.cars.map((id) => shared.carModels?.[id] ?? shared.model)),
          ];
          const results = await Promise.all(
            groups.map((model) =>
              queryClient.fetchQuery(
                comparisonPointsOptions(code, {
                  domain: shared.domain,
                  model,
                  metric: shared.domain === "WAVESCAN" ? "cf" : "ecoat",
                  vehicle_id: shared.cars.filter(
                    (id) => (shared.carModels?.[id] ?? shared.model) === model,
                  ),
                }),
              ),
            ),
          );
          const found = results.flatMap((result) => result.columns);
          cars = shared.cars.map((id) => found.find((car) => car.vehicle_id === id)!);
        }
        if (!live) return;
        onBenchChange({ ...shared, cars });
        setNotice({ text: "Opened the shared comparison." });
      } catch {
        if (!live) return;
        onBenchChange({ ...shared, cars: [] });
        setNotice({
          text: "Opened the shared months. The shared cars are no longer available.",
          warn: true,
        });
      }
      void navigate({
        to: ".",
        // One navigation: drop the link and show the shared measurement in both switches.
        search: (prev: Record<string, unknown>) => ({
          ...prev,
          compare: undefined,
          paint: shared.domain === "FILMTHICKNESS" ? ("film" as const) : undefined,
        }),
        replace: true,
      });
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per shared link
  }, [sharedKey]);

  const probe = useQuery(comparisonVehiclesOptions(code, { domain, limit: 1, offset: 0 }));
  const shelf = [...(probe.data?.available_months ?? [])].sort((a, b) => b.localeCompare(a));
  const models = useQuery({
    ...comparisonVehiclesOptions(code, { domain, month: shelf, limit: 1, offset: 0 }),
    enabled: shelf.length > 0,
  });
  const modelOptions = models.data?.model_options ?? [];
  const model = picked || (bench.domain === domain ? bench.model : null) || modelOptions[0] || "";
  const options = useQuery({
    ...comparisonVehiclesOptions(code, {
      domain,
      month: shelf,
      model,
      limit: 1,
      offset: 0,
    }),
    enabled: shelf.length > 0 && !!model,
  });
  // The newest month's overview gives paint family order (shared cache with its deck card).
  const familyOrder = useQuery({
    ...monthBoxesOptions(code, domain, shelf[0] ?? ""),
    enabled: !!shelf[0],
  }).data?.colors;
  const rank = (c: string) => familyOrder?.indexOf(c) ?? -1;
  const colorOptions = [...(options.data?.color_options ?? [])].sort(
    (a, b) => (rank(a) < 0 ? 999 : rank(a)) - (rank(b) < 0 ? 999 : rank(b)),
  );
  const filters = { domain, model, colors, weeks, q };
  // Same keys as each column's count query, so React Query shares one request per month.
  const counts = useQueries({
    queries: shelf.map((month) => ({
      ...comparisonVehiclesOptions(code, { ...deckQuery(month, filters), limit: 1, offset: 0 }),
      enabled: !!model,
    })),
  });
  // A month with no matching cars is left out instead of shown as an empty card.
  // A 422 is the API saying the model is not offered that month: no matching cars either.
  const visibleMonths = shelf.filter((month, i) => {
    const count = counts[i];
    const notOffered = count?.error instanceof ApiError && count.error.status === 422;
    return (
      (count?.data?.page.total !== 0 && !notOffered) ||
      (bench.domain === domain &&
        bench.months.some((key) => monthValue(key) === month && monthModel(bench, key) === model))
    );
  });

  const film = bench.domain === "FILMTHICKNESS";
  const benchLayer = film ? layer : null;
  const monthQueries = useQueries({
    queries: bench.months.map((month) => monthBoxesOptions(code, bench.domain, monthValue(month))),
  });
  const monthData = bench.months.flatMap((month, i) =>
    monthQueries[i]?.data
      ? [
          {
            month: monthValue(month),
            model: monthModel(bench, month),
            data: {
              ...monthQueries[i].data,
              boxes: monthQueries[i].data.boxes.filter(
                (box) => box.model_code === monthModel(bench, month),
              ),
            },
          },
        ]
      : [],
  );
  // Car CF mean per orientation comes from the API (ungraded cross-location box), not the browser.
  const visualModels = [
    ...new Set(
      bench.cars.map((car) => car.model).filter((value): value is string => Boolean(value)),
    ),
  ];
  const visuals = useQueries({
    queries: visualModels.map((model) => ({
      ...comparisonVehicleVisualsOptions(code, {
        model,
        vehicle_id: bench.cars.filter((car) => car.model === model).map((car) => car.vehicle_id),
      }),
      enabled: !film && bench.months.length > 0,
    })),
  });
  const markersFor = (orient: Orient, model: string): Marker[] =>
    bench.cars.flatMap((car, i) => {
      if (car.model !== model) return [];
      const mean = visuals
        .flatMap((query) => query.data?.vehicles ?? [])
        .find((v) => v.vehicle_id === car.vehicle_id)
        ?.cf_boxes.find((b) => b.orientation === orient[0])?.stats?.mean;
      return mean == null || !car.color
        ? []
        : [
            {
              id: car.vehicle_id,
              n: i + 1,
              label: carLabel(car),
              color: car.color,
              month: carMonth(car),
              value: Number(mean),
              mean,
            },
          ];
    });
  const benchColors = colourOrder(monthData, [
    ...monthData.flatMap(({ data }) =>
      data.boxes.filter((b) => b.layer === benchLayer).map((b) => b.color_name),
    ),
    ...bench.cars.flatMap((c) => (c.color ? [c.color] : [])),
  ]);
  // Click a colour on the chart: show only it; click it again: show every colour.
  const focusColor = (color: string) =>
    setHidden(
      benchColors.length - hidden.length === 1 && !hidden.includes(color)
        ? []
        : benchColors.filter((c) => c !== color),
    );
  const preset = (count: number) => {
    const months = visibleMonths.slice(0, count);
    if (months.length < 2) return setNotice({ text: "Not enough measured months.", warn: true });
    change(
      presetMonths(bench, domain, model, months, count),
      `Comparing ${months.length} months: ${[...months].reverse().map(monthName).join(", ")}.`,
      true,
    );
  };
  const copyLink = async () => {
    const shared = toShared(bench);
    if (!shared) return;
    const href = new URL(
      router.buildLocation({
        to: "/plant/$code",
        params: { code },
        search: { compare: shared },
      }).href,
      window.location.origin,
    ).href;
    try {
      await navigator.clipboard.writeText(href);
      setNotice({ text: "Link copied. Anyone with access to this plant can open it." });
    } catch {
      setNotice({ text: `Copy this link: ${href}`, warn: true });
    }
  };

  const change = (next: Bench, text: string, undoable = false) => {
    setNotice({ text, undo: undoable ? bench : undefined });
    onBenchChange(next);
  };
  const switchModel = async (nextModel: string) => {
    if (nextModel === model) return;
    const previousModel = model;
    const requestId = ++modelSwitchId.current;
    setPicked(nextModel);
    setColors([]);
    const selectedMonths = [...new Set(benchRef.current.months.map(monthValue))];
    if (benchRef.current.domain !== domain || selectedMonths.length === 0) return;
    setSwitchingModel(true);
    setNotice({ text: `Checking selected months for ${nextModel}…` });
    try {
      const availability = await Promise.all(
        selectedMonths.map(async (month) => {
          try {
            const result = await queryClient.fetchQuery(
              comparisonVehiclesOptions(code, {
                domain,
                month: [month],
                model: nextModel,
                limit: 1,
                offset: 0,
              }),
            );
            return result.page.total > 0 ? month : null;
          } catch (error) {
            if (error instanceof ApiError && error.status === 422) return null;
            throw error;
          }
        }),
      );
      if (requestId !== modelSwitchId.current) return;
      const previous = benchRef.current;
      const next = retargetMonths(
        previous,
        nextModel,
        availability.filter((month): month is string => !!month),
      );
      onBenchChange(next);
      const unavailable = [...new Set(previous.months.map(monthValue))].filter(
        (month) => !next.months.includes(month),
      ).length;
      const duplicates = previous.months.length - next.months.length - unavailable;
      setNotice({
        text: `Selected months now show ${nextModel}.${unavailable ? ` ${unavailable} ${unavailable === 1 ? "month has" : "months have"} no readings for this model and ${unavailable === 1 ? "was" : "were"} removed.` : ""}${duplicates ? ` ${duplicates} repeated ${duplicates === 1 ? "month was" : "months were"} combined.` : ""}`,
        undo: previous,
        pickOnUndo: previousModel,
      });
    } catch {
      if (requestId !== modelSwitchId.current) return;
      setPicked(previousModel);
      setNotice({
        text: "Could not check this model’s months. Try changing the model again.",
        warn: true,
      });
    } finally {
      if (requestId === modelSwitchId.current) setSwitchingModel(false);
    }
  };
  const add = (card: Card) => {
    const reason = blockReason(bench, card);
    if (reason) return setNotice({ text: reason, warn: true });
    change(
      addCard(bench, card),
      `${card.kind === "month" ? monthName(card.month) : carLabel(card.car)} added to the bench.`,
    );
  };
  const remove = (kind: SlotKind, key: string, label: string) =>
    change(removeSlot(bench, kind, key), `${label} removed.`, true);
  const move = (kind: SlotKind, key: string, target: string | undefined) => {
    if (!target) return;
    change(moveSlot(bench, kind, key, target), "Bench reordered.");
    requestAnimationFrame(() =>
      document.querySelector<HTMLElement>(`[data-slot-key="${key}"]`)?.focus(),
    );
  };
  const slotKeys = (kind: SlotKind, key: string, label: string) => (e: KeyboardEvent) => {
    if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      e.preventDefault();
      move(kind, key, neighbour(bench, kind, key, e.key === "ArrowLeft" ? -1 : 1));
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      remove(kind, key, label);
    }
  };
  const reason = dragging ? blockReason(bench, dragging) : null;
  const empty = isEmpty(bench);

  const slot = (kind: SlotKind, key: string, index: number, title: string, sub: string) => (
    <li
      key={key}
      className="cmp-slot"
      data-kind={kind}
      data-slot-key={key}
      tabIndex={0}
      draggable
      aria-label={`${title}, ${sub}. Alt plus arrow keys reorder, Delete removes.`}
      style={kind === "car" ? ({ "--slot": slotColor(index + 1) } as CSSProperties) : undefined}
      onKeyDown={slotKeys(kind, key, title)}
      onDragStart={(e) => {
        e.stopPropagation();
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", title);
        setSlotDrag({ kind, key });
      }}
      onDragEnd={() => setSlotDrag(null)}
      onDragOver={(e) => {
        if (slotDrag?.kind === kind) e.preventDefault();
      }}
      onDrop={(e) => {
        if (slotDrag?.kind !== kind) return;
        e.preventDefault();
        e.stopPropagation();
        move(kind, slotDrag.key, key);
        setSlotDrag(null);
      }}
    >
      {kind === "car" ? (
        <span className="cmp-slot__tag" aria-hidden>
          {index + 1}
        </span>
      ) : (
        <GripVertical className="cmp-grip" aria-hidden />
      )}
      <span className="cmp-slot__text">
        <span className="cmp-slot__title">{title}</span>
        <span className="cmp-slot__sub">{sub}</span>
      </span>
      {kind === "month" && bench.months.length > 1 && (
        <button
          type="button"
          className="cmp-icon-btn cmp-star"
          aria-pressed={bench.baseline === key}
          aria-label={
            bench.baseline === key ? `${title} is the baseline` : `Make ${title} the baseline`
          }
          title="Baseline: drawn as a band behind the other months"
          onClick={() =>
            change(
              { ...bench, baseline: bench.baseline === key ? null : key },
              bench.baseline === key ? "Baseline cleared." : `${title} is the baseline.`,
            )
          }
        >
          <Star aria-hidden />
        </button>
      )}
      <button
        type="button"
        className="cmp-icon-btn"
        aria-label={`Remove ${title}`}
        onClick={() => remove(kind, key, title)}
      >
        <X aria-hidden />
      </button>
    </li>
  );

  return (
    <div className="cmp" aria-label="Comparison">
      <section className="panel cmp-deck" aria-label="Deck">
        <div className="cmp-deck__top">
          <div>
            <h2 className="cmp-title">Choose what to compare</h2>
            <p className="cmp-hint">
              Choose a model, then add months or cars. Changing models updates selected months.
            </p>
          </div>
        </div>
        <div className="cmp-filters">
          <div className="cmp-filters__primary">
            <div className="cmp-chips cmp-domain" role="group" aria-label="Measurement">
              <span className="cmp-field-label">Paint appearance</span>
              {(["WAVESCAN", "FILMTHICKNESS"] as const).map((d) => (
                <button
                  key={d}
                  type="button"
                  className="cmp-chip"
                  aria-pressed={domain === d}
                  onClick={() => {
                    if (d === domain) return;
                    modelSwitchId.current += 1;
                    setSwitchingModel(false);
                    onDomainChange(d);
                    setPicked("");
                    setColors([]);
                    setWeeks([]);
                  }}
                >
                  {DOMAIN_LABEL[d]}
                </button>
              ))}
            </div>
            <label className="cmp-select">
              <span className="cmp-field-label">Vehicle model</span>
              <select
                value={model}
                aria-label="Vehicle model"
                onChange={(e) => void switchModel(e.target.value)}
                disabled={!modelOptions.length || switchingModel}
              >
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
            <label className="cmp-search">
              <span className="cmp-search-label">Find a car</span>
              <Search aria-hidden />
              <input
                type="search"
                placeholder={domain === "WAVESCAN" ? "Serial number" : "Serial or job number"}
                aria-label="Search serial or job number"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
          </div>
          <div className="cmp-filters__secondary" role="group" aria-label="Refine the selection">
            {colorOptions.length > 0 && (
              <details className="cmp-filter-group">
                <summary>
                  Paint colours{" "}
                  <span>{colors.length ? `${colors.length} selected` : "All colours"}</span>
                  <ChevronDown aria-hidden="true" />
                </summary>
                <Chips
                  label="Colour"
                  options={colorOptions}
                  selected={colors}
                  onChange={setColors}
                />
              </details>
            )}
            <details className="cmp-filter-group">
              <summary>
                Measured week{" "}
                <span>
                  {weeks.length ? weeks.map((week) => `W${week}`).join(", ") : "All weeks"}
                </span>
                <ChevronDown aria-hidden="true" />
              </summary>
              <Chips
                label="Week"
                options={WEEKS.map(([w]) => w)}
                selected={weeks}
                render={(w) => `W${w} · ${WEEKS.find(([week]) => week === w)?.[1]}`}
                onChange={setWeeks}
              />
            </details>
            {(colors.length > 0 || weeks.length > 0 || search) && (
              <button
                type="button"
                className="cmp-link"
                onClick={() => {
                  setColors([]);
                  setWeeks([]);
                  setSearch("");
                }}
              >
                Reset filters
              </button>
            )}
          </div>
        </div>
        {probe.isPending ? (
          <LoadingState>Loading measured months…</LoadingState>
        ) : probe.isError ? (
          <ApiErrorState error={probe.error} retry={() => void probe.refetch()} />
        ) : shelf.length === 0 ? (
          <p className="cmp-hint">There are no active readings to compare for this plant.</p>
        ) : models.isError ? (
          <ApiErrorState error={models.error} retry={() => void models.refetch()} />
        ) : (
          <div
            className="cmp-rail cmp-scroll"
            role="list"
            aria-label="Measured months, newest first"
          >
            {visibleMonths.length === 0 && (
              <p className="cmp-hint">No month has cars matching these filters.</p>
            )}
            {visibleMonths.map((month) => (
              <MonthColumn
                key={month}
                code={code}
                month={month}
                filters={filters}
                layer={layer}
                bench={bench}
                onAdd={add}
                onLift={setDragging}
              />
            ))}
          </div>
        )}
      </section>

      <section
        className="panel cmp-bench"
        aria-label="Bench"
        data-drag={dragging ? (reason ? "blocked" : "ready") : undefined}
        onDragOver={(e) => {
          if (dragging && !reason) {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
          }
        }}
        onDrop={(e) => {
          e.preventDefault();
          if (dragging) add(dragging);
          setDragging(null);
        }}
      >
        <header className="cmp-bench__top">
          <h2 className="cmp-title">Your comparison</h2>
          <span className="cmp-lock" data-locked={bench.model ? true : undefined}>
            {bench.model ? (
              <>
                <Lock aria-hidden /> {DOMAIN_LABEL[bench.domain]} ·{" "}
                {[
                  ...new Set([
                    ...bench.months.map((key) => monthModel(bench, key)),
                    ...bench.cars.map((car) => car.model),
                  ]),
                ].join(" / ")}
              </>
            ) : (
              "No model yet"
            )}
          </span>
          <span className="cmp-count">
            Months <b className="num">{bench.months.length}</b>/{MAX_MONTHS}
          </span>
          <span className="cmp-count">
            Cars <b className="num">{bench.cars.length}</b>/{MAX_CARS}
          </span>
          <span className="cmp-spacer" />
          {visibleMonths.length > 1 && model && (
            <div className="cmp-chips" role="group" aria-label="Quick compare">
              <span className="cmp-field-label">Quick</span>
              <button type="button" className="cmp-chip" onClick={() => preset(2)}>
                Latest vs previous
              </button>
              {visibleMonths.length > 2 && (
                <button type="button" className="cmp-chip" onClick={() => preset(3)}>
                  Last 3 months
                </button>
              )}
            </div>
          )}
          {!empty && (
            <>
              <button type="button" className="cmp-btn" onClick={() => void copyLink()}>
                <Link2 aria-hidden /> Copy link
              </button>
              <button
                type="button"
                className="cmp-btn"
                onClick={() => change(emptyBench(bench.domain), "Bench cleared.", true)}
              >
                Clear bench
              </button>
            </>
          )}
        </header>

        <ul className="cmp-slots" aria-label="On the bench">
          {bench.months.map((m, i) =>
            slot(
              "month",
              m,
              i,
              monthName(m),
              `${monthModel(bench, m)} · ` +
                (m === bench.baseline
                  ? "Baseline"
                  : film
                    ? `${layerLabel(layer)} distribution`
                    : "CF distribution"),
            ),
          )}
          {bench.cars.map((car, i) =>
            slot(
              "car",
              car.vehicle_id,
              i,
              carLabel(car),
              `${car.model} · ${car.color ?? "No colour"} · ${shortDate(car.measured_date, car.date_is_month_only)}`,
            ),
          )}
          <li className="cmp-ghost" aria-hidden>
            {reason ??
              (dragging ? "Drop to add" : empty ? "Drop a month or a car here" : "Drop more")}
          </li>
        </ul>

        <div
          className="cmp-notice"
          role="status"
          aria-live="polite"
          data-warn={notice?.warn || undefined}
        >
          {notice && (
            <>
              <span>{notice.text}</span>
              {notice.undo && (
                <button
                  type="button"
                  className="cmp-link"
                  onClick={() => {
                    onBenchChange(notice.undo!);
                    if (notice.pickOnUndo) setPicked(notice.pickOnUndo);
                    setNotice({ text: "Undone." });
                  }}
                >
                  <RotateCcw aria-hidden /> Undo
                </button>
              )}
            </>
          )}
        </div>

        {empty ? (
          <div className="cmp-empty">
            <p>
              <b>Month cards</b> become boxplots side by side. <b>Car cards</b> become a location
              profile. Put both on the bench to see where each car sits inside its month.
            </p>
            <p className="cmp-hint">
              No mouse? Use the + buttons, then Alt+Arrow keys to reorder and Delete to remove.
            </p>
          </div>
        ) : (
          <div className="cmp-results">
            {bench.months.length > 0 && bench.model && (
              <>
                {film && (
                  <div className="cmp-chips" role="group" aria-label="Film layer">
                    <span className="cmp-field-label">Layer</span>
                    {FILM_LAYERS.map((l) => (
                      <button
                        key={l.code}
                        type="button"
                        className="cmp-chip"
                        aria-pressed={layer === l.code}
                        onClick={() => setLayer(l.code)}
                      >
                        {l.label}
                      </button>
                    ))}
                  </div>
                )}
                {benchColors.length > 1 && (
                  <>
                    <p className="cmp-hint">Tip: click a colour name on the chart to focus it.</p>
                    <Chips
                      label="Show colours"
                      options={benchColors}
                      selected={benchColors.filter((c) => !hidden.includes(c))}
                      onChange={(shown) => setHidden(benchColors.filter((c) => !shown.includes(c)))}
                    />
                  </>
                )}
                {monthQueries.some((q) => q.isPending) && (
                  <LoadingState>Loading month distributions…</LoadingState>
                )}
                {monthQueries.map(
                  (query, i) =>
                    query.isError && (
                      <ApiErrorState
                        key={bench.months[i]}
                        error={query.error}
                        retry={() => void query.refetch()}
                      />
                    ),
                )}
                {visuals.map(
                  (query, i) =>
                    query.isError && (
                      <ApiErrorState
                        key={visualModels[i]}
                        error={query.error}
                        retry={() => void query.refetch()}
                      />
                    ),
                )}
                {[...new Set(bench.months.map((key) => monthModel(bench, key)))].flatMap((model) =>
                  (["Horizontal", "Vertical"] as const).map((orient) => (
                    <OrientChart
                      key={`${model}-${orient}`}
                      model={model}
                      orient={orient}
                      months={monthData.filter((entry) => entry.model === model)}
                      markers={markersFor(orient, model)}
                      hidden={hidden}
                      baseline={
                        bench.months.length > 1 &&
                        bench.baseline &&
                        monthModel(bench, bench.baseline) === model
                          ? monthValue(bench.baseline)
                          : null
                      }
                      layer={benchLayer}
                      onColor={focusColor}
                    />
                  )),
                )}
              </>
            )}
            {bench.cars.length > 0 && bench.model && (
              <ProfileSection
                key={bench.domain}
                code={code}
                domain={bench.domain}
                cars={bench.cars}
                filmLayer={layer.toLowerCase() as Metric}
                onFilmLayerChange={(metric) => setLayer(metric.toUpperCase())}
              />
            )}
            {bench.months.length + bench.cars.length === 1 && (
              <p className="cmp-hint">Add a second month or car to compare against.</p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
