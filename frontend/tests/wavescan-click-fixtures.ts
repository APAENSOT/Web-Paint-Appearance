import { overviewBox, overviewPayload } from "./overview-fixtures";
import type { components } from "../src/api/types";

export const wavescanClickFixture: components["schemas"]["WavescanOverviewOut"] = {
  ...overviewPayload("FTM", "2026-09"),
  color_options: [
    { color_name: "Absolute / Shadow Black", family_code: "DS" },
    { color_name: "Arctic White", family_code: "LS" },
  ],
  boxes: [
    {
      ...overviewBox,
      color_name: "Absolute / Shadow Black",
      mean: "61.99999999999999999",
      box_min: "12.12345678901234567",
      box_max: "90.98765432109876543",
      ford: "62.00000000000000001",
      minimum: "0",
      status: "FAIL",
    },
    { ...overviewBox, ford: null, minimum: null, status: null, outliers: [] },
    {
      ...overviewBox,
      color_name: "Absolute / Shadow Black",
      orient: "Vertical",
      status: "PASS",
      outliers: [],
    },
    {
      ...overviewBox,
      model_code: "P703 DBL RANGER",
      color_name: "Absolute / Shadow Black",
      status: "WARNING",
      q1: "0",
      q3: "0",
      median: "0",
      mean: "0",
      box_min: "0",
      box_max: "0",
      whisker_lo: "0",
      whisker_hi: "0",
      ford: "0",
      minimum: "0",
      outliers: [],
      n: 1,
    },
  ],
};
