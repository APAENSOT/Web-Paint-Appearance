import type { components } from "../src/api/types";
import type { Page } from "@playwright/test";

export const overviewBox: components["schemas"]["OverviewBox"] = {
  model_code: "P703 DBL RAPTOR",
  color_name: "Arctic White",
  family_code: "LS",
  orient: "Horizontal",
  n: 5,
  box_min: "55",
  q1: "58",
  median: "60",
  q3: "63",
  box_max: "70",
  whisker_lo: "55",
  whisker_hi: "66",
  outliers: ["70"],
  mean: "61.24",
  ford: "62",
  minimum: "55",
  status: "WARNING",
  below_minimum: [],
};

export function overviewPayload(
  plant: string,
  month: string | null,
): components["schemas"]["WavescanOverviewOut"] {
  const empty = plant === "FVL" || plant === "SAP";
  return {
    plant_code: plant,
    plant_is_active: !empty,
    month: month ?? "2026-09",
    models: [],
    colors: [],
    available_months: empty ? [] : ["2026-09", "2026-06"],
    model_options: empty ? [] : ["P703 DBL RAPTOR", "P703 DBL RANGER"],
    color_options: empty
      ? []
      : [
          { color_name: "Aluminum Metallic", family_code: "LM" },
          { color_name: "Arctic White", family_code: "LS" },
        ],
    boxes: empty
      ? []
      : [
          overviewBox,
          {
            ...overviewBox,
            orient: "Vertical",
            mean: "50.1",
            ford: "49",
            minimum: "42",
            status: "PASS",
            outliers: [],
          },
          {
            ...overviewBox,
            model_code: "P703 DBL RANGER",
            color_name: "Meteor Grey",
            family_code: "MM",
            mean: "48.0",
            ford: "60",
            minimum: "53",
            status: "FAIL",
          },
          {
            ...overviewBox,
            model_code: "P703 DBL RANGER",
            color_name: "Meteor Grey",
            family_code: "MM",
            orient: "Vertical",
            mean: "40.0",
            ford: "47",
            minimum: "40",
            status: "WARNING",
            outliers: [],
          },
          {
            ...overviewBox,
            model_code: "P703 DBL RAPTOR",
            color_name: "Held Colour",
            family_code: null,
            orient: "Horizontal",
            mean: "57.4",
            ford: null,
            minimum: null,
            status: null,
            outliers: [],
          },
        ],
    active_data_source: "v_wavescan_active",
  };
}

export async function mockOverview(page: Page) {
  await page.route("**/api/v1/plants/*/wavescan/overview**", (route) => {
    const url = new URL(route.request().url());
    const plant = url.pathname.split("/")[4];
    return route.fulfill({ json: overviewPayload(plant, url.searchParams.get("month")) });
  });
}
