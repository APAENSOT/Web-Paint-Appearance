/**
 * AR03 section 5: a pure slide plan built from the API responses.
 *
 * No statistic and no status is computed here: boxes, statuses and numbers
 * are the report's and the overviews' fields. Model charts are the Monthly
 * Overview charts themselves, captured by id at export. Finding lines reuse the
 * backend's template 2 / 3 wording scoped to one model (x layer), filled with
 * counts of the API's statuses. Counts only, never a share (D-AR03-10).
 */

import type { components } from "@/api/types";
import { filmWarningLabel } from "@/features/filmthickness/film-status";
import type { ChartBox } from "./ReportBoxPlot";
import type { AnalysisReport, AssistantAnswer, BandKey } from "./report-types";

type OverviewBox = components["schemas"]["OverviewBox"];
type FilmOverviewBox = components["schemas"]["FilmOverviewBox"];

/** What a deck can include; the page itself always shows every part. */
export const SECTIONS = [
  { id: "glance", label: "Boxplot slide per model and layer" },
  { id: "bands", label: "Wave Scan bands" },
  { id: "relationships", label: "Relationships" },
  { id: "summary", label: "Observation & Summary" },
] as const;
export type SectionId = (typeof SECTIONS)[number]["id"];

export const HEADER = "IMG VME Paint";
export const LAYER_WORD: Record<string, string> = {
  ECOAT: "E-coat",
  PRIMER: "Primer",
  BASE: "Base",
  CLEAR: "Clear",
};
export const BAND_WORD: Record<BandKey, string> = {
  du: "du",
  wa: "Wa",
  wb: "Wb",
  wc: "Wc",
  wd: "Wd",
  we: "We",
  cf: "CF",
};
export const RULE_OF_THUMB = "Rule of thumb (VOME PAM 2016, slide 19)";
const RULE_BANDS: BandKey[] = ["wa", "wb", "wc", "wd"];
export const BAND_NOTES: Partial<
  Record<BandKey, { range: string; note: string; pointsTo: string }>
