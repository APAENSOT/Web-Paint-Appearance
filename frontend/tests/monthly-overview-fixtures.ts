import type { components } from "../src/api/types";
import { filmBox, filmOverviewFixture } from "./film-overview-fixtures";
import { wavescanClickFixture } from "./wavescan-click-fixtures";

// Explicit backend membership: equality (55), Warning-only (60), and statistical
// outlier (70) are absent. Do not compute the list from a threshold in tests.
export const monthlyWaveFixture: typeof wavescanClickFixture = {
  ...wavescanClickFixture,
  boxes: wavescanClickFixture.boxes.map((box, index) =>
    index === 0 || index === 2
      ? {
          ...box,
          status: index === 0 ? "WARNING" : "PASS",
          minimum: "55",
          ford: "62",
          below_minimum: [
            {
              measurement_id: 999001,
              measured_date: "2026-09-30",
              checkzone: "3HOOD",
              cf: "1.123456789012345678901234567890123456789",
            },
            {
              measurement_id: 999002,
              measured_date: "2026-09-30",
              checkzone: "3HOOD",
              cf: "1.123456789012345678901234567890123456789",
            },
            {
              measurement_id: 999003,
              measured_date: null,
              checkzone: null,
              cf: "2.000000000000000000001",
            },
          ],
        }
      : box,
  ),
};

type Sequence = components["schemas"]["FilmColorSequenceEntry"];
// Supplied tie/unequal H/V/partial/no-rule ranks. Family/filter/value order differs.
export const monthlySequence: Sequence[] = [
  {
    rank: 1,
    color_name: "Zulu",
    family_code: "MM",
    family_name: "Metallic",
    family_order: 2,
    base_lo_h: "9",
    base_hi_h: "10",
    base_lo_v: "15",
    base_hi_v: "20",
    ladder: "BASE",
  },
  {
    rank: 2,
    color_name: "Alpha",
    family_code: "LS",
    family_name: "Solid",
    family_order: 1,
    base_lo_h: "9",
    base_hi_h: "10",
    base_lo_v: "16",
    base_hi_v: null,
    ladder: "BASE",
  },
  {
    rank: 3,
    color_name: "Published without Base measurements",
    family_code: "MM",
    family_name: "Metallic",
    family_order: 2,
    base_lo_h: "9",
    base_hi_h: "10",
    base_lo_v: "16",
    base_hi_v: null,
    ladder: "BASE",
  },
  {
    rank: 4,
    color_name: "Very long canonical colour without Base standard",
    family_code: null,
    family_name: null,
    family_order: null,
    base_lo_h: null,
    base_hi_h: null,
    base_lo_v: null,
    base_hi_v: null,
    ladder: "NO_BASE_STANDARD",
  },
];
export const monthlyFilmFixture: typeof filmOverviewFixture = {
  ...filmOverviewFixture,
  month: "2026-09",
  available_months: ["2026-09", "2026-08"],
  model_options: ["P703 DBL RANGER", "U704"],
  color_options: [
    monthlySequence[1],
    monthlySequence[0],
    monthlySequence[2],
    monthlySequence[3],
  ].map(({ color_name, family_code, family_name, family_order }) => ({
    color_name,
    family_code,
    family_name,
    family_order,
  })),
  color_sequence: monthlySequence,
  boxes: (["ECOAT", "PRIMER", "BASE", "CLEAR"] as const).flatMap((layer_code) =>
    ["P703 DBL RANGER", "U704"].flatMap((model_code) =>
      (["H", "V"] as const).flatMap((orient) =>
        monthlySequence
          .filter(
            (entry) =>
              !(entry.rank === 3 && layer_code === "BASE") &&
              !(entry.rank === 2 && orient === "V") &&
              !(entry.rank === 1 && model_code === "U704"),
          )
          .map((entry) =>
            filmBox({
              color_name: entry.color_name,
              family_code: entry.family_code,
              family_name: entry.family_name,
              family_order: entry.family_order,
              layer_code,
              model_code,
              orient,
              color_rank: entry.rank,
              mean: entry.rank === 1 ? "100.00000000000001" : "0",
              lo: "0",
              hi: null,
              target: null,
              standard_scope: "COLOR",
              status: "PASS",
              outliers: [],
            }),
          ),
      ),
    ),
  ),
};
