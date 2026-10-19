import { boxLines, plotDomain, type BoxEntry } from "./StudioCharts";

const statusStroke = (entry: BoxEntry) => {
  const status = entry.box && "status" in entry.box ? entry.box.status : null;
  return status === "PASS"
    ? "var(--nominal)"
    : status === "WARNING" || status === "OVER"
      ? "var(--caution)"
      : status === "FAIL"
        ? "var(--critical)"
        : "var(--muted-foreground)";
};
const statusWord = (entry: BoxEntry) =>
  entry.box && "status" in entry.box ? (entry.box.status ?? "No standard") : "Not measured";

/** One chart per orientation; colour blocks contain the complete ordered board. */
export function MonthlyDistribution({
  entries,
  orientation,
  onDetail,
}: {
  entries: BoxEntry[];
  orientation: "H" | "V";
  onDetail: (entry: BoxEntry) => void;
}) {
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
  const y = (value: string | number) =>
    270 - ((Number(value) - domain[0]) / (domain[1] - domain[0])) * 230;
  const rows = entries.filter((e) => e.orientation === orientation);
  const colors = [...new Set(rows.map((e) => e.color ?? ""))];
  const ordered = colors.flatMap((color) => rows.filter((e) => (e.color ?? "") === color));
  const slot = Math.max(
    108,
    ...ordered.map((entry) => (entry.group?.mean ?? entry.box?.mean ?? "").length * 7 + 24),
    ...colors.map(
      (color) =>
        (color.length * 8) / Math.max(1, rows.filter((entry) => entry.color === color).length) + 16,
    ),
  );
  const width = Math.max(660, ordered.length * slot + 80);
  const x = (index: number) => 80 + index * slot;
  const limits = [
    ...new Map(
      rows.flatMap((entry) =>
        entry.box
          ? boxLines(entry.box)
              .filter(([, value]) => value != null)
              .map(([label], i) => [label, i] as const)
          : [],
      ),
    ).entries(),
  ];
  return (
    <>
      <ul className="monthly-limit-legend" aria-label={`${orientation} supplied limit lines`}>
        {limits.map(([label, i]) => (
          <li key={label}>
            <svg width="28" height="12" aria-hidden="true">
              <line
                x1="0"
                x2="28"
                y1="6"
                y2="6"
                stroke={i === 0 ? "var(--nominal)" : "var(--critical)"}
                strokeDasharray={i === 2 ? "2 3" : "5 4"}
              />
            </svg>
            {label}
          </li>
        ))}
      </ul>
      <div
        className="studio-chart-scroll"
        tabIndex={0}
        role="region"
        aria-label={`${orientation} monthly chart scroll`}
      >
        <svg
          role="group"
          aria-label={`${orientation} distributions. All visible colours; month boxes in board order. Select a box or diamond for exact API values.`}
          viewBox={`0 0 ${width} 420`}
          style={{ width, minWidth: "100%", height: 420 }}
        >
          {[0, 1, 2, 3, 4].map((t) => {
            const value = domain[0] + ((domain[1] - domain[0]) * t) / 4;
            return (
              <g key={t}>
                <line x1={48} x2={width - 12} y1={y(value)} y2={y(value)} stroke="var(--border)" />
                <text
                  x={42}
                  y={y(value) + 4}
                  textAnchor="end"
                  fill="var(--muted-foreground)"
                  fontSize={11}
                >
                  {Number(value.toPrecision(3))}
                </text>
              </g>
            );
          })}
          {colors.map((color) => {
            const start = ordered.findIndex((e) => (e.color ?? "") === color);
            const count = ordered.filter((e) => (e.color ?? "") === color).length;
            return (
              <g key={color}>
                <line
                  x1={x(start) - slot / 2}
                  x2={x(start) - slot / 2}
                  y1={30}
                  y2={400}
                  stroke="var(--border)"
                />
                <text
                  data-colour={color}
                  x={x(start) + ((count - 1) * slot) / 2}
                  y={393}
                  textAnchor="middle"
                  fill="var(--foreground)"
                  fontSize={14}
                  fontWeight={600}
                >
                  {color || "No colour returned"}
                </text>
              </g>
            );
          })}
          {ordered.map((entry, index) => {
            const cx = x(index),
              box = entry.box,
              group = entry.group,
              stroke = statusStroke(entry);
            const label = `${entry.label} ${group ? `Group mean ${group.mean ?? "Not measured"}; ${group.contributing_month_count} contributing / ${entry.selected} selected` : `Mean ${box?.mean ?? "Not measured"}; n ${entry.n ?? "Unavailable"}; ${statusWord(entry)}`}`;
            const members = group
              ? ordered
                  .map((e, i) => ({ e, i }))
                  .filter(
                    ({ e }) => e.itemId === entry.itemId && e.color === entry.color && !e.group,
                  )
              : [];
            return (
              <g key={entry.key}>
                {group && !!members.length && (
                  <g aria-hidden="true" pointerEvents="none">
                    <path
                      data-testid="monthly-group-bracket"
                      d={`M${x(members[0].i) - 35} 335 v8 H${cx + 35} v-8`}
                      fill="none"
                      stroke="var(--primary)"
                    />
                    <text
                      x={cx - (members.length * slot) / 2}
                      y={361}
                      textAnchor="middle"
                      fill="var(--foreground)"
                      fontSize={12}
                    >
                      {entry.itemName}
                    </text>
                  </g>
                )}
                <g
                  tabIndex={0}
                  role="button"
                  aria-label={label}
                  className="monthly-glyph"
                  data-testid={group ? "studio-group-marker" : "studio-month-box"}
                  data-month={entry.month}
                  data-status={box && "status" in box ? box.status : undefined}
                  onClick={() => onDetail(entry)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onDetail(entry);
                    }
                  }}
                >
                  <rect
                    className="monthly-hit"
                    x={cx - 48}
                    y={28}
                    width={96}
                    height={336}
                    fill="transparent"
                  />
                  {group ? (
                    <>
                      {group.mean == null ? (
                        <text
                          x={cx}
                          y={160}
                          textAnchor="middle"
                          fill="var(--muted-foreground)"
                          fontSize={12}
                        >
                          Unavailable
                        </text>
                      ) : (
                        <>
                          <path
                            d={`M${cx} ${y(group.mean) - 7} l7 7 l-7 7 l-7 -7 Z`}
                            fill="var(--primary)"
                          />
                          <text
                            x={cx}
                            y={y(group.mean) - 16}
                            textAnchor="middle"
                            fill="var(--foreground)"
                            fontSize={12}
                          >
                            {group.mean}
                          </text>
                        </>
                      )}
                      <text x={cx} y={307} textAnchor="middle" fill="var(--primary)" fontSize={12}>
                        Group mean
                      </text>
                      <text
                        x={cx}
                        y={324}
                        textAnchor="middle"
                        fill="var(--muted-foreground)"
                        fontSize={11}
                      >
                        {group.contributing_month_count}/{entry.selected} months
                      </text>
                    </>
                  ) : !box || entry.n === 0 ? (
                    <text
                      x={cx}
                      y={160}
                      textAnchor="middle"
                      fill="var(--muted-foreground)"
                      fontSize={12}
                    >
                      Not measured
                    </text>
                  ) : (
                    <>
                      {(statusWord(entry) === "FAIL" || statusWord(entry) === "WARNING") && (
                        <rect
                          x={cx - 48}
                          y={30}
                          width={96}
                          height={240}
                          fill={stroke}
                          opacity={0.06}
                        />
                      )}
                      <line
                        x1={cx}
                        x2={cx}
                        y1={y(box.whisker_lo)}
                        y2={y(box.whisker_hi)}
                        stroke={stroke}
                        strokeWidth={1.5}
                      />
                      {[box.whisker_lo, box.whisker_hi].map((value, i) => (
                        <line
                          key={i}
                          x1={cx - 12}
                          x2={cx + 12}
                          y1={y(value)}
                          y2={y(value)}
                          stroke={stroke}
                          strokeWidth={1.5}
                        />
                      ))}
                      <rect
                        data-testid="monthly-quartiles"
                        x={cx - 22}
                        width={44}
                        y={y(box.q3)}
                        height={Math.max(0, y(box.q1) - y(box.q3))}
                        fill={stroke}
                        fillOpacity={0.12}
                        stroke={stroke}
                        strokeWidth={1.5}
                      />
                      <line
                        x1={cx - 22}
                        x2={cx + 22}
                        y1={y(box.median)}
                        y2={y(box.median)}
                        stroke={stroke}
                        strokeWidth={2.5}
                      />
                      {boxLines(box).map(([label, value], i) =>
                        value == null ? null : (
                          <line
                            key={label}
                            data-spec={label}
                            data-value={value}
                            x1={cx - 44}
                            x2={cx + 44}
                            y1={y(value)}
                            y2={y(value)}
                            stroke={i === 0 ? "var(--nominal)" : "var(--critical)"}
                            strokeDasharray={i === 2 ? "2 3" : "5 4"}
                          >
                            <title>
                              {label}: {value}
                            </title>
                          </line>
                        ),
                      )}
                      {box.outliers.map((value, i) => (
                        <circle key={i} cx={cx} cy={y(value)} r={3} fill={stroke} />
                      ))}
                      <text
                        data-testid="comparison-mean"
                        x={cx}
                        y={
                          y(
                            Math.max(
                              Number(box.whisker_hi),
                              Number(box.mean),
                              ...box.outliers.map(Number),
                            ),
                          ) - 12
                        }
                        textAnchor="middle"
                        fill="var(--foreground)"
                        fontSize={12}
                      >
                        {box.mean}
                      </text>
                    </>
                  )}
                  {!group && (
                    <>
                      <text
                        x={cx}
                        y={307}
                        textAnchor="middle"
                        fill="var(--foreground)"
                        fontSize={12}
                      >
                        {entry.caption}
                      </text>
                      <text x={cx} y={325} textAnchor="middle" fill={stroke} fontSize={11}>
                        {statusWord(entry)}
                      </text>
                    </>
                  )}
                  <title>{label}</title>
                </g>
              </g>
            );
          })}
        </svg>
        {!rows.length && (
          <p className="cv-empty">
            No visible {orientation} readings. Restore colours or add measured months.
          </p>
        )}
      </div>
    </>
  );
}
