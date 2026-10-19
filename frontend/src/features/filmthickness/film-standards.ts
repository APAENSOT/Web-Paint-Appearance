import type { components } from "@/api/types";
export type FilmStandardsOut = components["schemas"]["FilmStandardsOut"];
export type FilmLayerRuleOut = components["schemas"]["FilmLayerRuleOut"];
export type FilmRuleOut = components["schemas"]["FilmRuleOut"];
export type FilmPlantColorOut = components["schemas"]["FilmPlantColorOut"];
export type FilmRuleIn = components["schemas"]["FilmRuleIn"];
export type FilmStandardPublishIn = components["schemas"]["FilmStandardPublishIn"];
export type FilmStandardPublishOut = components["schemas"]["FilmStandardPublishOut"];
export type Layer = FilmLayerRuleOut["layer_code"];
export const layers = [
  ["ECOAT", "E-coat"],
  ["PRIMER", "Primer"],
  ["BASE", "Base"],
  ["CLEAR", "Clear"],
] as const;
export type Resolved = { rule: FilmRuleOut | null; inherited: boolean };
export function resolveOrientation(
  own: FilmLayerRuleOut | undefined,
  wide: FilmLayerRuleOut | undefined,
  orientation: "h" | "v",
  color: string | null,
): Resolved {
  const rule = own?.[orientation] ?? (color === null ? null : wide?.[orientation]) ?? null;
  return { rule, inherited: Boolean(color !== null && !own?.[orientation] && rule) };
}
export type TripleDraft = Record<"lo" | "hi" | "target", string>;
export const draftFrom = (rule: FilmRuleOut | null): TripleDraft => ({
  lo: rule?.lo == null ? "" : String(rule.lo),
  hi: rule?.hi == null ? "" : String(rule.hi),
  target: rule?.target == null ? "" : String(rule.target),
});
export const sameValues = (h: FilmRuleOut | null, v: FilmRuleOut | null) =>
  Boolean(h && v && h.lo === v.lo && h.hi === v.hi && h.target === v.target);
export const displayValue = (value: number | null | undefined) =>
  value == null ? "Not set" : `${Number(value.toFixed(2))} µm`;
export type LimitField = "lo" | "hi" | "target";
/**
 * The limit lines a layer has, with their owner-locked names (T67 D-67-05).
 * Clear has no Maximum: `lo` is "No point below" and `target` is the
 * "Minimum requirement" (the API refuses `hi` on CLEAR). Every other layer
 * is Minimum / Maximum.
 */
export function limitFields(layer: Layer): readonly (readonly [LimitField, string])[] {
  return layer === "CLEAR"
    ? [
        ["lo", "No point below"],
        ["target", "Minimum requirement"],
      ]
    : [
        ["lo", "Minimum"],
        ["hi", "Maximum"],
      ];
}
export function validateTriple(
  draft: TripleDraft,
  layer: Layer,
): { values: FilmRuleIn; errors: Partial<TripleDraft> } {
  const errors: Partial<TripleDraft> = {};
  const values: FilmRuleIn = { lo: null, hi: null, target: null };
  for (const [field] of limitFields(layer)) {
    const raw = draft[field].trim();
    if (!raw) continue;
    if (!/^\d+(?:\.\d{1,2})?$/.test(raw) || Number(raw) > 500)
      errors[field] = "Use a decimal from 0 through 500, with at most two decimal places.";
    else values[field] = Number(raw);
  }
  if (layer === "CLEAR") {
    if (values.lo == null && !errors.lo) errors.lo = "Set No point below.";
    if (values.target != null && values.lo != null && values.target < values.lo)
      errors.target = "Minimum requirement must be at least No point below.";
    return { values, errors };
  }
  if (values.lo == null && values.hi == null && !errors.lo && !errors.hi)
    errors.lo = "Set a Minimum or Maximum.";
  if (values.lo != null && values.hi != null && values.lo > values.hi)
    errors.hi = "Maximum must be at least Minimum.";
  return { values, errors };
}

export function plantTemplate(plant: string): { shared: Layer[]; colours: Layer[] } | null {
  if (plant === "AAT") return { shared: ["ECOAT", "CLEAR"], colours: ["PRIMER", "BASE"] };
  if (["FTM", "SAP", "FVL"].includes(plant))
    return { shared: ["ECOAT", "PRIMER", "CLEAR"], colours: ["BASE"] };
  return null;
}
export const layerName = (layer: Layer) => layers.find(([code]) => code === layer)![1];
export function resolveRow(
  data: FilmStandardsOut,
  layer: Layer,
  color: string | null,
  retained = false,
) {
  const own = data.rules.find((r) => r.layer_code === layer && r.color_name === color);
  const wide = retained
    ? undefined
    : data.rules.find((r) => r.layer_code === layer && r.color_name === null);
  return {
    own,
    h: resolveOrientation(own, wide, "h", color),
    v: resolveOrientation(own, wide, "v", color),
  };
}
export function retainedRules(data: FilmStandardsOut, layer: Layer) {
  return data.rules
    .filter(
      (r) =>
        r.layer_code === layer &&
        r.color_name !== null &&
        !data.colors.some((c) => c.color_name === r.color_name),
    )
    .sort((a, b) => a.color_name!.localeCompare(b.color_name!));
}
export function colourGroups(colors: FilmPlantColorOut[], search: string) {
  const query = search.trim().toLowerCase();
  const families = new Map<string | null, FilmPlantColorOut[]>();
  for (const color of colors) {
    if (!color.color_name.toLowerCase().includes(query)) continue;
    families.set(color.family_name, [...(families.get(color.family_name) ?? []), color]);
  }
  return [...families]
    .sort(([a], [b]) => (a === null ? 1 : b === null ? -1 : a.localeCompare(b)))
    .map(([family, colors]) => ({
      key: JSON.stringify(family),
      name: family ?? "No family assigned",
      colors: colors.sort((a, b) => a.color_name.localeCompare(b.color_name)),
    }));
}
