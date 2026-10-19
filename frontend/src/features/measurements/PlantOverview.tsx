import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useIsFetching } from "@tanstack/react-query";
import { WavescanBoxSummary } from "./WavescanBoxSummary";
import { wavescanBoxKey, wavescanDescription } from "./wavescan-inspection";
import "./wavescan-overview.css";
import {
  CartesianGrid,
  ComposedChart,
  Customized,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import {
  displayMean,
  groupBoxesByModel,
  integerDomain,
  integerTicks,
  modelsToRender,
  monthTitle,
  SCROLL_HINT,
  statusLabel,
  targetRuns,
  type OverviewBox,
} from "./overview-display";

type Overview = components["schemas"]["WavescanOverviewOut"];

const PASS = "var(--nominal)";
const WARN = "var(--caution)";
const FAIL = "var(--critical)";
const NEUTRAL = "var(--muted-foreground)";
const STANDARD = "var(--nominal)";
const MINIMUM = "var(--critical)";

type BandScale = ((value: string) => number) & { bandwidth?: () => number; range?: () => number[] };
type NumericScale = ((value: number) => number) & { range?: () => number[] };
type XAxisLike = {
  scale?: BandScale;
  bandwidth?: number | (() => number);
  x?: number;
  width?: number;
};
type YAxisLike = { scale?: NumericScale; y?: number; height?: number };
type CartesianAxes = {
  xAxisMap?: Record<string, XAxisLike>;
  yAxisMap?: Record<string, YAxisLike>;
};

function strokeFor(status: OverviewBox["status"]): string {
  if (status === "PASS") return PASS;
  if (status === "WARNING") return WARN;
  if (status === "FAIL") return FAIL;
  return NEUTRAL;
}

function firstAxis<T>(map?: Record<string, T>): T | undefined {
  return map ? Object.values(map)[0] : undefined;
}

function scaleBandwidth(scale?: BandScale): number {
  const value = scale?.bandwidth?.();
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

function categoryLayout(xScale: BandScale, names: string[]) {
  const points = names.map((name) => xScale(name)).filter((value) => Number.isFinite(value));
  const gaps = points.slice(1).map((value, index) => value - points[index]);
  const spacing = gaps.length ? gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length : 36;
  const band = scaleBandwidth(xScale);
  const banded = band >= spacing * 0.35;
  return {
    center: (name: string) => (banded ? xScale(name) + band / 2 : xScale(name)),
    slot: banded ? band : spacing,
  };
}

function yDomain(boxes: OverviewBox[]): [number, number] {
  const nums: number[] = [];
  for (const box of boxes) {
    nums.push(
      Number(box.whisker_lo),
      Number(box.whisker_hi),
      Number(box.box_min),
      Number(box.box_max),
    );
    if (box.ford != null) nums.push(Number(box.ford));
    if (box.minimum != null) nums.push(Number(box.minimum));
    for (const outlier of box.outliers) nums.push(Number(outlier));
  }
  if (nums.length === 0) return [0, 100];
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const pad = Math.max((hi - lo) * 0.12, 2);
  return integerDomain(lo - pad, hi + pad);
}

type Inspection = {
  selected: string | null;
  select: (box: OverviewBox, opener: SVGElement) => void;
  descriptionId: (box: OverviewBox) => string;
};

function ColorTick({
  x = 0,
  y = 0,
  payload,
  boxes,
  selected,
  select,
  descriptionId,
}: Inspection & {
  x?: number;
  y?: number;
  payload?: { value?: string };
  boxes: OverviewBox[];
}) {
  const name = payload?.value ?? "";
  const box = boxes.find((item) => item.color_name === name);
  return (
    <g
      transform={`translate(${x},${y})`}
      className="wavescan-label-target"
      role="button"
      tabIndex={-1}
      data-wavescan-label={box ? wavescanBoxKey(box) : undefined}
      aria-label={`${name}; ${box?.orient} summary`}
      aria-describedby={box ? descriptionId(box) : undefined}
      aria-expanded={box ? selected === wavescanBoxKey(box) : false}
      onClick={(event) => {
        if (box) select(box, event.currentTarget);
      }}
      onKeyDown={(event) => {
        if (box && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          select(box, event.currentTarget);
        }
      }}
    >
      <rect
        className="wavescan-label-hit"
        x={-Math.max(44, name.length * 5.5 + 12) / 2}
        y={-4}
        width={Math.max(44, name.length * 5.5 + 12)}
        height={44}
        rx={3}
      />
      <text textAnchor="middle" dy={14} fontSize={10} fill="var(--foreground)">
        {name}
      </text>
      <text textAnchor="middle" dy={28} fontSize={10} fill={strokeFor(box?.status ?? null)}>
        {statusLabel(box?.status ?? null)}
      </text>
    </g>
  );
}

function BoxLayer({
  xAxisMap,
  yAxisMap,
  boxes,
  selected,
  select,
  descriptionId,
}: CartesianAxes & Inspection & { boxes: OverviewBox[] }) {
  const xAxis = firstAxis(xAxisMap);
  const yAxis = firstAxis(yAxisMap);
  const xScale = xAxis?.scale;
  const yScale = yAxis?.scale;
  if (!xAxis || !yAxis || !xScale || !yScale) return null;
  const names = boxes.map((box) => box.color_name);
  const layout = categoryLayout(xScale, names);
  const boxWidth = Math.max(14, Math.min(34, layout.slot / 2.4));
  const cap = boxWidth / 2.4;
  const y = (value: string | number) => yScale(Number(value));
  const centers = names
    .map((name) => layout.center(name))
    .filter((value) => Number.isFinite(value));
  const plotXMin =
    typeof xAxis.x === "number" ? xAxis.x : centers.length ? Math.min(...centers) : 0;
  const plotXMax =
    typeof xAxis.x === "number" && typeof xAxis.width === "number"
      ? xAxis.x + xAxis.width
      : centers.length
        ? Math.max(...centers)
        : 0;
  const spanX = (start: string, end: string) => {
    const pad = layout.slot / 2;
    return {
      x1: Math.max(plotXMin, layout.center(start) - pad),
      x2: Math.min(plotXMax, layout.center(end) + pad),
    };
  };
  const plotRange = yScale.range?.();
  const plotTop = typeof yAxis.y === "number" ? yAxis.y : plotRange ? Math.min(...plotRange) : 0;
  const plotHeight =
    typeof yAxis.height === "number"
      ? yAxis.height
      : plotRange
        ? Math.abs(plotRange[1] - plotRange[0])
        : 0;
  const fordRuns = targetRuns(boxes, "ford");
  const minRuns = targetRuns(boxes, "minimum");

  return (
    <g>
      {plotHeight > 0 &&
        boxes.map((box) => {
          if (box.status !== "FAIL" && box.status !== "WARNING") return null;
          const center = layout.center(box.color_name);
          if (!Number.isFinite(center)) return null;
          return (
            <rect
              key={`${box.color_name}-band`}
              x={center - layout.slot / 2}
              y={plotTop}
              width={layout.slot}
              height={plotHeight}
              fill={box.status === "FAIL" ? FAIL : WARN}
              fillOpacity={0.1}
            />
          );
        })}
      {fordRuns.map((run) => {
        const { x1, x2 } = spanX(run.start, run.end);
        if (!Number.isFinite(x1) || !Number.isFinite(x2) || x2 <= x1) return null;
        return (
          <line
            key={`ford-${run.start}-${run.end}-${run.value}`}
            x1={x1}
            x2={x2}
            y1={y(run.value)}
            y2={y(run.value)}
            stroke={STANDARD}
            strokeWidth={1.5}
            strokeDasharray="5 4"
          />
        );
      })}
      {minRuns.map((run) => {
        const { x1, x2 } = spanX(run.start, run.end);
        if (!Number.isFinite(x1) || !Number.isFinite(x2) || x2 <= x1) return null;
        return (
          <line
            key={`min-${run.start}-${run.end}-${run.value}`}
            x1={x1}
            x2={x2}
            y1={y(run.value)}
            y2={y(run.value)}
            stroke={MINIMUM}
            strokeWidth={1.5}
            strokeDasharray="5 4"
          />
        );
      })}
      {boxes.map((box, index) => {
        const center = layout.center(box.color_name);
        if (!Number.isFinite(center)) return null;
        const left = center - boxWidth / 2;
        const q1 = y(box.q1);
        const q3 = y(box.q3);
        const top = Math.min(q1, q3);
        const height = Math.max(Math.abs(q3 - q1), 2);
        const medianY = y(box.median);
        const whiskerLo = y(box.whisker_lo);
        const whiskerHi = y(box.whisker_hi);
        const stroke = strokeFor(box.status);
        return (
          <g
            key={`${box.model_code}-${box.color_name}-${box.orient}`}
            className="wavescan-box-target"
            role="button"
            tabIndex={0}
            data-wavescan-box={wavescanBoxKey(box)}
            aria-label={`${box.color_name}; ${box.orient} box summary`}
            aria-describedby={descriptionId(box)}
            aria-expanded={selected === wavescanBoxKey(box)}
            onClick={(event) => select(box, event.currentTarget)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                select(box, event.currentTarget);
              }
            }}
          >
            <rect
              className="wavescan-box-hit"
              x={center - 22}
              y={plotTop}
              width={44}
              height={Math.max(plotHeight, 44)}
              rx={3}
            />
            <line
              x1={center}
              x2={center}
              y1={whiskerHi}
              y2={top}
              stroke={stroke}
              strokeWidth={1.5}
            />
            <line
              x1={center}
              x2={center}
              y1={top + height}
              y2={whiskerLo}
              stroke={stroke}
              strokeWidth={1.5}
            />
            <line
              x1={center - cap}
              x2={center + cap}
              y1={whiskerHi}
              y2={whiskerHi}
              stroke={stroke}
              strokeWidth={1.5}
            />
            <line
              x1={center - cap}
              x2={center + cap}
              y1={whiskerLo}
              y2={whiskerLo}
              stroke={stroke}
              strokeWidth={1.5}
            />
            <rect
              x={left}
              y={top}
              width={boxWidth}
              height={height}
              fill={stroke}
              fillOpacity={0.16}
              stroke={stroke}
              strokeWidth={1.5}
              rx={2}
              className="animate-grow-y"
              style={{
                transformOrigin: `${center}px ${medianY}px`,
                animationDelay: `${Math.min(index, 8) * 40}ms`,
              }}
            />
            <line
              x1={left}
              x2={left + boxWidth}
              y1={medianY}
              y2={medianY}
              stroke={stroke}
              strokeWidth={2.5}
            />
            {box.outliers.map((value, outlierIndex) => (
              <circle
                key={`${box.color_name}-out-${outlierIndex}`}
                cx={center}
                cy={y(value)}
                r={2.5}
                fill={stroke}
              />
            ))}
            <text
              x={center}
              y={Math.min(whiskerHi, top) - 8}
              textAnchor="middle"
              fontSize={11}
              className="num"
              fill="var(--foreground)"
            >
              {displayMean(box.mean)}
            </text>
            <title>{`${box.color_name}: ${statusLabel(box.status)}, mean ${displayMean(box.mean)}, n ${box.n}`}</title>
          </g>
        );
      })}
    </g>
  );
}

