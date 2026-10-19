import type { components } from "@/api/types";
import { filmWarningLabel } from "./film-status";
import { pointText, type LabelOf } from "@/features/measurements/point-labels";

export type FilmOverviewData = components["schemas"]["FilmOverviewOut"];
export type FilmOverviewBox = components["schemas"]["FilmOverviewBox"];
export type FilmColorSequenceEntry = components["schemas"]["FilmColorSequenceEntry"];
export const FILM_LAYERS = [
  { code: "ECOAT", label: "E-coat" },
  { code: "PRIMER", label: "Primer" },
  { code: "BASE", label: "Base" },
  { code: "CLEAR", label: "Clear" },
] as const;
export const scopeLabel = {
  NONE: "No standard",
  COLOR: "Colour standard",
  PLANT: "Plant-wide standard",
};
export const boxKey = (box: FilmOverviewBox) =>
  JSON.stringify([box.layer_code, box.model_code, box.color_name, box.orient]);
export const orientationLabel = (orient: FilmOverviewBox["orient"]) =>
  orient === "H" ? "Horizontal" : "Vertical";
export function groupFilmBoxes(data: FilmOverviewData, layer: FilmOverviewBox["layer_code"]) {
  const boxes = data.boxes.filter((box) => box.layer_code === layer);
  const models = [...new Set(boxes.map((box) => box.model_code))];
  return models.map((model) => {
    const actual = boxes.filter((box) => box.model_code === model);
    return {
      model,
      boxes: actual,
      horizontal: actual.filter((box) => box.orient === "H"),
      vertical: actual.filter((box) => box.orient === "V"),
      colours: data.color_sequence.map((entry) => ({
        ...entry,
        name: entry.color_name,
        boxes: actual.filter((box) => box.color_name === entry.color_name),
      })),
    };
  });
}
export const colourPairWidth = (name: string) => Math.max(144, name.length * 7 + 32);
export function filmDomain(boxes: FilmOverviewBox[]): [number, number] {
  const values = boxes
    .flatMap((box) => [
      box.whisker_lo,
      box.whisker_hi,
      box.box_min,
      box.box_max,
      box.q1,
      box.q3,
      box.median,
      box.mean,
      ...specSegments(box, 0, 0).map((spec) => spec.raw),
    ])
    .map(Number);
  if (!values.length) return [0, 2];
  const lo = Math.min(...values),
    hi = Math.max(...values);
  const span = Math.max(hi - lo, 1);
  return [Math.floor(lo - Math.max(span * 0.08, 1)), Math.ceil(hi + Math.max(span * 0.18, 1))];
}
export function integerTicks([lo, hi]: [number, number]) {
  const rough = Math.max((hi - lo) / 5, 1);
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].find((value) => value * power >= rough)! * power;
  const ticks: number[] = [];
  for (let value = Math.ceil(lo / step) * step; value <= hi; value += step)
    ticks.push(value === 0 ? 0 : value);
  return ticks;
}
export const displayMean = (raw: string) => String(Math.round(Number(raw)));
export function statusPresentation(box: FilmOverviewBox) {
  if (box.status === null)
    return {
      text: box.standard_scope === "NONE" ? "No standard" : "Not graded",
      colour: "neutral",
    };
  return {
    PASS: { text: "Pass", colour: "nominal" },
    // T112 (D-112-1): the API code stays WARNING; the owner's word is "Acceptable".
    WARNING: { text: filmWarningLabel(box.layer_code), colour: "caution" },
    FAIL: { text: "Fail", colour: "critical" },
    OVER: { text: "Over", colour: "over" },
  }[box.status];
}
export const pointKey = (
  box: FilmOverviewBox,
  point: FilmOverviewBox["out_of_spec"][number],
  index: number,
) =>
  JSON.stringify([
    boxKey(box),
    point.side,
    point.value,
    point.point_code,
    point.logical_vehicle_id,
    index,
  ]);
const SPECS = [
  { field: "lo", labelField: "lo_label", dash: "6 4" },
  { field: "hi", labelField: "hi_label", dash: "2 4" },
  { field: "target", labelField: "target_label", dash: "8 3 2 3" },
] as const;
export function specSegments(box: FilmOverviewBox, centre: number, slotWidth: number) {
  if (box.standard_scope === "NONE") return [];
  return SPECS.flatMap(({ field, labelField, dash }) =>
    box[field] === null
      ? []
      : [
          {
            field,
            label: box[labelField],
            dash,
            raw: box[field]!,
            value: Number(box[field]),
            x1: centre - slotWidth / 3,
            x2: centre + slotWidth / 3,
          },
        ],
  );
}
export function panelLegend(boxes: FilmOverviewBox[]) {
  const seen = new Set<string>();
  return boxes
    .flatMap((box) => specSegments(box, 0, 0))
    .filter((spec) => {
      const key = JSON.stringify([spec.field, spec.label]);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}
export function filmMonthTitle(month: string | null) {
  if (!month) return "No measurement month";
  return new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}
export function measuredDate(raw: string | null) {
  if (raw === null) return "Date unavailable";
  const [year, month, day] = raw.split("-").map(Number);
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  return `${day} ${months[month - 1]} ${year}`;
}
export function readingSide(box: FilmOverviewBox, point: FilmOverviewBox["out_of_spec"][number]) {
  if (point.side === "HIGH")
    return box.hi_label && box.hi_label !== "Maximum" ? `Above ${box.hi_label}` : "Above maximum";
  return box.lo_label && box.lo_label !== "Minimum" ? `Below ${box.lo_label}` : "Below minimum";
}
/** RO13 (F9): with no published limit there is nothing to be outside of. */
export function noOutsideLimitText(box: FilmOverviewBox) {
  return box.standard_scope === "NONE"
    ? "No standard, so no limit check"
    : "No readings outside the published limits";
}
/** RO17-FIX (D-RO17F-5): `labelOf` names an outside-limit point by its label. */
export function boxDescription(box: FilmOverviewBox, labelOf?: LabelOf) {
  const layer = FILM_LAYERS.find((item) => item.code === box.layer_code)!.label;
  return `${box.model_code}; ${box.color_name}; ${orientationLabel(box.orient)}; ${layer}. ${box.family_name ?? "No family assigned"}; ${statusPresentation(box).text}; ${scopeLabel[box.standard_scope]}. Average ${box.mean}; Observed minimum ${box.box_min}; Observed maximum ${box.box_max}. Q1 ${box.q1}; median ${box.median}; Q3 ${box.q3}; whiskers ${box.whisker_lo} to ${box.whisker_hi}; Statistical outliers ${box.outliers.join(", ") || "None"}. ${specSegments(
    box,
    0,
    0,
  )
    .map((spec) => `${spec.label}: ${spec.raw}`)
    .join(
      "; ",
    )}. Outside-limit readings: ${box.out_of_spec.map((point) => `${measuredDate(point.measured_date)}; ${readingSide(box, point)}; ${point.value}; Point ${labelOf ? pointText(labelOf("film", box.model_code, point.point_code), point.point_code) : point.point_code}`).join("; ") || noOutsideLimitText(box)}. Values in microns.`;
}
