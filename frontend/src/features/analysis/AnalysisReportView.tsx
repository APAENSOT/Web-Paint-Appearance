/**
 * AR03: the Analysis & Report page as a pure view of the API responses.
 *
 * Operator first: a verdict per area, then the boxes that need attention,
 * most serious first, each opening onto the dashboard's own Monthly Overview
 * chart (passed in as `chartFor`) and the readings that are out. The
 * summary, the deeper analysis and the slide builder follow. Every number,
 * status and sentence is an API field (D-AR03-8); counts only (D-AR03-10).
 */

import type { ReactNode } from "react";
import { ChevronRight, Download, SlidersHorizontal } from "lucide-react";
import type { components } from "@/api/types";
import { filmWarningLabel } from "@/features/filmthickness/film-status";
import { statusLabel } from "@/features/measurements/overview-display";
import {
  statusPresentation,
  type FilmOverviewData,
} from "@/features/filmthickness/film-overview-display";
import { ReportBoxPlot } from "./ReportBoxPlot";
import {
  BAND_NOTES,
  BAND_WORD,
  EXPLORATORY,
  LAYER_WORD,
  PREDICTIVE_NOTE,
  RULE_OF_THUMB,
  SECTIONS,
  bandChartBox,
  bandNoteText,
  fmt,
  observationRows,
  type ObservationRow,
  type SectionId,
} from "./report-slides";
import type { AnalysisReport, AnalysisReportQuery, BandKey, Matrix } from "./report-types";

export type WavescanData = components["schemas"]["WavescanOverviewOut"];
export type Code = AnalysisReport["issues"][number]["status"];
export type Sections = Record<SectionId, boolean>;

const COPY = {
  bandsSub:
    "Wave Scan bands for the month you pick. Counted readings. Lower is better in every band. No grade or pass rate.",
  bandsEmpty: "No counted Wave Scan readings for this selection.",
  noMonth: "No Wave Scan or Film readings at this plant yet.",
  allPass: "Every box is Pass this month. Nothing needs attention.",
};

const longMonth = (m: string) =>
  new Date(`${m}-01T00:00:00`).toLocaleString("en", { month: "long", year: "numeric" });
const orientWord = (o: string) => (o === "H" ? "Horizontal" : "Vertical");
// The site's words; OVER exists on Film only, so statusLabel (Wave Scan) never sees it.
const codeWord = (code: Code, layer?: string | null) =>
  code === "WARNING" && layer
    ? filmWarningLabel(layer)
    : code === "OVER"
      ? "Over"
      : statusLabel(code);
const boxKey = (layer: string | null, model: string, color: string, orient: string) =>
  `${layer ?? ""}|${model}|${color}|${orient}`;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// ------------------------------------------------------------------ view
export type ViewProps = {
  report: AnalysisReport;
  wavescanData?: WavescanData;
  filmData?: FilmOverviewData;
  sections: Sections;
  onToggle: (id: SectionId) => void;
  query: AnalysisReportQuery;
  onQuery: (q: AnalysisReportQuery) => void;
  remarks: Record<string, string>;
  onRemark: (key: string, value: string) => void;
  nextSteps: string;
  onNextSteps: (v: string) => void;
  onExport: () => void;
  exporting: boolean;
  exportError?: string | null;
  chartFor: (row: ObservationRow) => ReactNode;
  pairing?: ReactNode;
  assistant?: ReactNode;
};

