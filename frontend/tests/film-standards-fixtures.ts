import type { FilmStandardsOut, FilmRuleOut } from "../src/features/filmthickness/film-standards";
export const rule = (
  lo: number | null = 0,
  hi: number | null = null,
  target: number | null = null,
  note = "Fixture source",
): FilmRuleOut => ({
  lo,
  hi,
  target,
  source_document: null,
  source_note: note,
  created_at: "2026-10-06T03:00:00Z",
});
export const filmStandardsFixture: FilmStandardsOut = {
  plant_code: "FTM",
  colors: [
    { color_name: "Blue", family_name: "Context only" },
    { color_name: "Amber", family_name: "Context only" },
  ],
  rules: [
    { layer_code: "ECOAT", color_name: null, h: rule(), v: rule(18) },
    { layer_code: "ECOAT", color_name: "Blue", h: rule(12, 20, null, "Own horizontal"), v: null },
    { layer_code: "PRIMER", color_name: null, h: rule(20, 25), v: rule(20, 25) },
    {
      layer_code: "CLEAR",
      color_name: null,
      h: rule(36, null, 46),
      v: rule(30, null, 46, "Vertical source"),
    },
    { layer_code: "BASE", color_name: "Retired", h: rule(5, 10), v: rule(6, 11) },
  ],
};
