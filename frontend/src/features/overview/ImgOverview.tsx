import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Maximize2, Minimize2, X } from "lucide-react";
import { imgColorsOptions, imgMonthsOptions, imgOverviewOptions } from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { monthTitle } from "@/features/measurements/overview-display";
import {
  FILM_MEASURES,
  axisTicks,
  chartGroups,
  countText,
  croppedTicks,
  displayMean1,
  effectiveMonth,
  emptyReason,
  exclusionsOf,
  isUnmapped,
  measureLabel,
  orientLabel,
  rankedColours,
  type FilmMeasure,
  type ImgColorSeries,
  type ImgColors,
  type ImgOverview as ImgData,
  type ImgSeries,
  type Metric,
  type Orient,
} from "./img-overview-display";

const FOCUSABLE =
  'button:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

type ReportProps = {
  month: string | null;
  onMonth: (month: string) => void;
  onClose: () => void;
  reduced: boolean;
};

/**
 * Overview IMG: monthly family averages, a dialog laid over the landing map.
 * Every number on it is an API field; this file only lays them out.
 */
export function ImgOverview({
  measure,
  onMeasure,
  ...props
}: ReportProps & { measure: FilmMeasure; onMeasure: (measure: FilmMeasure) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const months = useQuery(imgMonthsOptions);
  const shown = months.data ? effectiveMonth(months.data.months, props.month) : null;
  const report = useQuery({
    ...imgOverviewOptions({ month: shown ?? "", film_measure: measure }),
    enabled: shown !== null,
    // The last report stays (dimmed) while the next loads, so focus never falls out of the dialog.
    placeholderData: keepPreviousData,
  });
  // A new month or measure is a new report: a detail from the old one would describe nothing on screen.
  useEffect(() => setSelected(null), [shown, measure]);
  const detail = report.data?.series.find((s) => s.id === selected) ?? null;
  return (
    <ReportShell
      {...props}
      title="Overview IMG"
      subtitle="Monthly family averages · FTM / FVL / SAP / AAT"
      months={months}
      shown={shown}
      report={report}
      extraControls={
        <label>
          <span>Film measure</span>
          <select value={measure} onChange={(e) => onMeasure(e.target.value as FilmMeasure)}>
            {FILM_MEASURES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      }
      body={(data: ImgData) => (
        <>
          <UnmappedNotice series={data.series} />
          <div className="img-report__charts">
            {/* Each domain is one row: Horizontal left, Vertical right. */}
            {(
              [
                ["CF", "H"],
                ["CF", "V"],
                ["FILM", "H"],
                ["FILM", "V"],
              ] as [Metric, Orient][]
            ).map(([metric, orient]) => (
              <FamilyChart
                key={`${metric}${orient}`}
                data={data}
                metric={metric}
                orient={orient}
                selected={selected}
                onSelect={setSelected}
                reduced={props.reduced}
              />
            ))}
          </div>
        </>
      )}
      detail={
        detail && report.data
          ? {
              id: detail.id,
              node: (back) => (
                <Detail
                  title={`${detail.plant_code} · ${detail.family_name}`}
                  context={`${detail.metric === "CF" ? "Wave Scan CF" : "Film Thickness"} · ${orientLabel(detail.orient)}${
                    detail.film_measure ? ` · ${measureLabel(detail.film_measure)}` : ""
                  } · ${monthTitle(report.data!.month)}`}
                  series={detail}
                  unit={detail.unit === "CF" ? "CF" : "µm"}
                  colours={detail.colors}
                  unmapped={isUnmapped(detail)}
                  onClose={back}
                />
              ),
            }
          : null
      }
      onDetailClose={() => setSelected(null)}
    />
  );
}

/** IMG Color: every plant's colours ranked by pooled CF, H and V apart. */
const PLANT_FILTERS = ["ALL", "FTM", "FVL", "SAP", "AAT"] as const;

export function ImgColor(props: ReportProps) {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [plant, setPlant] = useState<(typeof PLANT_FILTERS)[number]>("ALL");
  const months = useQuery(imgMonthsOptions);
  const shown = months.data ? effectiveMonth(months.data.months, props.month) : null;
  const report = useQuery({
    ...imgColorsOptions({ month: shown ?? "" }),
    enabled: shown !== null,
    placeholderData: keepPreviousData,
  });
  useEffect(() => setSelected(null), [shown]);
  const detail = report.data?.series.find((s) => s.id === selected) ?? null;
  return (
    <ReportShell
      {...props}
      title="IMG Color"
      subtitle="Average CF by colour · every plant · ranked high to low"
      months={months}
      shown={shown}
      report={report}
      extraControls={
        <>
          <div className="img-report__plants" role="group" aria-label="Show plant">
            <span>Plant</span>
            <div>
              {PLANT_FILTERS.map((code) => (
                <button
                  key={code}
                  type="button"
                  aria-pressed={plant === code}
                  onClick={() => {
                    setPlant(code);
                    setSelected(null);
                  }}
                >
                  {code === "ALL" ? "All plants" : code}
                </button>
              ))}
            </div>
          </div>
          <label className="img-report__search">
            <span>Find a colour</span>
            <input
              type="search"
              value={search}
              placeholder="Colour name…"
              onChange={(event) => {
                setSearch(event.target.value);
                setSelected(null);
              }}
            />
          </label>
        </>
      }
      body={(data: ImgColors) => (
        <div className="img-report__ranks">
          {(["H", "V"] as Orient[]).map((orient) => (
            <ColourChart
              key={orient}
              data={{
                ...data,
                series: data.series.filter(
                  (x) =>
                    (plant === "ALL" || x.plant_code === plant) &&
                    x.color_name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
                ),
              }}
              scale={data}
              orient={orient}
              selected={selected}
              onSelect={setSelected}
              reduced={props.reduced}
            />
          ))}
        </div>
      )}
      detail={
        detail && report.data
          ? {
              id: detail.id,
              node: (back) => (
                <Detail
                  title={`${detail.color_name} · ${detail.plant_code}`}
                  context={`Average CF · ${orientLabel(detail.orient)} · ${monthTitle(report.data!.month)}`}
                  series={detail}
                  unit="CF"
                  onClose={back}
                />
              ),
            }
          : null
      }
      onDetailClose={() => setSelected(null)}
    />
  );
}

// ------------------------------------------------------------------ shell
function ReportShell<T extends { month: string; series: unknown[]; aggregation: string }>({
  title,
  subtitle,
  month,
  onMonth,
  onClose,
  reduced,
  months,
  shown,
  report,
  extraControls,
  body,
  detail,
  onDetailClose,
}: ReportProps & {
  title: string;
  subtitle: string;
  months: UseQueryResult<{ months: string[] }>;
  shown: string | null;
  report: UseQueryResult<T> & { isPlaceholderData: boolean };
  extraControls?: ReactNode;
  body: (data: T) => ReactNode;
  detail: { id: string; node: (back: () => void) => ReactNode } | null;
  onDetailClose: () => void;
}) {
  const dialog = useRef<HTMLElement>(null);
  const titleId = useId();
  const [closing, setClosing] = useState(false);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [expanded]);

  // Keep the parent's choice valid: a month that left the list falls back to the newest.
  useEffect(() => {
    if (shown !== null && shown !== month) onMonth(shown);
  }, [shown, month, onMonth]);

  useLayoutEffect(() => {
    const el = dialog.current;
    if (!el) return;
    el.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    if (reduced) return;
    const enter = el.animate(
      [
        { opacity: 0, transform: "translateY(10px) scale(0.985)" },
        { opacity: 1, transform: "none" },
      ],
      { duration: 240, easing: "cubic-bezier(0.16, 1, 0.3, 1)" },
    );
    return () => enter.cancel();
  }, [reduced]);

  const close = () => {
    if (closing) return;
    const el = dialog.current;
    if (!el || reduced) return onClose();
    setClosing(true);
    el.animate([{ opacity: 1 }, { opacity: 0, transform: "translateY(6px)" }], {
      duration: 160,
      easing: "ease-in",
      fill: "forwards",
    }).onfinish = onClose;
  };

  // Escape closes from anywhere while open, even if focus was lost to the page.
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
    };
    document.addEventListener("keydown", onEscape);
    return () => document.removeEventListener("keydown", onEscape);
  }, []);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "Tab" || !dialog.current) return;
    const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const back = () => {
    const id = detail?.id;
    onDetailClose();
    if (id)
      dialog.current?.querySelector<HTMLElement>(`[data-series="${CSS.escape(id)}"]`)?.focus();
  };

  return (
    <div
      className="img-overlay"
      data-closing={closing || undefined}
      data-expanded={expanded || undefined}
    >
      <section
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="img-report"
        onKeyDown={onKeyDown}
      >
        <header className="img-report__header">
          <div className="img-report__title">
            <h2 id={titleId}>{title}</h2>
            <p>{subtitle}</p>
          </div>
          <div className="img-report__controls">
            <label>
              <span>Measured month</span>
              <select
                value={shown ?? ""}
                disabled={months.isError || (months.isSuccess && !months.data.months.length)}
                onChange={(e) => onMonth(e.target.value)}
              >
                {!months.data?.months.length && (
                  <option value="">
                    {months.isPending
                      ? "Loading months…"
                      : months.isError
                        ? "Months unavailable"
                        : "No months"}
                  </option>
                )}
                {months.data?.months.map((m) => (
                  <option key={m} value={m}>
                    {monthTitle(m)}
                  </option>
                ))}
              </select>
            </label>
            {extraControls}
            <p className="img-report__note">
              Point settings applied · no grades · select a bar for details
            </p>
          </div>
          <div className="img-report__actions">
            <button
              type="button"
              className="img-report__close"
              onClick={() => setExpanded((value) => !value)}
              aria-pressed={expanded}
              aria-label={expanded ? "Fit report to map" : "Expand report"}
            >
              {expanded ? (
                <Minimize2 size={15} aria-hidden="true" />
              ) : (
                <Maximize2 size={15} aria-hidden="true" />
              )}
              <span>{expanded ? "Fit" : "Expand"}</span>
            </button>
            <button type="button" className="img-report__close" onClick={close}>
              <X size={15} aria-hidden="true" />
              Close
            </button>
          </div>
        </header>

        <div className="img-report__main">
          <div
            className="img-report__body"
            data-stale={report.isPlaceholderData || undefined}
            aria-busy={report.isFetching}
          >
            {report.isPlaceholderData && report.data && (
              <p className="img-report__refresh" role="status">
                Loading selected report… Showing {monthTitle(report.data.month)} until ready.
              </p>
            )}
            {months.isPending ? (
              <LoadingState>Loading measured months…</LoadingState>
            ) : months.isError ? (
              <ApiErrorState error={months.error} retry={() => void months.refetch()} />
            ) : !months.data.months.length ? (
              <p className="img-report__empty">
                No measured months yet. Months appear here once Wave Scan or Film readings are
                loaded.
              </p>
            ) : report.isPending ? (
              <LoadingState>Loading {shown ? monthTitle(shown) : "report"}…</LoadingState>
            ) : report.isError ? (
              <ApiErrorState error={report.error} retry={() => void report.refetch()} />
            ) : (
              <>
                {!report.data.series.length && (
                  <p className="img-report__empty" role="status">
                    No eligible readings in {monthTitle(report.data.month)}.
                  </p>
                )}
                {report.data.series.length > 0 && body(report.data)}
              </>
            )}
          </div>
          {detail?.node(back)}
        </div>
        {report.data && (
          <footer className="img-report__footer">
            <p>{report.data.aggregation}</p>
          </footer>
        )}
      </section>
    </div>
  );
}

