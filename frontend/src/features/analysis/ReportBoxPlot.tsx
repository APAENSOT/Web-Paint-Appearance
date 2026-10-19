/**
 * AR03 (D-AR03-9): the report's one SVG boxplot, on screen and in the slides.
 *
 * Neutral fill, the mean marked and labelled, dashed lines with the box's own
 * labels, the site's status word as text under the box (never a fill colour).
 * When the API sends `values` (n < 5) the values are drawn as dots. Ink is
 * `currentColor`, so the same markup reads on screen and as a PNG.
 */

export type ChartBox = {
  label: string;
  n: number;
  q1: number;
  median: number;
  q3: number;
  whiskerLo: number;
  whiskerHi: number;
  mean: number;
  outliers: number[];
  values?: number[] | null;
  status?: string;
  lines?: { label: string; value: number }[];
};

export const CHART_W = 960;
export const CHART_H = 520;
const M = { top: 24, right: 16, bottom: 170, left: 48 };
const fmt = (x: number) => x.toFixed(1);

export function ReportBoxPlot({
  boxes,
  title,
  width = CHART_W,
  height = CHART_H,
  forImage = false,
}: {
  boxes: ChartBox[];
  title: string;
  width?: number;
  height?: number;
  /** An <img> needs pixel size; on screen the chart scales with its box. */
  forImage?: boolean;
}) {
  if (!boxes.length) return null;
  const all = boxes.flatMap((b) => [
    b.whiskerLo,
    b.whiskerHi,
    ...b.outliers,
    ...(b.values ?? []),
    ...(b.lines ?? []).map((l) => l.value),
  ]);
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = (hi - lo || 1) * 0.08;
  const [y0, y1] = [lo - pad, hi + pad];
  const plotH = height - M.top - M.bottom;
  const slot = (width - M.left - M.right) / Math.max(boxes.length, 1);
  const y = (v: number) => M.top + ((y1 - v) / (y1 - y0)) * plotH;
  const ticks = Array.from({ length: 5 }, (_, i) => y0 + ((y1 - y0) * i) / 4);
  const half = Math.min(slot * 0.28, 28);

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox={`0 0 ${width} ${height}`}
      width={forImage ? width : undefined}
      height={forImage ? height : undefined}
      role="img"
      aria-label={title}
      className="h-auto w-full max-w-full"
      fontFamily="Arial, sans-serif"
      fontSize={11}
    >
      <title>{title}</title>
      {ticks.map((t) => (
        <g key={t}>
          <line
            x1={M.left}
            x2={width - M.right}
            y1={y(t)}
            y2={y(t)}
            stroke="#9ca3af"
            strokeOpacity={0.3}
          />
          <text x={M.left - 6} y={y(t) + 4} textAnchor="end" fill="currentColor">
            {fmt(t)}
          </text>
        </g>
      ))}
      {boxes.map((b, i) => {
        const cx = M.left + slot * (i + 0.5);
        return (
          <g key={`${b.label}-${i}`} data-box={b.label}>
            {(b.lines ?? []).map((l) => (
              <g key={`${l.label}-${l.value}`} data-line={l.label}>
                <line
                  x1={cx - slot / 2 + 2}
                  x2={cx + slot / 2 - 2}
                  y1={y(l.value)}
                  y2={y(l.value)}
                  stroke="currentColor"
                  strokeDasharray="5 3"
                />
                <text
                  x={cx + slot / 2 - 3}
                  y={y(l.value) - 3}
                  textAnchor="end"
                  fontSize={9}
                  fill="currentColor"
                >
                  {l.label} {fmt(l.value)}
                </text>
              </g>
            ))}
            {b.values ? (
              b.values.map((v, k) => (
                <circle key={k} cx={cx} cy={y(v)} r={4} fill="currentColor" data-dot="" />
              ))
            ) : (
              <>
                <line x1={cx} x2={cx} y1={y(b.whiskerHi)} y2={y(b.q3)} stroke="currentColor" />
                <line x1={cx} x2={cx} y1={y(b.q1)} y2={y(b.whiskerLo)} stroke="currentColor" />
                <line
                  x1={cx - half / 2}
                  x2={cx + half / 2}
                  y1={y(b.whiskerHi)}
                  y2={y(b.whiskerHi)}
                  stroke="currentColor"
                />
                <line
                  x1={cx - half / 2}
                  x2={cx + half / 2}
                  y1={y(b.whiskerLo)}
                  y2={y(b.whiskerLo)}
                  stroke="currentColor"
                />
                <rect
                  x={cx - half}
                  y={y(b.q3)}
                  width={half * 2}
                  height={Math.max(y(b.q1) - y(b.q3), 1)}
                  fill="#9ca3af"
                  fillOpacity={0.4}
                  stroke="currentColor"
                />
                <line
                  x1={cx - half}
                  x2={cx + half}
                  y1={y(b.median)}
                  y2={y(b.median)}
                  stroke="currentColor"
                  strokeWidth={2}
                />
                {b.outliers.map((v, k) => (
                  <circle key={k} cx={cx} cy={y(v)} r={2.5} fill="none" stroke="currentColor" />
                ))}
              </>
            )}
            <path
              d={`M ${cx} ${y(b.mean) - 5} l 5 5 l -5 5 l -5 -5 z`}
              fill="currentColor"
              data-mean={fmt(b.mean)}
            />
            <text x={cx + 7} y={y(b.mean) + 4} fontSize={10} fontWeight="bold" fill="currentColor">
              {fmt(b.mean)}
            </text>
            <text
              x={cx}
              y={height - M.bottom + 16}
              textAnchor="middle"
              fill="currentColor"
              data-status=""
            >
              {b.status ?? ""}
            </text>
            <text
              x={cx}
              y={height - M.bottom + 30}
              textAnchor="middle"
              fontSize={10}
              fill="currentColor"
            >
              n {b.n}
            </text>
            <text
              transform={`translate(${cx} ${height - M.bottom + 42}) rotate(-35)`}
              textAnchor="end"
              fontSize={10}
              fill="currentColor"
            >
              {b.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
