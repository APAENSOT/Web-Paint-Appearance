import { useId, useState, useRef } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Customized,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import {
  boxDescription,
  boxKey,
  colourPairWidth,
  filmDomain,
  integerTicks,
  displayMean,
  statusPresentation,
  panelLegend,
  orientationLabel,
  FILM_LAYERS,
  specSegments,
  type FilmOverviewBox,
  type FilmColorSequenceEntry,
} from "./film-overview-display";

import { SCROLL_HINT } from "@/features/measurements/overview-display";
import { FilmBoxSummary } from "./FilmBoxSummary";
import { usePointLabelsHere } from "@/features/measurements/point-labels";

type Axis = { scale: (value: number) => number };
type Axes = { xAxisMap?: Record<string, Axis>; yAxisMap?: Record<string, Axis> };
type Colour = {
  name: string;
  boxes: FilmOverviewBox[];
  family_code: string | null;
  family_name: string | null;
  family_order: number | null;
  ladder: FilmColorSequenceEntry["ladder"];
};

function FilmGlyphs({
  xAxisMap,
  yAxisMap,
  colours,
  boxes,
  widths,
  domain,
  model,
  active,
  setDetail,
  descriptionId,
}: Axes & {
  colours: Colour[];
  boxes: FilmOverviewBox[];
  widths: number[];
  domain: [number, number];
  model: string;
  active?: FilmOverviewBox;
  setDetail: (key: string) => void;
  descriptionId: (box: FilmOverviewBox) => string;
}) {
  const x = Object.values(xAxisMap ?? {})[0]?.scale;
  const y = Object.values(yAxisMap ?? {})[0]?.scale;
  if (!x || !y) return null;
  const starts = widths.map((_, index) =>
    widths.slice(0, index).reduce((sum, width) => sum + width, 0),
  );
  return (
    <g>
      {boxes.map((box) => {
        const index = colours.findIndex((colour) => colour.name === box.color_name);
        const colour = colours[index];
        const orient = box.orient;
        const centre = x(starts[index] + widths[index] / 2);
        const slotWidth = Math.abs(x(starts[index] + widths[index]) - x(starts[index]));
        const bottom = y(domain[0]);
        const key = boxKey(box),
          half = Math.min(24, slotWidth * 0.26);
        const q1 = y(Number(box.q1)),
          q3 = y(Number(box.q3));
        return (
          <g
            key={key}
            tabIndex={0}
            role="button"
            data-film-box={key}
            aria-label={`${colour.name}; ${orientationLabel(orient)}; ${model}; ${FILM_LAYERS.find((layer) => layer.code === box.layer_code)!.label}`}
            aria-describedby={descriptionId(box)}
            aria-expanded={active === box}
            className={`film-box film-box-${orient}`}
            data-status={statusPresentation(box).colour}
            data-selected={active === box}
            onClick={() => setDetail(key)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setDetail(key);
              }
            }}
          >
            <title>
              {colour.name}; {orientationLabel(orient)}
            </title>
            {(box.status === "WARNING" || box.status === "FAIL") && (
              <rect
                data-highlight={box.status}
                className="film-slot-band"
                x={centre - slotWidth / 2}
                y={y(domain[1])}
                width={slotWidth}
                height={bottom - y(domain[1])}
              />
            )}
            <rect
              className="film-box-hit"
              x={centre - slotWidth / 2 + 2}
              y={y(domain[1])}
              width={slotWidth - 4}
              height={bottom - y(domain[1]) + 24}
              fill="transparent"
              stroke="none"
            />
            <line
              x1={centre}
              x2={centre}
              y1={y(Number(box.whisker_lo))}
              y2={y(Number(box.whisker_hi))}
            />
            {[box.whisker_lo, box.whisker_hi].map((value, i) => (
              <line
                key={i}
                x1={centre - half / 2}
                x2={centre + half / 2}
                y1={y(Number(value))}
                y2={y(Number(value))}
              />
            ))}
            <rect
              className="film-quartiles"
              x={centre - half}
              y={q3}
              width={half * 2}
              height={Math.max(0, q1 - q3)}
            />
            {q1 === q3 && (
              <line x1={centre - half} x2={centre + half} y1={q1} y2={q1} strokeWidth={4} />
            )}
            <line
              className="film-median"
              x1={centre - half}
              x2={centre + half}
              y1={y(Number(box.median))}
              y2={y(Number(box.median))}
              strokeWidth={2.5}
            />
            <text
              className="film-mean num"
              data-mean={box.mean}
              x={centre}
              y={y(Math.max(Number(box.whisker_hi), Number(box.q3), Number(box.mean))) - 12}
              textAnchor="middle"
            >
              {displayMean(box.mean)}
            </text>
            {specSegments(box, centre, slotWidth).map((spec) => (
              <line
                key={spec.field}
                data-spec={spec.field}
                data-value={spec.raw}
                x1={spec.x1}
                x2={spec.x2}
                y1={y(spec.value)}
                y2={y(spec.value)}
                strokeDasharray={spec.dash}
                className={`film-spec film-spec-${spec.field}`}
              />
            ))}
          </g>
        );
      })}
    </g>
  );
}