> = {
  du: {
    range: "< 0.1 mm",
    note: "clear coat too thin or milky, poor flow, or sprayed too dry.",
    pointsTo: "Clear.",
  },
  wa: {
    range: "0.1–0.3 mm",
    note: "dry spray, or base coat too heavy.",
    pointsTo: "Clear.",
  },
  wb: {
    range: "0.3–1 mm",
    note: "base coat too heavy, or rough layers underneath (e-coat, substrate).",
    pointsTo: "Clear, Base.",
  },
  wc: {
    range: "1–3 mm",
    note: "rarely the booth unless it is a repair; rheology set too high, sanding marks, dry large-droplet primer overspray, or very rough e-coat or substrate.",
    pointsTo: "Base.",
  },
  wd: {
    range: "3–10 mm",
    note: "rheology set too high, substrate smoothness, or poor 2K mixing.",
    pointsTo: "Primer, Substrate.",
  },
  we: { range: "10–30 mm", note: "substrate structure.", pointsTo: "E-coat, Substrate." },
};
export const bandNoteText = (band: BandKey) => {
  const n = BAND_NOTES[band];
  return n ? `${BAND_WORD[band]} (${n.range}): ${n.note} Points to: ${n.pointsTo}` : "";
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const mon = (month: string) => MONTHS[Number(month.slice(5, 7)) - 1];
export const monYear = (month: string) => `${mon(month)} ${month.slice(0, 4)}`;
export const monShort = (month: string) => `${mon(month)}'${month.slice(2, 4)}`;
export const exportDate = (d: Date) =>
  `${MONTHS[d.getMonth()]}.${String(d.getDate()).padStart(2, "0")}.${d.getFullYear()}`;
export const fmt = (x: string | number) => Number(x).toFixed(1);

// ------------------------------------------------------------------ charts
export const filmLines = (b: FilmOverviewBox) =>
  (
    [
      [b.lo_label, b.lo],
      [b.hi_label, b.hi],
      [b.target_label, b.target],
    ] as const
  )
    .filter(([label, v]) => label && v != null)
    .map(([label, v]) => ({ label: label!, value: +v! }));

type BandBoxIn = NonNullable<NonNullable<AnalysisReport["bands"]>["bands"][number]["all"]>;
export function bandChartBox(label: string, b: BandBoxIn, band?: BandKey): ChartBox {
  return {
    label,
    n: b.n,
    q1: +b.q1,
    median: +b.median,
    q3: +b.q3,
    whiskerLo: +b.whisker_lo,
    whiskerHi: +b.whisker_hi,
    mean: +b.mean,
    outliers: b.outliers.map(Number),
    values: b.values?.map(Number) ?? null,
    lines:
      band && RULE_BANDS.includes(band)
        ? [15, 25, 40].map((v) => ({ label: "Rule", value: v }))
        : [],
  };
}

// ------------------------------------------------------------------ findings
type Counted = { status?: string | null };
const count = (boxes: Counted[], code: string | null) =>
  boxes.filter((b) => (b.status ?? null) === code).length;

/** Backend template 2, scoped to one model's Wave Scan boxes. */
export function wsFinding(boxes: OverviewBox[]): string {
  const below = boxes.reduce((sum, b) => sum + b.below_minimum.length, 0);
  return `Wave Scan: ${count(boxes, "PASS")} of ${boxes.length} boxes Pass, ${count(boxes, "WARNING")} Acceptable, ${count(boxes, "FAIL")} Fail; ${below} readings below the minimum.`;
}

/** Backend template 3, scoped to one model x layer. */
export function filmFinding(layer: string, boxes: FilmOverviewBox[]): string {
  const word = LAYER_WORD[layer] ?? layer;
  const pass = count(boxes, "PASS");
  if (pass === boxes.length) return `${word}: all ${boxes.length} boxes Pass.`;
  return `${word}: ${boxes.length - pass} of ${boxes.length} boxes not Pass (${count(boxes, "WARNING")} ${filmWarningLabel(layer)}, ${count(boxes, "FAIL")} Fail, ${count(boxes, "OVER")} Over).`;
}

const unique = <T>(xs: T[]) => [...new Set(xs)];
const byModel = <T extends { model_code: string }>(boxes: T[]) =>
  unique(boxes.map((b) => b.model_code)).map((model) => ({
    model,
    boxes: boxes.filter((b) => b.model_code === model),
  }));

// ------------------------------------------------------------------ observations
export type ObservationRow = {
  key: string;
  priority: number;
  domain: "wavescan" | "film";
  layer: string | null;
  model: string;
  where: string;
  observation: string;
  issues: number;
  /** The worst status among this group's non-Pass boxes, as the API sent it. */
  status: AnalysisReport["issues"][number]["status"];
  /** Readings listed below Minimum / beyond a line, summed over the group. */
  readings: number;
};
const RANK: Record<string, number> = { FAIL: 0, OVER: 1, WARNING: 2 };

export function observationRows(
  report: AnalysisReport,
  wsBoxes: OverviewBox[],
  filmBoxes: FilmOverviewBox[],
): ObservationRow[] {
  const groups = new Map<string, AnalysisReport["issues"]>();
  for (const i of report.issues) {
    const key = `${i.domain}|${i.model}|${i.layer ?? ""}`;
    groups.set(key, [...(groups.get(key) ?? []), i]);
  }
  return [...groups.entries()]
    .map(([key, items]) => {
      const { domain, model, layer } = items[0];
      const worst = Math.min(...items.map((i) => RANK[i.status ?? ""] ?? 3));
      return {
        key,
        worst,
        domain,
        layer,
        status: items.find((i) => (RANK[i.status ?? ""] ?? 3) === worst)!.status,
        readings: items.reduce((sum, i) => sum + i.points.length, 0),
        model,
        where: domain === "wavescan" ? "Wave Scan" : `Film ${LAYER_WORD[layer!] ?? layer}`,
        observation:
          domain === "wavescan"
            ? wsFinding(wsBoxes.filter((b) => b.model_code === model))
            : filmFinding(
                layer!,
                filmBoxes.filter((b) => b.model_code === model && b.layer_code === layer),
              ),
        issues: items.length,
      };
    })
    .sort((a, b) => a.worst - b.worst || b.issues - a.issues)
    .map(({ worst: _worst, ...row }, i) => ({ ...row, priority: i + 1 }));
}

// ------------------------------------------------------------------ plan
/** A Monthly Overview chart (captured by id at export), or a band chart drawn from `boxes`. */
export type ChartSpec = { id: string; title: string; boxes?: ChartBox[]; note?: string };
export const wsChartId = (model: string) => `ws|${model}`;
export const filmChartId = (model: string, layer: string) => `film|${model}|${layer}`;
export type SlideSpec =
  | { kind: "title"; date: string; title: string; subtitle: string }
  | { kind: "chart"; title: string; charts: ChartSpec[]; spec: string[]; finding: string }
  | {
      kind: "relationships";
      title: string;
      matrix: string[][];
      strongest: string[][];
      lines: string[];
    }
  | { kind: "observations"; title: string; rows: string[][] }
  | { kind: "notes"; title: string; nextSteps: string[]; summary: string[] };

export type SlideChoices = {
  sections: Record<SectionId, boolean>;
  remarks: Record<string, string>;
  nextSteps: string[];
  date: Date;
};

export const EXPLORATORY = (n: number) => `Exploratory, ${n} paired cars`;
export const PREDICTIVE_NOTE = (n: number) =>
  `A predictive model needs about 100 cars measured on both instruments; today ${n}.`;

export function buildSlidePlan(
  input: { report: AnalysisReport; wavescan: OverviewBox[]; film: FilmOverviewBox[] },
  choices: SlideChoices,
): SlideSpec[] {
  const { report, wavescan, film } = input;
  const plant = report.plant_code;
  const month = report.month ?? "";
  const on = choices.sections;
  const slides: SlideSpec[] = [
    {
      kind: "title",
      date: exportDate(choices.date),
      title: month ? `${plant} Paint Quality ${monYear(month)}` : `${plant} Paint Quality`,
      subtitle: HEADER,
    },
  ];
  if (!month) return slides;

  if (on.glance) {
    for (const { model, boxes } of byModel(wavescan)) {
      slides.push({
        kind: "chart",
        title: `${plant} ${model} Wave Scan CF – ${monShort(month)}`,
        charts: [{ id: wsChartId(model), title: `${model} CF` }],
        spec: unique(
          boxes
            .filter((b) => b.ford != null)
            .map(
              (b) =>
                `${b.family_code ?? b.color_name} ${b.orient[0]}: Standard ${fmt(b.ford!)}, Minimum ${fmt(b.minimum!)}`,
            ),
        ),
        finding: wsFinding(boxes),
      });
    }
  }
  if (on.bands && report.bands && report.bands.n_readings > 0) {
    const bands = report.bands.bands
      .filter((b) => b.all)
      .map((b) => ({ ...b, band: b.band as BandKey }));
    const top = bands
      .filter((b) => BAND_NOTES[b.band])
      .reduce<(typeof bands)[number] | null>(
        (best, b) => (!best || +b.all!.median > +best.all!.median ? b : best),
        null,
      );
    slides.push({
      kind: "chart",
      title: `${plant} Wave Scan bands – ${monShort(month)}`,
      charts: [
        {
          id: "bands",
          title: "Wave Scan bands",
          boxes: bands
            .filter((b) => b.band !== "cf")
            .map((b) => bandChartBox(BAND_WORD[b.band], b.all!, b.band)),
          note: RULE_OF_THUMB,
        },
        ...bands
          .filter((b) => b.band === "cf")
          .map((b) => ({ id: "cf", title: "CF", boxes: [bandChartBox("CF", b.all!)] })),
      ],
      spec: [`${RULE_OF_THUMB}: 15 / 25 / 40 on Wa–Wd.`],
      finding: top ? bandNoteText(top.band) : "",
    });
  }
  if (on.glance) {
    for (const { model, boxes } of byModel(film)) {
      for (const layer of unique(boxes.map((b) => b.layer_code))) {
        const mine = boxes.filter((b) => b.layer_code === layer);
        slides.push({
          kind: "chart",
          title: `${plant} ${model} ${LAYER_WORD[layer]} FB – ${monShort(month)}`,
          charts: [{ id: filmChartId(model, layer), title: `${model} ${LAYER_WORD[layer]}` }],
          spec: unique(
            mine
              .filter((b) => filmLines(b).length)
              .map(
                (b) =>
                  `${b.standard_scope === "COLOR" ? `${b.color_name} ` : ""}${b.orient}: ${filmLines(
                    b,
                  )
                    .map((l) => `${l.label} ${fmt(l.value)}`)
                    .join(", ")}`,
              ),
          ),
          finding: filmFinding(layer, mine),
        });
      }
    }
  }
  const rel = report.relationships;
  if (on.relationships && (rel.wavescan || rel.film || rel.strongest.length)) {
    const m = rel.wavescan;
    const params = (m?.params ?? []).map((p) => BAND_WORD[p as BandKey] ?? p);
    slides.push({
      kind: "relationships",
      title: `${plant} Relationships – ${monShort(month)}`,
      matrix: m
        ? [
            ["", ...params],
            ...m.rho.map((row, i) => [
              params[i],
              ...row.map((r, j) =>
                r == null ? `– (n ${m.n[i][j]})` : `${fmt(r)} (n ${m.n[i][j]})`,
              ),
            ]),
          ]
        : [],
      strongest: [
        ["A", "B", "Scope", "rho", "n"],
        ...rel.strongest.map((s) => [
          s.a,
          s.b,
          s.scope === "paired"
            ? EXPLORATORY(rel.paired?.cars ?? 0)
            : s.scope === "film"
              ? "Film"
              : "Wave Scan",
          fmt(s.rho),
          String(s.n),
        ]),
      ],
      lines:
        rel.paired && rel.paired.cars < 100
          ? [EXPLORATORY(rel.paired.cars), PREDICTIVE_NOTE(rel.paired.cars)]
          : [],
    });
  }
  if (on.summary) {
    slides.push({
      kind: "observations",
      title: "Observation & Summary",
      rows: [
        ["Priority", "Model", "Layer / Domain", "Observation", "Remark"],
        ...observationRows(report, wavescan, film).map((r) => [
          String(r.priority),
          r.model,
          r.where,
          r.observation,
          choices.remarks[r.key] ?? "",
        ]),
      ],
    });
    slides.push({
      kind: "notes",
      title: "Observation & Summary",
      nextSteps: choices.nextSteps.filter((s) => s.trim()),
      summary: report.summary,
    });
  }
  return slides;
}

// ------------------------------------------------------------------ AR04
export const riskLine = (r: NonNullable<AssistantAnswer["risk"]>) =>
  `If not fixed: about ${r.expected_out} of the next ${r.of_next} cars out`;

/** "2026-10" -> "October 2026". */
export const monthWords = (m: string) =>
  new Date(`${m}-01T00:00:00`).toLocaleString("en", { month: "long", year: "numeric" });
export const evidenceCell = (c: string | number | null) =>
  c === null || c === "" ? "—" : String(c);

/** One assistant answer as a notes slide, in the API's own words, with its top 5 evidence rows. */
export function answerSlide(a: AssistantAnswer): SlideSpec {
  return {
    kind: "notes",
    title: a.month ? `${a.decision.headline} — ${monthWords(a.month)}` : a.decision.headline,
    nextSteps: a.next_step ? [a.next_step] : [],
    summary: [
      ...(a.explanation ? [a.explanation] : []),
      a.proof,
      ...(a.risk ? [riskLine(a.risk)] : []),
      `Method: ${a.method.rule}`,
      ...a.evidence.rows.slice(0, 5).map((r) => r.map(evidenceCell).join(" · ")),
    ],
  };
}

/** Answer slides go before the observations table (at the end when there is none). */
export function withAssistantSlides(plan: SlideSpec[], extra: SlideSpec[]): SlideSpec[] {
  const at = plan.findIndex((s) => s.kind === "observations");
  const i = at < 0 ? plan.length : at;
  return [...plan.slice(0, i), ...extra, ...plan.slice(i)];
}
