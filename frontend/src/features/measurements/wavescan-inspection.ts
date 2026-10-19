import { displayMean, statusLabel, type OverviewBox } from "./overview-display";

export const wavescanBoxKey = (box: OverviewBox) =>
  JSON.stringify([box.model_code, box.color_name, box.orient]);

/**
 * A stored Wave Scan measure as the file wrote it. A value that is a float32
 * artefact (63.9000015258789: a float32 written out as a double) shows as the
 * shortest decimal that reads back to the same float32 (63.9); any other value
 * shows exactly as stored.
 */
export function wavescanMeasure(raw: string): string {
  const value = Number(raw);
  const single = Math.fround(value);
  const artefact =
    Number.isFinite(value) &&
    String(value) === raw && // more digits than a double holds is exact decimal, not float32
    Math.abs(single - value) <= 1e-9 * Math.abs(value);
  if (!artefact) return raw;
  for (let digits = 1; digits <= 9; digits += 1) {
    const short = Number(value.toPrecision(digits));
    if (Math.fround(short) === single) return String(short);
  }
  return raw;
}

export function wavescanMeasuredDate(raw: string | null) {
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

export function wavescanPrimary(box: OverviewBox) {
  return [
    { label: "Average", raw: box.mean, display: displayMean(box.mean) },
    { label: "Observed minimum", raw: box.box_min, display: displayMean(box.box_min) },
    { label: "Observed maximum", raw: box.box_max, display: displayMean(box.box_max) },
    { label: "Standard", raw: box.ford, display: box.ford ?? "Not set" },
    { label: "Minimum", raw: box.minimum, display: box.minimum ?? "Not set" },
  ];
}

export function wavescanDescription(box: OverviewBox) {
  return `${box.model_code}; ${box.color_name}; ${box.orient}; ${statusLabel(box.status)}. ${wavescanPrimary(
    box,
  )
    .map((field) => `${field.label}: ${field.raw == null ? "Not set" : `${field.display} CF`}`)
    .join(". ")}. Select for detailed measurements.`;
}