type PanelProps = {
  model: string;
  colours: Colour[];
  boxes: FilmOverviewBox[];
  widths: number[];
  domain: [number, number];
  orient: FilmOverviewBox["orient"];
};
function OrientationCard({ model, colours, boxes, widths, domain, orient }: PanelProps) {
  const id = useId();
  const labelOf = usePointLabelsHere();
  const card = useRef<HTMLElement>(null);
  const opener = useRef<HTMLElement | SVGElement | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const active = boxes.find((box) => boxKey(box) === detail);
  const total = widths.reduce((sum, width) => sum + width, 0);
  const descriptionId = (box: FilmOverviewBox) => `${id}-${boxes.indexOf(box)}`;
  const select = (key: string) => {
    const focused = document.activeElement;
    opener.current =
      focused instanceof HTMLElement || focused instanceof SVGElement ? focused : null;
    setDetail(key);
  };
  const close = () => {
    setDetail(null);
    if (opener.current?.isConnected && card.current?.contains(opener.current))
      opener.current.focus();
  };
  const actual = boxes;
  const legend = panelLegend(actual);
  const gridStyle = { gridTemplateColumns: widths.map((width) => `${width}fr`).join(" ") };
  const families = colours.reduce<
    { start: number; count: number; name: string | null; code: string | null }[]
  >((groups, colour, index) => {
    const last = groups.at(-1);
    if (last && last.code === colour.family_code && last.name === colour.family_name) last.count++;
    else
      groups.push({
        start: index,
        count: 1,
        name: colour.family_name,
        code: colour.family_code,
      });
    return groups;
  }, []);
  return (
    <section
      ref={card}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          close();
        }
      }}
      className="film-orientation-panel"
      aria-label={`${model} ${orientationLabel(orient)}`}
    >
      <div className="film-panel-heading">
        <h4 className="font-semibold">
          {orientationLabel(orient)} <span className="text-xs text-muted-foreground">· µm</span>
        </h4>
        <ul aria-label={`${orientationLabel(orient)} spec legend`} className="film-legend text-xs">
          {legend.map((spec) => (
            <li
              key={JSON.stringify([spec.field, spec.label])}
              className={`film-spec-${spec.field}`}
            >
              <svg width="28" height="10" aria-hidden>
                <line
                  x1="0"
                  x2="28"
                  y1="5"
                  y2="5"
                  stroke="currentColor"
                  strokeDasharray={spec.dash}
                />
              </svg>
              {spec.label}
            </li>
          ))}
        </ul>
      </div>
      {!actual.length ? (
        <p className="py-6">No {orientationLabel(orient)} readings</p>
      ) : (
        <div
          className="film-chart-scroll"
          role="region"
          aria-label={`${model} ${orientationLabel(orient)} Film boxes, horizontally scrollable`}
          tabIndex={0}
        >
          <div style={{ width: total + 76, minWidth: "100%" }}>
            <div className="film-family-labels" style={gridStyle}>
              {families.map((family) => (
                <span
                  key={family.start}
                  style={{ gridColumn: `${family.start + 1} / span ${family.count}` }}
                >
                  {family.name ?? "No family assigned"}
                </span>
              ))}
            </div>
            <ResponsiveContainer width="100%" height={360}>
              <ComposedChart
                data={[{ x: 0 }, { x: total }]}
                margin={{ top: 16, right: 16, bottom: 8, left: 0 }}
                accessibilityLayer={false}
              >
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis type="number" dataKey="x" domain={[0, total]} hide />
                <YAxis
                  type="number"
                  domain={domain}
                  ticks={integerTicks(domain)}
                  width={60}
                  tick={{
                    fill: "var(--muted-foreground)",
                    fontSize: 11,
                    fontFamily: "JetBrains Mono",
                  }}
                  tickFormatter={(value) => String(value)}
                  label={{
                    value: "µm",
                    position: "insideTopLeft",
                    fill: "var(--muted-foreground)",
                    fontSize: 12,
                  }}
                />
                <Customized
                  component={
                    <FilmGlyphs
                      colours={colours}
                      boxes={actual}
                      widths={widths}
                      domain={domain}
                      model={model}
                      active={active}
                      setDetail={select}
                      descriptionId={descriptionId}
                    />
                  }
                />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="film-colour-labels" style={gridStyle}>
              {colours.map((colour) => {
                // FilmOverviewChart only passes colours that have a box here.
                const box = actual.find((item) => item.color_name === colour.name)!;
                return (
                  <span
                    key={colour.name}
                    data-colour={colour.name}
                    data-highlight={
                      box.status === "WARNING" || box.status === "FAIL" ? box.status : undefined
                    }
                  >
                    <button
                      type="button"
                      className="film-colour-select"
                      aria-expanded={active === box}
                      aria-label={`${colour.name}; ${orientationLabel(orient)} summary`}
                      onClick={() => select(boxKey(box))}
                    >
                      {colour.name}
                    </button>
                    <br />
                    <strong data-status={statusPresentation(box).colour}>
                      {statusPresentation(box).text}
                    </strong>
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      )}
      {boxes.map((box) => (
        <p key={boxKey(box)} id={descriptionId(box)} className="sr-only">
          {boxDescription(box, labelOf)}
        </p>
      ))}
      {active && (
        <FilmBoxSummary
          box={active}
          close={close}
          ladder={colours.find((colour) => colour.name === active.color_name)?.ladder}
        />
      )}
    </section>
  );
}
export function FilmOverviewChart({
  model,
  colours,
  boxes,
}: {
  model: string;
  colours: Colour[];
  boxes: FilmOverviewBox[];
}) {
  const domain = filmDomain(boxes);
  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">
        Select a box or colour for its summary. {SCROLL_HINT}
      </p>
      {(["H", "V"] as const).map((orient) => {
        const actual = boxes.filter((box) => box.orient === orient);
        // Only colours with readings in this orientation get a slot.
        const shown = colours.filter((colour) =>
          actual.some((box) => box.color_name === colour.name),
        );
        return (
          <OrientationCard
            key={`${orient}-${JSON.stringify(boxes)}`}
            model={model}
            colours={shown}
            boxes={actual}
            widths={shown.map((colour) => colourPairWidth(colour.name))}
            domain={domain}
            orient={orient}
          />
        );
      })}
    </div>
  );
}