function OrientChart({
  title,
  boxes,
  empty,
  delay,
  busy,
  scope,
}: {
  busy: boolean;
  scope: string;
  title: string;
  boxes: OverviewBox[];
  empty: string;
  delay: string;
}) {
  const id = useId();
  const card = useRef<HTMLElement>(null);
  const opener = useRef<SVGElement | null>(null);
  const [selection, setSelection] = useState<{ scope: string; key: string | null }>({
    scope,
    key: null,
  });
  const selected = selection.scope === scope ? selection.key : null;
  const setSelected = (key: string | null) => setSelection({ scope, key });
  if (selection.scope !== scope) setSelected(null);
  const active = boxes.find((box) => wavescanBoxKey(box) === selected);
  // Forget removed grains during render so their later reappearance cannot reopen a detail.
  if (selected && !active) setSelected(null);
  const select = (box: OverviewBox, target: SVGElement) => {
    if (busy) return;
    opener.current = target;
    target.focus({ preventScroll: true });
    setSelected(wavescanBoxKey(box));
  };
  const close = () => {
    const attribute = opener.current?.hasAttribute("data-wavescan-label")
      ? "data-wavescan-label"
      : "data-wavescan-box";
    const target = opener.current?.isConnected
      ? opener.current
      : [...(card.current?.querySelectorAll<SVGElement>(`[${attribute}]`) ?? [])].find(
          (node) => node.getAttribute(attribute) === selected,
        );
    setSelected(null);
    target?.focus({ preventScroll: true });
  };
  const inspection: Inspection = {
    selected: busy ? null : selected,
    select,
    descriptionId: (box) => `${id}-${boxes.indexOf(box)}`,
  };
  const minWidth =
    boxes.length * Math.max(56, ...boxes.map((box) => box.color_name.length * 5.5 + 12)) + 120;
  const scroller = useRef<HTMLDivElement>(null);
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const node = scroller.current;
    if (!node) {
      setWide(false);
      return;
    }
    const check = () => setWide(node.scrollWidth > node.clientWidth + 1);
    check();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(check);
    observer.observe(node);
    return () => observer.disconnect();
  }, [minWidth]);
  const data = boxes.map((box) => ({ color_name: box.color_name }));
  const domain = yDomain(boxes);
  const ticks = integerTicks(domain);
  return (
    <section
      ref={card}
      className="wavescan-orientation-panel panel animate-rise min-w-0 p-4"
      style={{ animationDelay: delay }}
      aria-label={title}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          close();
        }
      }}
    >
      <div className="wavescan-panel-heading">
        <h4 className="font-semibold">
          {title.endsWith("Horizontal") ? "Horizontal" : "Vertical"}{" "}
          <span className="text-xs text-muted-foreground">· CF</span>
        </h4>
        <ul className="wavescan-legend text-xs text-muted-foreground">
          <li className="flex items-center gap-1.5">
            <span
              className="inline-block h-px w-4 border-t border-dashed"
              style={{ borderColor: STANDARD }}
            />
            Standard
          </li>
          <li className="flex items-center gap-1.5">
            <span
              className="inline-block h-px w-4 border-t border-dashed"
              style={{ borderColor: MINIMUM }}
            />
            Minimum
          </li>
        </ul>
      </div>
      {wide && <p className="mb-2 text-xs text-muted-foreground">{SCROLL_HINT}</p>}
      {boxes.length === 0 ? (
        <p className="py-10 text-center text-xs text-muted-foreground">{empty}</p>
      ) : (
        <div ref={scroller} className="wavescan-chart-scroll">
          <div
            className="h-80 w-full min-w-0 overflow-hidden"
            style={{ minWidth }}
            role="group"
            aria-label={`${title} CF boxplots`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                key={boxes.map((box) => `${box.color_name}:${box.mean}:${box.n}`).join("|")}
                data={data}
                margin={{ top: 28, right: 20, bottom: 40, left: 8 }}
              >
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis
                  dataKey="color_name"
                  interval={0}
                  height={58}
                  padding={{ left: 24, right: 36 }}
                  tick={(props) => <ColorTick {...props} boxes={boxes} {...inspection} />}
                  tickLine={false}
                  axisLine={{ stroke: "var(--border)" }}
                />
                <YAxis
                  domain={domain}
                  ticks={ticks}
                  interval={0}
                  allowDecimals={false}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  tickFormatter={(value: number) => String(Math.round(value))}
                  label={{
                    value: "CF",
                    angle: -90,
                    position: "insideLeft",
                    fill: "var(--muted-foreground)",
                  }}
                />
                <Customized component={<BoxLayer boxes={boxes} {...inspection} />} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
      {boxes.map((box) => (
        <p className="sr-only" id={inspection.descriptionId(box)} key={wavescanBoxKey(box)}>
          {wavescanDescription(box)}
        </p>
      ))}
      {active && (
        <div hidden={busy}>
          <WavescanBoxSummary box={active} close={close} />
        </div>
      )}
    </section>
  );
}

export function PlantOverview({
  month,
  data,
  isPending,
  isError,
  error,
  onRetry,
  selectedModels,
}: {
  month: string;
  data?: Overview;
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  onRetry: () => void;
  selectedModels: string[];
}) {
  const busy = useIsFetching({ queryKey: ["overview"] }) > 0;
  const scope = JSON.stringify([
    data?.plant_code,
    month,
    data?.month,
    selectedModels,
    data?.models,
    data?.colors,
  ]);
  const groups = useMemo(() => {
    if (!data) return [];
    const models = modelsToRender(selectedModels, data.boxes, data.model_options);
    const grouped = groupBoxesByModel(data.boxes);
    const byModel = new Map(grouped.map((group) => [group.model, group]));
    return models.map((model) => byModel.get(model) ?? { model, horizontal: [], vertical: [] });
  }, [data, selectedModels]);

  if (isPending) {
    return (
      <section className="panel min-h-[420px] p-5" aria-label="Monthly Overview">
        <LoadingState>Loading monthly overview...</LoadingState>
      </section>
    );
  }
  if (isError) {
    return (
      <section className="panel min-h-[420px] p-5" aria-label="Monthly Overview">
        <ApiErrorState error={error ?? new Error("Monthly overview failed")} retry={onRetry} />
      </section>
    );
  }

  const emptyMonth = !data?.boxes.length;
  return (
    <section
      className="wavescan-overview flex min-w-0 flex-col gap-3"
      aria-label="Monthly Overview"
    >
      <section className="panel animate-rise px-5 py-4">
        <h2 className="text-xl font-bold">WaveScan</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Monthly overview · paint appearance in CF
        </p>
        <p className="mt-1 text-sm">{monthTitle(data?.month ?? month)} · CF</p>
        {!emptyMonth && (
          <p className="mt-3 text-xs text-muted-foreground">
            Select a box or colour name to inspect its readings and limits. Horizontal and Vertical
            are shown separately.
          </p>
        )}
        {emptyMonth && (
          <p className="mt-2 text-xs text-muted-foreground">
            There are no active readings for this month.
          </p>
        )}
      </section>
      {groups.map((group, index) => (
        <section key={group.model} className="flex min-w-0 flex-col gap-3" aria-label={group.model}>
          <h3 className="px-1 text-base font-semibold tracking-tight">{group.model}</h3>
          <OrientChart
            scope={scope}
            busy={busy}
            title={`${group.model} Horizontal`}
            boxes={group.horizontal}
            empty="There are no active Horizontal readings."
            delay={`${80 + index * 80}ms`}
          />
          <OrientChart
            scope={scope}
            busy={busy}
            title={`${group.model} Vertical`}
            boxes={group.vertical}
            empty="There are no active Vertical readings."
            delay={`${120 + index * 80}ms`}
          />
        </section>
      ))}
    </section>
  );
}
