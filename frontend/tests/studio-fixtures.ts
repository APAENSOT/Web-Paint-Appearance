import type { Page } from "@playwright/test";
import type { components } from "../src/api/types";
import { mockComparison, candidatesFor } from "./comparison-fixtures";
import { overviewBox } from "./overview-fixtures";
import { filmBox } from "./film-overview-fixtures";
type Input = components["schemas"]["ComparisonMonthlyPreviewIn"];
type Preview = components["schemas"]["ComparisonMonthlyPreviewOut"];
const params = ["du", "wa", "wb", "wc", "wd", "we"] as const;
export const months = [
  "2026-08",
  "2026-07",
  "2026-06",
  "2026-05",
  "2026-04",
  "2026-03",
  "2026-02",
  "2026-01",
];
export function studioPreview(body: Input): Preview {
  // Synthetic response facts, explicitly supplied for the equal-month/gap cases.
  const monthly = body.months.map((month) => ({
    month,
    mean: month === "2026-06" ? "40" : month === "2026-07" ? "60" : null,
    n: month === "2026-06" ? 1 : month === "2026-07" ? 9 : 0,
  }));
  const contributors = monthly.filter((m) => m.mean != null);
  const mean = contributors.length === 2 ? "50" : (contributors[0]?.mean ?? null);
  const summary = {
    monthly,
    mean,
    contributing_months: contributors.map((m) => m.month),
    missing_months: monthly.filter((m) => m.mean == null).map((m) => m.month),
    contributing_month_count: contributors.length,
  };
  const group_means: Preview["group_means"] = ["Arctic White", "Meteor Grey"].flatMap((color) =>
    (["H", "V"] as const).map((orientation) => ({
      ...(body.domain === "FILMTHICKNESS" && color === "Meteor Grey"
        ? {
            monthly: body.months.map((month) => ({ month, mean: null, n: 0 })),
            mean: null,
            contributing_months: [],
            missing_months: body.months,
            contributing_month_count: 0,
          }
        : summary),
      color,
      orientation,
      metric: body.metric,
      layer_code:
        body.domain === "WAVESCAN"
          ? null
          : (body.metric.toUpperCase() as "ECOAT" | "PRIMER" | "BASE" | "CLEAR"),
    })),
  );
  return {
    plant_code: "AAT",
    domain: body.domain,
    model: body.model,
    metric: body.metric,
    months: body.months,
    month_boxes: monthly.map((m) => ({
      month: m.month,
      wavescan_boxes:
        body.domain !== "WAVESCAN" || m.mean == null
          ? []
          : ["Arctic White", "Meteor Grey"].flatMap((color_name) =>
              (["Horizontal", "Vertical"] as const).map((orient) => ({
                ...overviewBox,
                model_code: body.model,
                color_name,
                orient,
                n: m.n,
                mean: m.mean!,
                box_min: m.mean!,
                q1: m.mean!,
                median: m.mean!,
                q3: m.mean!,
                box_max: m.mean!,
                whisker_lo: m.mean!,
                whisker_hi: m.mean!,
                outliers: [],
                ...(m.n === 9
                  ? {
                      box_min: "50",
                      q1: "57",
                      median: "60",
                      q3: "63",
                      box_max: "70",
                      whisker_lo: "50",
                      whisker_hi: "70",
                    }
                  : {}),
                ford: "62.4000",
                minimum: "35.0000",
              })),
            ),
      film_boxes:
        body.domain !== "FILMTHICKNESS" || m.mean == null
          ? []
          : (["H", "V"] as const).map((orient) =>
              filmBox({
                model_code: body.model,
                color_name: "Arctic White",
                orient,
                layer_code: body.metric.toUpperCase() as "ECOAT" | "PRIMER" | "BASE" | "CLEAR",
                mean: m.mean!,
                n: m.n,
                box_min: m.n === 1 ? "40" : "45",
                q1: m.n === 1 ? "40" : "52",
                median: m.n === 1 ? "40" : "60",
                q3: m.n === 1 ? "40" : "68",
                box_max: m.n === 1 ? "40" : "75",
                whisker_lo: m.n === 1 ? "40" : "45",
                whisker_hi: m.n === 1 ? "40" : "75",
                outliers: [],
                status: body.metric === "clear" && m.n === 1 ? "WARNING" : "PASS",
                lo: "30.0000",
                lo_label: body.metric === "clear" ? "No point below" : "Minimum",
                target: body.metric === "clear" ? "46.0000" : null,
                target_label: body.metric === "clear" ? "Minimum requirement" : null,
                hi: body.metric === "clear" ? null : "65.0000",
                hi_label: body.metric === "clear" ? null : "Maximum",
              }),
            ),
    })),
    group_means,
    profiles:
      body.domain === "FILMTHICKNESS"
        ? []
        : ["Arctic White", "Meteor Grey"].flatMap((color) =>
            [
              { point_no: 1, code: "HOOD", orientation: "H" as const },
              { point_no: 2, code: "DOOR", orientation: "V" as const },
              { point_no: 3, code: "ROOF", orientation: null },
            ].map((location) => ({
              ...location,
              color,
              metrics: params.map((metric, i) =>
                metric === "wc"
                  ? {
                      ...summary,
                      metric,
                      mean: null,
                      monthly: body.months.map((month) => ({ month, mean: null, n: 0 })),
                      contributing_months: [],
                      missing_months: body.months,
                      contributing_month_count: 0,
                    }
                  : metric === "du"
                    ? { ...summary, metric }
                    : {
                        ...summary,
                        metric,
                        mean: contributors.length ? String(i * 7) : null,
                        monthly: monthly.map((m) => ({
                          ...m,
                          mean: m.mean == null ? null : String(i * 7),
                        })),
                      },
              ),
            })),
          ),
    unaligned_reading_count: body.months.map((month) => ({
      month,
      n: month === "2026-07" ? 4 : 0,
    })),
    active_data_source: body.domain === "WAVESCAN" ? "v_wavescan_active" : "filmthickness_active",
  };
}
export function vehicleVisuals(
  ids: string[],
): components["schemas"]["ComparisonVehicleVisualsOut"] {
  const columns = ids.map((id) => candidatesFor("WAVESCAN").find((c) => c.vehicle_id === id)!);
  const stats = {
    box_min: "0",
    q1: "15.6000",
    median: "31.2000",
    q3: "46.8000",
    box_max: "62.4000",
    whisker_lo: "0",
    whisker_hi: "62.4000",
    outliers: [],
    mean: "31.2000",
  };
  const trace = (id: number) => ({
    measurement_id: id,
    panel_label: `Original hood ${id}`,
    source_file: "approved.xlsx",
    source_sheet: "WaveScan",
    source_row: id,
    load_id: 100,
    cf: "62.4000",
    du: "0",
    wa: "10.00000000000000001",
    wb: "60.2000",
    wc: null,
    wd: "20.3000",
    we: "18.4000",
  });
  return {
    plant_code: "AAT",
    model: "P703",
    columns,
    vehicles: ids.map((vehicle_id, i) => ({
      vehicle_id,
      cf_boxes: [
        {
          orientation: "H",
          n: i === 1 ? 1 : 2,
          stats:
            i === 1
              ? {
                  ...stats,
                  box_min: "62.4000",
                  q1: "62.4000",
                  median: "62.4000",
                  q3: "62.4000",
                  box_max: "62.4000",
                  whisker_lo: "62.4000",
                  whisker_hi: "62.4000",
                  mean: "62.4000",
                }
              : stats,
        },
        { orientation: "V", n: 0, stats: null },
      ],
      locations: [
        {
          point_no: 1,
          code: "HOOD",
          orientation: "H",
          traces: [{ ...trace(i * 10 + 1), cf: i === 1 ? null : "0" }, trace(i * 10 + 2)],
        },
        {
          point_no: 2,
          code: "DOOR",
          orientation: "V",
          traces: [{ ...trace(i * 10 + 3), cf: null }],
        },
        { point_no: 3, code: "ROOF", orientation: null, traces: [] },
      ],
      unaligned_locations: [{ checkzone: "OLDHOOD", trace: trace(i * 10 + 9) }],
    })),
    active_data_source: "v_wavescan_active",
  };
}
export async function mockStudio(page: Page) {
  await mockComparison(page);
  const previews: Input[] = [],
    visuals: string[][] = [],
    options: URL[] = [];
  await page.route("**/api/v1/plants/*/comparison/vehicles**", async (route) => {
    const url = new URL(route.request().url());
    options.push(url);
    if (url.searchParams.get("limit") !== "1") return route.fallback();
    return route.fulfill({
      json: {
        plant_code: "AAT",
        plant_is_active: true,
        domain: url.searchParams.get("domain"),
        available_months: months,
        default_month: "2026-08",
        selected_months: url.searchParams.getAll("month").length
          ? url.searchParams.getAll("month")
          : ["2026-08"],
        model_options: ["P703", "U704"],
        color_options: ["Arctic White", "Meteor Grey"],
        week_options: [],
        items: [],
        page: { limit: 1, offset: 0, total: 0, returned: 0 },
        active_data_source:
          url.searchParams.get("domain") === "WAVESCAN"
            ? "v_wavescan_active"
            : "filmthickness_active",
      },
    });
  });
  await page.route("**/comparison/monthly-preview", (route) => {
    const body = route.request().postDataJSON() as Input;
    previews.push(body);
    return route.fulfill({ json: studioPreview(body) });
  });
  await page.route("**/comparison/vehicle-visuals**", (route) => {
    const ids = new URL(route.request().url()).searchParams.getAll("vehicle_id");
    visuals.push(ids);
    return route.fulfill({ json: vehicleVisuals(ids) });
  });
  return { previews, visuals, options };
}