export function AnalysisReportView(props: ViewProps) {
  const { report } = props;
  const rows = observationRows(
    report,
    props.wavescanData?.boxes ?? [],
    props.filmData?.boxes ?? [],
  );
  return (
    <div className="ar03 grid min-w-0 gap-3" data-testid="analysis-workspace">
      <Header {...props} />
      {props.assistant}
      {!report.month ? (
        <p className="panel p-5 text-sm">{COPY.noMonth}</p>
      ) : (
        <>
          <details className="min-w-0" data-testid="full-data">
            <summary className="panel flex min-h-14 items-center gap-3 px-4 py-3 font-bold sm:px-5">
              <ChevronRight
                className="ar03-chevron size-4 shrink-0 text-muted-foreground"
                aria-hidden
              />
              Full data
            </summary>
            <div className="mt-3 grid min-w-0 gap-3">
              <Verdict report={report} />
              <Attention {...props} rows={rows} />
              <Summary report={report} />
              <Detail
                id="comparison"
                title="This month and last month"
                hint={`${report.comparison.length} boxes, ${report.previous_month} to ${report.month}`}
              >
                <Comparison report={report} />
              </Detail>
              {report.bands && (
                <Detail
                  id="bands"
                  title="Band diagnosis"
                  hint={`${report.bands.n_readings} counted readings on ${plural(report.bands.n_cars, "car")}`}
                >
                  <Bands bands={report.bands} />
                </Detail>
              )}
              <Detail
                id="relationships"
                title="How the parameters relate"
                hint="Spearman rho with n in every cell"
              >
                <Relationships report={report} />
              </Detail>
              {props.pairing && (
                <Detail
                  id="pairing"
                  title="Wave Scan and Film pairing"
                  hint="Cars measured on both instruments"
                >
                  {props.pairing}
                </Detail>
              )}
            </div>
          </details>
          <Slides {...props} rows={rows} />
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ header
function Header({ report, query, onQuery, onExport, exporting, exportError }: ViewProps) {
  const picked = report.models.length + report.colors.length;
  return (
    <section
      className="panel grid min-w-0 gap-4 p-4 sm:p-5"
      aria-label="Report choices"
      data-testid="analysis-controls"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-4">
            <div className="min-w-0">
              <p className="eyebrow">Analysis & Report</p>
              <h2 className="text-xl font-bold">
                {report.plant_code}
                {report.month ? ` · ${longMonth(report.month)}` : ""}
              </h2>
            </div>
          </div>
          {report.previous_month && (
            <p className="mt-1 text-sm text-muted-foreground">
              Compared with {longMonth(report.previous_month)}. Wave Scan counts counted readings;
              Film counts active readings.
            </p>
          )}
        </div>
        <button
          type="button"
          className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
          onClick={onExport}
          disabled={exporting || !report.month}
          aria-busy={exporting}
          data-testid="analysis-export"
        >
          <Download className="size-4" aria-hidden />
          {exporting ? "Building slides..." : "Export slides"}
        </button>
      </div>
      {exportError && (
        <p role="alert" className="text-sm text-[var(--critical)]">
          {exportError}
        </p>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-xs text-muted-foreground">
          Month
          <select
            aria-label="Month"
            className="min-h-11 rounded-md border border-border bg-transparent px-3 text-sm text-foreground"
            value={report.month ?? ""}
            onChange={(e) => onQuery({ ...query, month: e.target.value })}
          >
            {report.options.months.map((m) => (
              <option key={m} value={m}>
                {longMonth(m)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          Instrument
          <select
            aria-label="Instrument"
            className="min-h-11 rounded-md border border-border bg-transparent px-3 text-sm text-foreground"
            value={report.domain}
            onChange={(e) =>
              onQuery({ ...query, domain: e.target.value as AnalysisReportQuery["domain"] })
            }
          >
            <option value="both">Wave Scan and Film</option>
            <option value="wavescan">Wave Scan</option>
            <option value="film">Film</option>
          </select>
        </label>
        <details className="relative min-w-0">
          <summary className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border px-3 text-sm">
            <SlidersHorizontal className="size-4" aria-hidden />
            {picked ? `Models and colours (${picked} picked)` : "All models and colours"}
          </summary>
          <div className="mt-2 grid gap-3 rounded-md border border-border p-3">
            <MultiPick
              legend="Models"
              options={report.options.models}
              picked={report.models}
              onChange={(models) => onQuery({ ...query, models })}
            />
            <MultiPick
              legend="Colours"
              options={report.options.colors}
              picked={report.colors}
              onChange={(colors) => onQuery({ ...query, colors })}
            />
          </div>
        </details>
      </div>
    </section>
  );
}

function MultiPick({
  legend,
  options,
  picked,
  onChange,
}: {
  legend: string;
  options: string[];
  picked: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="text-xs text-muted-foreground">{legend} (none ticked means all)</legend>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {options.map((o) => (
          <label key={o} className="inline-flex min-h-8 items-center gap-2">
            <input
              type="checkbox"
              checked={picked.includes(o)}
              onChange={() =>
                onChange(picked.includes(o) ? picked.filter((p) => p !== o) : [...picked, o])
              }
            />
            {o}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

// ------------------------------------------------------------------ verdict
export function StatusChip({ code, word }: { code: Code; word?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 font-semibold whitespace-nowrap text-[var(--tone)]"
      data-tone={code ?? "NONE"}
    >
      <span className="size-2 shrink-0 rounded-full bg-[var(--tone)]" aria-hidden />
      {word ?? codeWord(code)}
    </span>
  );
}

type Tally = { code: Code; word: string; n: number };

function CountBar({ tally, label }: { tally: Tally[]; label: string }) {
  const shown = tally.filter((t) => t.n > 0);
  return (
    <div
      className="flex h-2.5 w-full overflow-hidden rounded-full bg-[var(--panel-sunken)]"
      role="img"
      aria-label={label}
    >
      {shown.map((t) => (
        <span
          key={t.word}
          data-tone={t.code ?? "NONE"}
          className="h-full bg-[var(--tone)]"
          style={{ flexGrow: t.n }}
        />
      ))}
    </div>
  );
}

function VerdictRow({
  area,
  tally,
  extra,
  before,
}: {
  area: string;
  tally: Tally[];
  extra?: string;
  before?: string;
}) {
  const total = tally.reduce((s, t) => s + t.n, 0);
  const notPass = tally.filter((t) => t.code !== "PASS" && t.n > 0);
  const text = notPass.length
    ? `${notPass.map((t) => `${t.n} ${t.word}`).join(", ")} of ${plural(total, "box", "boxes")}`
    : `All ${plural(total, "box", "boxes")} Pass`;
  return (
    <li
      className="grid gap-x-4 gap-y-1.5 py-3 sm:grid-cols-[8rem_minmax(8rem,14rem)_1fr] sm:items-center"
      data-verdict={area}
    >
      <span className="font-semibold">{area}</span>
      <CountBar tally={tally} label={`${area}: ${text}`} />
      <span className="text-sm">
        <span className={notPass.length ? "font-semibold" : "text-muted-foreground"}>{text}</span>
        {extra && <span className="text-muted-foreground">. {extra}</span>}
        {before && <span className="block text-xs text-muted-foreground">{before}</span>}
      </span>
    </li>
  );
}

const wsTally = (b: { PASS: number; WARNING: number; FAIL: number; NONE: number }): Tally[] => [
  { code: "FAIL", word: "Fail", n: b.FAIL },
  { code: "WARNING", word: "Acceptable", n: b.WARNING },
  { code: null, word: "No standard", n: b.NONE },
  { code: "PASS", word: "Pass", n: b.PASS },
];
const filmTally = (b: {
  layer?: string;
  PASS: number;
  WARNING: number;
  FAIL: number;
  OVER: number;
  NONE: number;
}): Tally[] => [
  { code: "FAIL", word: "Fail", n: b.FAIL },
  { code: "OVER", word: "Over", n: b.OVER },
  { code: "WARNING", word: filmWarningLabel(b.layer), n: b.WARNING },
  { code: null, word: "No standard or not graded", n: b.NONE },
  { code: "PASS", word: "Pass", n: b.PASS },
];
const tallyText = (t: Tally[]) =>
  t
    .filter((x) => x.n)
    .map((x) => `${x.n} ${x.word}`)
    .join(", ");

function Verdict({ report }: { report: AnalysisReport }) {
  const ws = report.glance.wavescan;
  const film = report.glance.film;
  const prev = report.previous_month ? longMonth(report.previous_month) : "last month";
  return (
    <section
      className="panel min-w-0 p-4 sm:p-5"
      data-section="glance"
      aria-label="This month at a glance"
    >
      <h3 className="text-lg font-bold">This month at a glance</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Box status from the dashboard: one box per model, colour and orientation.
        {ws && ` Wave Scan: ${ws.readings} readings on ${plural(ws.cars, "car")}.`}
        {film && ` Film: ${film.readings} readings on ${plural(film.cars, "car")}.`}
      </p>
      <ul className="mt-2 divide-y divide-border">
        {ws && (
          <VerdictRow
            area="Wave Scan"
            tally={wsTally(ws.boxes)}
            extra={`${ws.below_minimum} readings below their Minimum`}
            before={ws.previous ? `${prev}: ${tallyText(wsTally(ws.previous.boxes))}` : undefined}
          />
        )}
        {film?.boxes_by_layer.map((l) => {
          const p = film.previous?.boxes_by_layer.find((x) => x.layer === l.layer);
          return (
            <VerdictRow
              key={l.layer}
              area={LAYER_WORD[l.layer] ?? l.layer}
              tally={filmTally(l)}
              before={p ? `${prev}: ${tallyText(filmTally(p))}` : undefined}
            />
          );
        })}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------------ attention
function Attention({ report, filmData, chartFor, rows }: ViewProps & { rows: ObservationRow[] }) {
  const scope = new Map(
    (filmData?.boxes ?? []).map((b) => [
      boxKey(b.layer_code, b.model_code, b.color_name, b.orient),
      b,
    ]),
  );
  const word = (i: AnalysisReport["issues"][number]) => {
    const box = i.domain === "film" && scope.get(boxKey(i.layer, i.model, i.color, i.orient));
    return box ? statusPresentation(box).text : codeWord(i.status, i.layer);
  };
  return (
    <section
      className="panel min-w-0 p-4 sm:p-5"
      data-section="issues"
      aria-label="Needs attention"
    >
      <h3 className="text-lg font-bold">Needs attention</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {rows.length
          ? `${report.issues.length} boxes are not Pass, in ${plural(rows.length, "group")}. Most serious first: Fail, then Over, then Acceptable. Open a group for its Monthly Overview chart and the readings that are out.`
          : COPY.allPass}
      </p>
      <ol className="mt-3 divide-y divide-border border-y border-border">
        {rows.map((row, index) => {
          const issues = report.issues.filter(
            (i) => i.domain === row.domain && i.model === row.model && i.layer === row.layer,
          );
          return (
            <li key={row.key} data-problem={row.key}>
              <details open={index === 0}>
                <summary className="grid gap-x-4 gap-y-1 py-3 sm:grid-cols-[1.25rem_7.5rem_minmax(0,1fr)_auto] sm:items-center">
                  <ChevronRight
                    className="ar03-chevron hidden size-4 text-muted-foreground sm:block"
                    aria-hidden
                  />
                  <StatusChip code={row.status} word={codeWord(row.status, row.layer)} />
                  <span className="min-w-0">
                    <span className="font-semibold">{row.where}</span>
                    <span className="text-muted-foreground"> · {row.model}</span>
                    <span className="block text-sm">{row.observation}</span>
                  </span>
                  <span className="text-sm text-muted-foreground sm:text-right">
                    <span className="num text-foreground">{issues.length}</span> boxes
                    {row.readings > 0 && (
                      <>
                        {" · "}
                        <span className="num text-foreground">{row.readings}</span>{" "}
                        {row.domain === "wavescan" ? "below Minimum" : "beyond a line"}
                      </>
                    )}
                  </span>
                </summary>
                <div className="grid min-w-0 gap-4 pb-5 sm:pl-9">
                  {chartFor(row)}
                  <Table
                    caption={`${row.where} ${row.model}: boxes that are not Pass`}
                    heads={[
                      "Status",
                      "Colour",
                      "H / V",
                      "n",
                      "Mean",
                      "Median",
                      "Lines",
                      "Readings out",
                    ]}
                  >
                    {issues.map((i) => (
                      <tr
                        key={boxKey(i.layer, i.model, i.color, i.orient)}
                        className="border-t border-border"
                        data-issue={i.status ?? "NONE"}
                      >
                        <td className="px-3 py-2 align-top">
                          <StatusChip code={i.status} word={word(i)} />
                        </td>
                        <Td>{i.color}</Td>
                        <Td>{orientWord(i.orient)}</Td>
                        <Td num>{i.n}</Td>
                        <Td num>{fmt(i.mean)}</Td>
                        <Td num>{fmt(i.median)}</Td>
                        <Td>
                          {Object.entries(i.limits)
                            .map(([k, v]) => `${k} ${fmt(v)}`)
                            .join(", ") || "No standard"}
                        </Td>
                        <Td>
                          {i.points.length === 0 ? (
                            <span className="text-muted-foreground">None</span>
                          ) : (
                            <details>
                              <summary className="num underline decoration-dotted underline-offset-4">
                                {i.points.length} readings
                              </summary>
                              <ul className="mt-1 space-y-0.5">
                                {i.points.map((p, k) => (
                                  <li key={k} className="num whitespace-nowrap">
                                    {fmt(p.value)}{" "}
                                    {p.side === "HIGH" ? "high" : p.side === "LOW" ? "low" : ""} ·{" "}
                                    {p.point_code}
                                    {p.panel ? ` (${p.panel})` : ""} · car {p.car?.slice(0, 12)} ·{" "}
                                    {p.date}
                                  </li>
                                ))}
                              </ul>
                            </details>
                          )}
                        </Td>
                      </tr>
                    ))}
                  </Table>
                </div>
              </details>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Summary({ report }: { report: AnalysisReport }) {
  return (
    <section
      className="panel min-w-0 p-4 sm:p-5"
      data-section="summary"
      aria-label="What the numbers say"
    >
      <h3 className="text-lg font-bold">What the numbers say</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Key findings from this month's measurements. These findings also appear in your slides.
      </p>
      <ul
        className="mt-3 max-w-[75ch] list-disc space-y-1.5 pl-5 text-sm"
        data-testid="summary-sentences"
      >
        {report.summary.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------------ detail
function Detail({
  id,
  title,
  hint,
  children,
}: {
  id: string;
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <details className="panel min-w-0" data-section={id}>
      <summary className="flex min-h-14 items-center gap-3 px-4 py-3 sm:px-5">
        <ChevronRight className="ar03-chevron size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="font-bold">{title}</span>
        <span className="ml-auto text-right text-xs text-muted-foreground">{hint}</span>
      </summary>
      <div className="min-w-0 px-4 pb-5 sm:px-5">{children}</div>
    </details>
  );
}

function Table({
  heads,
  children,
  caption,
}: {
  heads: string[];
  children: ReactNode;
  caption: string;
}) {
  return (
    <div className="mt-3 overflow-x-auto rounded-md border border-border">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-[var(--surface-2)] text-muted-foreground">
          <tr>
            {heads.map((h) => (
              <th key={h} scope="col" className="px-3 py-2 font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

const Td = ({ children, num }: { children: ReactNode; num?: boolean }) => (
  <td className={`px-3 py-2 align-top ${num ? "num" : ""}`}>{children}</td>
);

function Comparison({ report }: { report: AnalysisReport }) {
  const word = (code: Code, mean: string | null, layer?: string | null) =>
    mean == null ? (
      <span className="text-muted-foreground">Not measured</span>
    ) : (
      <StatusChip code={code} word={codeWord(code, layer)} />
    );
  return (
    <Table
      caption="Box means and statuses, this month and last month"
      heads={[
        "Area",
        "Model",
        "Colour",
        "H / V",
        `Mean ${report.previous_month}`,
        `Mean ${report.month}`,
        "Change",
        `Status ${report.previous_month}`,
        `Status ${report.month}`,
      ]}
    >
      {report.comparison.map((r) => (
        <tr
          key={`${r.domain}|${boxKey(r.layer, r.model, r.color, r.orient)}`}
          className="border-t border-border"
        >
          <Td>{r.domain === "wavescan" ? "Wave Scan" : `Film ${LAYER_WORD[r.layer!]}`}</Td>
          <Td>{r.model}</Td>
          <Td>{r.color}</Td>
          <Td>{orientWord(r.orient)}</Td>
          <Td num>{r.mean_before == null ? "-" : fmt(r.mean_before)}</Td>
          <Td num>{r.mean_now == null ? "-" : fmt(r.mean_now)}</Td>
          <Td num>{r.mean_change == null ? "-" : fmt(r.mean_change)}</Td>
          <Td>{word(r.status_before, r.mean_before, r.layer)}</Td>
          <Td>{word(r.status_now, r.mean_now, r.layer)}</Td>
        </tr>
      ))}
    </Table>
  );
}

function Bands({ bands }: { bands: NonNullable<AnalysisReport["bands"]> }) {
  if (bands.n_readings === 0)
    return (
      <p className="text-sm" data-testid="bands-empty">
        {COPY.bandsEmpty}
      </p>
    );
  return (
    <>
      <p className="text-sm text-muted-foreground">{COPY.bandsSub}</p>
      <div className="mt-3 grid min-w-0 gap-6 lg:grid-cols-2">
        {bands.bands.map((raw) => {
          const b = { ...raw, band: raw.band as BandKey };
          const boxes = (
            [
              ["All", b.all],
              ["Horizontal", b.horizontal],
              ["Vertical", b.vertical],
            ] as const
          ).flatMap(([label, box]) => (box ? [bandChartBox(label, box, b.band)] : []));
          return (
            <figure key={b.band} className="min-w-0" data-band={b.band}>
              <figcaption className="text-sm font-semibold">{BAND_WORD[b.band]}</figcaption>
              <ReportBoxPlot
                title={`${BAND_WORD[b.band]} band`}
                boxes={boxes}
                width={480}
                height={380}
              />
              {["wa", "wb", "wc", "wd"].includes(b.band) && (
                <p className="text-xs text-muted-foreground">{RULE_OF_THUMB}</p>
              )}
              <p className="text-xs">
                n = {b.all?.n ?? 0}
                {b.previous_month_median != null &&
                  ` · Last month median ${fmt(b.previous_month_median)}`}
              </p>
              {BAND_NOTES[b.band] && (
                <p className="mt-1 max-w-[70ch] text-xs" data-band-note={b.band}>
                  {bandNoteText(b.band)}
                </p>
              )}
            </figure>
          );
        })}
      </div>
      <Table
        caption="Band medians per panel group"
        heads={["Panel", "n", ...Object.values(BAND_WORD)]}
      >
        {bands.panel_groups.map((g) => (
          <tr key={g.panel_group} className="border-t border-border">
            <th scope="row" className="px-3 py-2 font-medium">
              {g.panel_group}
            </th>
            <Td num>{g.n_readings}</Td>
            {(Object.keys(BAND_WORD) as BandKey[]).map((k) => (
              <Td key={k} num>
                {g.median[k] == null ? "-" : fmt(g.median[k]!)}
              </Td>
            ))}
          </tr>
        ))}
      </Table>
    </>
  );
}

function MatrixTable({ m, names, caption }: { m: Matrix; names: string[]; caption: string }) {
  return (
    <Table caption={caption} heads={["", ...names]}>
      {m.rho.map((row, i) => (
        <tr key={names[i]} className="border-t border-border">
          <th scope="row" className="px-3 py-2 font-medium">
            {names[i]}
          </th>
          {row.map((r, j) => (
            <td
              key={j}
              className="num px-3 py-2"
              style={{
                backgroundColor:
                  r == null ? undefined : `rgba(128,128,128,${(Math.abs(+r) * 0.5).toFixed(2)})`,
              }}
            >
              {r == null ? "-" : fmt(r)}
              <span className="block text-[10px] text-muted-foreground">n {m.n[i][j]}</span>
            </td>
          ))}
        </tr>
      ))}
    </Table>
  );
}

function Relationships({ report }: { report: AnalysisReport }) {
  const rel = report.relationships;
  const paired = rel.paired;
  return (
    <>
      <p className="text-sm text-muted-foreground">
        Spearman rank correlation (rho) with the number of pairs (n) in every cell. Statistics, not
        a trained model.
      </p>
      {rel.wavescan && (
        <MatrixTable
          m={rel.wavescan}
          names={rel.wavescan.params.map((p) => BAND_WORD[p as BandKey] ?? p)}
          caption="Wave Scan band correlations, one reading per pair"
        />
      )}
      {rel.film && (
        <MatrixTable
          m={rel.film}
          names={rel.film.params.map((p) => LAYER_WORD[p] ?? p)}
          caption="Film layer correlations, one car and point per pair"
        />
      )}
      <h4 className="mt-5 text-sm font-semibold">Strongest relationships</h4>
      <Table caption="Strongest relationships" heads={["A", "B", "Scope", "rho", "n", "Slope"]}>
        {rel.strongest.map((s) => (
          <tr key={`${s.scope}|${s.a}|${s.b}`} className="border-t border-border">
            <Td>{s.a}</Td>
            <Td>{s.b}</Td>
            <Td>
              {s.scope === "paired"
                ? EXPLORATORY(paired?.cars ?? 0)
                : s.scope === "film"
                  ? "Film"
                  : "Wave Scan"}
            </Td>
            <Td num>{fmt(s.rho)}</Td>
            <Td num>{s.n}</Td>
            <Td num>{s.slope == null ? "-" : s.slope}</Td>
          </tr>
        ))}
      </Table>
      {paired && (
        <>
          <h4 className="mt-5 text-sm font-semibold" data-testid="paired-label">
            Film and Wave Scan: {EXPLORATORY(paired.cars)}
          </h4>
          <p className="text-xs text-muted-foreground" data-testid="paired-note">
            {PREDICTIVE_NOTE(paired.cars)}
          </p>
          <Table
            caption="Film layer against Wave Scan band on the same car and panel"
            heads={["Film layer", "Wave Scan", "rho", "n"]}
          >
            {paired.rows.map((r) => (
              <tr key={`${r.film_layer}|${r.ws_param}`} className="border-t border-border">
                <Td>{LAYER_WORD[r.film_layer]}</Td>
                <Td>{BAND_WORD[r.ws_param as BandKey]}</Td>
                <Td num>{r.rho == null ? "-" : fmt(r.rho)}</Td>
                <Td num>{r.n}</Td>
              </tr>
            ))}
          </Table>
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------ slides
function Slides({
  sections,
  onToggle,
  remarks,
  onRemark,
  nextSteps,
  onNextSteps,
  rows,
}: ViewProps & { rows: ObservationRow[] }) {
  return (
    <section className="panel min-w-0 p-4 sm:p-5" data-section="slides" aria-label="Slide deck">
      <h3 className="text-lg font-bold">Slide deck</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Export slides builds a deck in the plant's Quality Report template, with the Monthly
        Overview boxplots. Choose what goes in, add remarks and next steps first.
      </p>
      <fieldset className="mt-3 min-w-0">
        <legend className="text-xs text-muted-foreground">Include</legend>
        <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {SECTIONS.map((s) => (
            <label key={s.id} className="inline-flex min-h-8 items-center gap-2">
              <input
                type="checkbox"
                checked={sections[s.id]}
                onChange={() => onToggle(s.id)}
                data-toggle={s.id}
              />
              {s.label}
            </label>
          ))}
        </div>
      </fieldset>
      <h4 className="mt-5 text-sm font-semibold">Observations, as they go on the slide</h4>
      <Table
        caption="Observation rows, most serious first"
        heads={["Priority", "Model", "Layer / Domain", "Observation", "Remark"]}
      >
        {rows.map((r) => (
          <tr key={r.key} className="border-t border-border">
            <Td num>{r.priority}</Td>
            <Td>{r.model}</Td>
            <Td>{r.where}</Td>
            <Td>{r.observation}</Td>
            <td className="px-3 py-2">
              <input
                className="min-h-9 w-44 rounded-md border border-border bg-transparent px-2"
                aria-label={`Remark for ${r.model} ${r.where}`}
                value={remarks[r.key] ?? ""}
                onChange={(e) => onRemark(r.key, e.target.value)}
              />
            </td>
          </tr>
        ))}
      </Table>
      <label className="mt-5 grid max-w-[75ch] gap-1 text-sm">
        Next steps, one per line
        <textarea
          className="min-h-24 rounded-md border border-border bg-transparent p-2"
          value={nextSteps}
          onChange={(e) => onNextSteps(e.target.value)}
        />
      </label>
    </section>
  );
}
