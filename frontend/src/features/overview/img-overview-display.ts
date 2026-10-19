import type { components } from "@/api/types";

export type ImgOverview = components["schemas"]["ImgOverviewOut"];
export type ImgSeries = components["schemas"]["ImgSeries"];
export type FilmMeasure = ImgOverview["film_measure"];
export type Metric = ImgSeries["metric"];
export type Orient = ImgSeries["orient"];

export const PLANT_ORDER = ["FTM", "FVL", "SAP", "AAT"] as const;

export const FILM_MEASURES: { value: FilmMeasure; label: string }[] = [
  { value: "ECOAT", label: "Ecoat" },
  { value: "PRIMER", label: "Primer" },
  { value: "BASE", label: "Base" },
  { value: "CLEAR", label: "Clear" },
  { value: "CALCULATED_TOTAL", label: "Calculated Total" },
];

export const measureLabel = (measure: FilmMeasure) =>
  FILM_MEASURES.find((m) => m.value === measure)?.label ?? measure;

export const orientLabel = (orient: Orient) => (orient === "H" ? "Horizontal" : "Vertical");

export const COUNT_UNIT: Record<ImgSeries["count_unit"], [string, string]> = {
  CF_READING: ["CF reading", "CF readings"],
  LAYER_READING: ["layer reading", "layer readings"],
  FILM_POINT: ["complete point", "complete points"],
};

export const countText = (n: number, unit: ImgSeries["count_unit"]) =>
  `${n.toLocaleString("en-US")} ${COUNT_UNIT[unit][n === 1 ? 0 : 1]}`;

export const EXCLUSION_LABEL: Record<keyof ImgSeries["exclusions"], string> = {
  SETTING_EXCLUDED: "Excluded by point settings",
  INCOMPLETE_TOTAL: "Missing a layer (not in Total)",
  UNKNOWN_ORIENTATION: "No H/V orientation",
  INVALID_VALUE: "Invalid value",
  DUPLICATE_LAYER: "Duplicate layer at one point",
};

export const exclusionsOf = (s: Pick<ImgSeries, "exclusions">) =>
  (Object.keys(EXCLUSION_LABEL) as (keyof ImgSeries["exclusions"])[])
    .map((key) => ({ key, label: EXCLUSION_LABEL[key], count: s.exclusions[key] }))
    .filter((e) => e.count > 0);

/** Display only: the returned decimal string, shown to two places. The exact string stays in detail. */
export function displayMean(mean: string): string {
  const value = Number(mean);
  return Number.isFinite(value) ? value.toFixed(2) : mean;
}

/** Short reason for a slot that has no bar. Never a zero. */
export function emptyReason(s: ImgSeries): string {
  if (s.availability === "EXCLUDED_OR_INCOMPLETE") {
    const total = exclusionsOf(s).reduce((n, e) => n + e.count, 0);
    return `Excluded · ${total.toLocaleString("en-US")}`;
  }
  return "No readings";
}

export const isUnmapped = (s: ImgSeries) => s.family_key.startsWith("UNMAPPED:");

export type PlantGroup = { plant: string; slots: ImgSeries[] };

/**
 * One chart's x-axis: plants in FTM/FVL/SAP/AAT order (visible ones only), each with its
 * families in the order the API returned them. A visible plant with nothing in this domain
 * keeps its place with no slots, so the chart can say so instead of drawing a zero.
 */
export function chartGroups(data: ImgOverview, metric: Metric, orient: Orient): PlantGroup[] {
  return PLANT_ORDER.filter((p) => data.plants.includes(p)).map((plant) => ({
    plant,
    slots: data.series.filter(
      (s) => s.plant_code === plant && s.metric === metric && s.orient === orient,
    ),
  }));
}

/** Zero-based "nice" axis shared by the H and V charts of one measure. */
export function axisTicks(series: { mean: string | null }[]): number[] {
  const top = Math.max(0, ...series.map((s) => (s.mean === null ? 0 : Number(s.mean))));
  if (!(top > 0)) return [0, 25, 50, 75, 100];
  const rough = top / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? 10 * power;
  const ticks: number[] = [];
  for (let t = 0; t < top + step * 0.001; t += step) ticks.push(Number(t.toFixed(6)));
  if (ticks[ticks.length - 1] < top)
    ticks.push(Number((ticks[ticks.length - 1] + step).toFixed(6)));
  return ticks;
}

/** The month to show: the kept choice while it is still listed, else the newest. */
export const effectiveMonth = (months: string[], chosen: string | null) =>
  chosen !== null && months.includes(chosen) ? chosen : (months[0] ?? null);

/** Display only: one decimal, as the owner's Overview IMG reference shows. The exact string stays in detail. */
export function displayMean1(mean: string): string {
  const value = Number(mean);
  return Number.isFinite(value) ? value.toFixed(1) : mean;
}

/**
 * Overview IMG axis, like the owner's reference: starts a step or two below the lowest returned
 * mean so plant-to-plant differences read, ends just above the highest. Shared by H and V.
 */
export function croppedTicks(series: { mean: string | null }[]): number[] {
  const values = series.flatMap((s) => (s.mean === null ? [] : [Number(s.mean)]));
  if (!values.length) return [0, 25, 50, 75, 100];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const rough = Math.max(hi - lo, hi * 0.1) / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? 10 * power;
  const bottom = Math.max(0, Math.floor(lo / step) * step - step);
  let top = Math.ceil(hi / step) * step;
  if (top - hi < step * 0.25) top += step;
  const ticks: number[] = [];
  for (let t = bottom; t <= top + step * 0.001; t += step) ticks.push(Number(t.toFixed(6)));
  return ticks;
}

export type ImgColors = components["schemas"]["ImgColorsOut"];
export type ImgColorSeries = components["schemas"]["ImgColorSeries"];

/** IMG Color: one orientation's bars in the API's rank order (descending, nulls last). */
export const rankedColours = (data: ImgColors, orient: Orient) =>
  data.series.filter((s) => s.orient === orient);