function Axis({ ticks, bottom, top }: { ticks: number[]; bottom: number; top: number }) {
  return (
    <div className="img-chart__axis" aria-hidden="true" data-cropped={bottom > 0 || undefined}>
      {/* A cropped axis says so: bar length is not proportional below the first tick. */}
      {bottom > 0 && (
        <svg className="img-chart__break" viewBox="0 0 12 8" aria-hidden="true">
          <path d="M0 3l3-2 3 2 3-2 3 2M0 7l3-2 3 2 3-2 3 2" fill="none" />
        </svg>
      )}
      {ticks.map((t) => (
        <span key={t} style={{ bottom: `${((t - bottom) / (top - bottom)) * 100}%` }}>
          {t.toFixed(1)}
        </span>
      ))}
    </div>
  );
}

function Grid({ ticks, bottom, top }: { ticks: number[]; bottom: number; top: number }) {
  return (
    <div className="img-chart__grid" aria-hidden="true">
      {ticks.map((t) => (
        <span key={t} style={{ bottom: `${((t - bottom) / (top - bottom)) * 100}%` }} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------- Overview IMG
function FamilyChart({
  data,
  metric,
  orient,
  selected,
  onSelect,
  reduced,
}: {
  data: ImgData;
  metric: Metric;
  orient: Orient;
  selected: string | null;
  onSelect: (id: string) => void;
  reduced: boolean;
}) {
  const headingId = useId();
  const groups = chartGroups(data, metric, orient);
  // Shared scale: the H and V charts of one measure read against the same axis.
  const ticks = croppedTicks(data.series.filter((s) => s.metric === metric));
  const [bottom, top] = [ticks[0], ticks[ticks.length - 1]];
  const unit = metric === "CF" ? "CF" : `${measureLabel(data.film_measure)} · µm`;
  const title = `Average ${metric === "CF" ? "CF" : "Film Thickness"} — ${orientLabel(orient)}`;
  return (
    <figure className="img-chart" aria-labelledby={headingId} data-chart={`${metric}-${orient}`}>
      <figcaption>
        <h3 id={headingId}>{title}</h3>
        <p>
          {unit}
          {bottom > 0 && (
            <span className="img-chart__crop"> · axis starts at {bottom.toFixed(1)}</span>
          )}
        </p>
      </figcaption>
      <div className="img-chart__plot">
        <Axis ticks={ticks} bottom={bottom} top={top} />
        <div className="img-chart__scroll">
          <div className="img-chart__groups">
            <Grid ticks={ticks} bottom={bottom} top={top} />
            {groups.map((group) => (
              <div
                key={group.plant}
                className="img-chart__group"
                role="group"
                aria-label={group.plant}
              >
                <div className="img-chart__slots">
                  {group.slots.length ? (
                    group.slots.map((s) => (
                      <Bar
                        key={`${s.plant_code}|${s.family_key}`}
                        id={s.id}
                        mean={s.mean}
                        height={s.mean === null ? 0 : (Number(s.mean) - bottom) / (top - bottom)}
                        label={s.family_name}
                        reason={emptyReason(s)}
                        aria={`${s.plant_code} ${s.family_name}: ${
                          s.mean === null
                            ? emptyReason(s)
                            : `average ${displayMean1(s.mean)} ${unit}, ${countText(s.included_count, s.count_unit)}`
                        }. Show details.`}
                        pressed={selected === s.id}
                        onSelect={onSelect}
                        reduced={reduced}
                      />
                    ))
                  ) : (
                    <p className="img-chart__none">
                      No {metric === "CF" ? "Wave Scan" : "Film"} measurements
                    </p>
                  )}
                </div>
                <strong className="img-chart__plant">{group.plant}</strong>
              </div>
            ))}
          </div>
        </div>
      </div>
    </figure>
  );
}

function Bar({
  id,
  mean,
  height,
  label,
  sublabel,
  plant,
  reason,
  aria,
  pressed,
  onSelect,
  reduced,
}: {
  id: string;
  mean: string | null;
  height: number;
  label: string;
  sublabel?: string;
  plant?: string;
  reason: string;
  aria: string;
  pressed: boolean;
  onSelect: (id: string) => void;
  reduced: boolean;
}) {
  return (
    <button
      type="button"
      className="img-bar"
      data-series={id}
      data-empty={mean === null || undefined}
      data-plant={plant}
      aria-pressed={pressed}
      aria-label={aria}
      onClick={() => onSelect(id)}
    >
      <span className="img-bar__zone">
        {mean === null ? (
          <span className="img-bar__reason">{reason}</span>
        ) : (
          <span
            className="img-bar__fill"
            data-reduced={reduced || undefined}
            style={{ "--h": `${Math.max(0, height) * 100}%` } as CSSProperties}
          >
            <span className="img-bar__value num">{displayMean1(mean)}</span>
          </span>
        )}
      </span>
      <span className="img-bar__family" title={sublabel ? `${label} · ${sublabel}` : label}>
        {label}
        {sublabel && <small>{sublabel}</small>}
      </span>
    </button>
  );
}

/** Models the catalogue does not know are shown on their own; say so once, with where to fix it. */
function UnmappedNotice({ series }: { series: ImgSeries[] }) {
  const models = [...new Set(series.filter(isUnmapped).map((x) => x.family_name))];
  if (!models.length) return null;
  return (
    <p className="img-report__notice" role="note">
      Not in the model catalogue, so shown as their own bars: <strong>{models.join(", ")}</strong>.
      An Admin can attach {models.length === 1 ? "it" : "them"} to a family in{" "}
      <Link to="/admin">Admin</Link>.
    </p>
  );
}

// ------------------------------------------------------------- IMG Color
function ColourChart({
  data,
  scale,
  orient,
  selected,
  onSelect,
  reduced,
}: {
  data: ImgColors;
  /** The unfiltered report: filtering by plant never rescales the axis. */
  scale: ImgColors;
  orient: Orient;
  selected: string | null;
  onSelect: (id: string) => void;
  reduced: boolean;
}) {
  const headingId = useId();
  const bars = rankedColours(data, orient);
  // Zero-based, as the owner's ranking reference; H and V share one scale.
  const ticks = axisTicks(scale.series);
  const top = ticks[ticks.length - 1];
  return (
    <figure
      className="img-chart img-rank"
      aria-labelledby={headingId}
      data-chart={`COLOR-${orient}`}
    >
      <figcaption>
        <h3 id={headingId}>Average CF — {orientLabel(orient)}</h3>
        <p>Highest first · shared scale 0–{top} CF</p>
        <ul className="img-rank__legend" aria-label="Plant colours">
          {[...new Set(bars.map((b) => b.plant_code))].map((code) => (
            <li key={code} data-plant={code}>
              {code}
            </li>
          ))}
        </ul>
      </figcaption>
      <div className="img-rank__rows" aria-label={`${orientLabel(orient)} colour ranking`}>
        {bars.length ? (
          bars.map((s, i) => (
            <button
              type="button"
              className="img-rank__row"
              key={s.id}
              data-series={s.id}
              data-plant={s.plant_code}
              data-empty={s.mean === null || undefined}
              aria-label={`Rank ${i + 1}: ${s.color_name}, ${s.plant_code}: ${
                s.mean === null
                  ? colourReason(s)
                  : `${displayMean1(s.mean)} CF, ${countText(s.included_count, s.count_unit)}`
              }. Show details.`}
              aria-pressed={selected === s.id}
              onClick={() => onSelect(s.id)}
            >
              <span className="img-rank__number" aria-hidden="true">
                {i + 1}
              </span>
              <span className="img-rank__name">
                {s.color_name}
                <small>
                  {s.plant_code} · {countText(s.included_count, s.count_unit)}
                </small>
              </span>
              <span className="img-rank__track" aria-hidden="true">
                {s.mean !== null && (
                  <span
                    className="img-rank__fill"
                    style={{
                      transform: `scaleX(${Math.max(0, Math.min(1, Number(s.mean) / top))})`,
                    }}
                    data-reduced={reduced || undefined}
                  />
                )}
              </span>
              <span className="img-rank__value">
                {s.mean === null ? (
                  colourReason(s)
                ) : (
                  <>
                    {displayMean1(s.mean)}
                    <small>CF</small>
                  </>
                )}
              </span>
            </button>
          ))
        ) : (
          <p className="img-report__empty" role="status">
            No matching CF readings. Try another plant, colour or month.
          </p>
        )}
      </div>
    </figure>
  );
}

function colourReason(s: ImgColorSeries): string {
  const total = exclusionsOf(s).reduce((n, e) => n + e.count, 0);
  return s.availability === "EXCLUDED_OR_INCOMPLETE"
    ? `Excluded · ${total.toLocaleString("en-US")}`
    : "No CF readings";
}

// ---------------------------------------------------------------- detail
function Detail({
  title,
  context,
  series: s,
  unit,
  colours,
  unmapped,
  onClose,
}: {
  title: string;
  context: string;
  series: ImgSeries | ImgColorSeries;
  unit: string;
  colours?: { key: string; included_count: number }[];
  unmapped?: boolean;
  onClose: () => void;
}) {
  const exclusions = exclusionsOf(s);
  const heading = useRef<HTMLHeadingElement>(null);
  // Keyboard and screen-reader users land on what they asked for; Close details returns them.
  useEffect(() => heading.current?.focus(), [s.id]);
  return (
    <aside className="img-detail" aria-label={`${title.replace(" · ", " ")} detail`}>
      <div className="img-detail__head">
        <div>
          <h3 ref={heading} tabIndex={-1}>
            {title}
          </h3>
          <p>{context}</p>
        </div>
        <button type="button" onClick={onClose}>
          Close details
        </button>
      </div>
      <dl className="img-detail__facts">
        <div>
          <dt>Average</dt>
          <dd className="num">{s.mean === null ? "No average" : `${s.mean} ${unit}`}</dd>
        </div>
        <div>
          <dt>Included</dt>
          <dd className="num">{countText(s.included_count, s.count_unit)}</dd>
        </div>
        {unmapped && (
          <div>
            <dt>Family</dt>
            <dd>Not in the model catalogue; shown on its own</dd>
          </div>
        )}
      </dl>
      <Section title="Exclusions">
        {exclusions.length ? (
          exclusions.map((e) => <Row key={e.key} label={e.label} count={e.count} />)
        ) : (
          <li className="img-detail__muted">None</li>
        )}
      </Section>
      <Section title="Member models">
        {s.member_models.map((m) => (
          <Row
            key={m.model_code}
            label={
              m.model_name === m.model_code ? m.model_code : `${m.model_name} (${m.model_code})`
            }
            count={s.models.find((c) => c.key === m.model_code)?.included_count ?? 0}
          />
        ))}
      </Section>
      {colours && (
        <Section title="Colours">
          {colours.length ? (
            colours.map((c) => <Row key={c.key} label={c.key} count={c.included_count} />)
          ) : (
            <li className="img-detail__muted">None included</li>
          )}
        </Section>
      )}
      <Section title="Measurement locations">
        {s.locations.length ? (
          s.locations.map((c) => <Row key={c.key} label={c.key} count={c.included_count} />)
        ) : (
          <li className="img-detail__muted">None included</li>
        )}
      </Section>
      {s.exclusions.UNKNOWN_ORIENTATION > 0 && (
        <p className="img-detail__note">
          Readings with no H/V orientation are disclosed on both the Horizontal and the Vertical bar
          of this group; the two counts are the same readings, not additional ones.
        </p>
      )}
      <p className="img-detail__note">
        Each list counts the same {s.count_unit === "CF_READING" ? "readings" : "inclusions"}; the
        lists overlap and are not added together.
      </p>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="img-detail__section">
      <h4>{title}</h4>
      <ul>{children}</ul>
    </section>
  );
}

function Row({ label, count }: { label: string; count: number }) {
  return (
    <li>
      <span>{label}</span>
      <span className="num">{count.toLocaleString("en-US")}</span>
    </li>
  );
}
