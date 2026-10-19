import type { Page } from "@playwright/test";
import type { components } from "../src/api/types";
import { identity, measurement, workspaceMeta } from "./fixtures";
import { mockOverview } from "./overview-fixtures";

export const historyVehicleId = "a".repeat(64);
export const historyVehicle: components["schemas"]["HistoryVehicleSetOut"] = {
  vehicle_id: historyVehicleId,
  load_id: 123,
  plant_code: "AAT",
  measured_date: "2026-09-13",
  date_is_month_only: false,
  model: "P703",
  color: "White",
  serial_no: "T09-TEST",
  identity_complete: true,
  point_count: 1,
  expected_point_count: 31,
  incomplete_set: true,
  source_file: "approved-september.xlsx",
  source_sheet: "Review1",
  week: 2,
};
const { plant: _plant, ...measurementPoint } = measurement;
// `MeasurementOut` carries every measure as `string | null` and
// `HistoryPointOut` as `string`, so the measures are restated rather than
// spread: the fixture does set them all, and narrowing them here says so
// instead of asserting it away.
export const historyPoint: components["schemas"]["HistoryPointOut"] = {
  ...measurementPoint,
  lw: measurement.lw ?? "3.7",
  sw: measurement.sw ?? "4.2",
  cf: measurement.cf ?? "62",
  doi: measurement.doi ?? "80",
  du: measurement.du ?? "1",
  wa: measurement.wa ?? "1",
  wb: measurement.wb ?? "2",
  wc: measurement.wc ?? "3",
  wd: measurement.wd ?? "4",
  we: measurement.we ?? "5",
  b: measurement.b ?? "6",
  // T94 (D-94-4): the panel column is the stored position, the long name.
  // The plant's own words travel beside it as `src_zone_text`.
  checkzone: "RRHOOD",
  panel_label: "RRHOOD",
  src_zone_text: "01 RRHOOD",
  source_file: "approved-september.xlsx",
  // T114: Point Check's tags on the reading's point -- a live, counted,
  // standard point here.
  retired: false,
  counted: true,
  is_extra: false,
};
export const historyPoints = (row = historyPoint): components["schemas"]["HistoryPointPage"] => ({
  items: [row],
  page: { offset: 0, limit: 50, total: 1, returned: 1 },
  vehicle: historyVehicle,
  plant_code: "AAT",
  active_data_source: "v_wavescan_active",
});
export async function mockHistory(page: Page, role = "engineer") {
  const requests: URL[] = [];
  await mockOverview(page);
  await page.route("**/api/v1/plants/*/filmthickness/facets**", (r) => {
    const url = new URL(r.request().url());
    return r.fulfill({
      json: {
        plant_code: url.pathname.split("/")[4],
        plant_is_active: true,
        default_month: null,
        months: [],
        month: url.searchParams.get("month"),
        model: url.searchParams.get("model"),
        models: [],
        color: url.searchParams.get("color"),
        colors: [],
        active_data_source: "filmthickness_active",
      },
    });
  });
  await page.route("**/api/v1/auth/me", (r) =>
    r.fulfill({ json: { ...identity, principal: { ...identity.principal, roles: [role] } } }),
  );
  await page.route("**/api/v1/meta", (r) => r.fulfill({ json: workspaceMeta }));
  await page.route("**/api/v1/plants/*/history/**", (r) => {
    const url = new URL(r.request().url());
    requests.push(url);
    const plant = url.pathname.split("/")[4];
    const empty = plant === "FVL" || plant === "SAP";
    const month = url.searchParams.get("month"),
      model = url.searchParams.get("model"),
      color = url.searchParams.get("color");
    const common = {
      plant_code: plant,
      plant_is_active: !empty,
      active_data_source: "v_wavescan_active",
    };
    if (url.pathname.endsWith("facets"))
      return r.fulfill({
        json: {
          ...common,
          default_month: empty ? null : "2026-09",
          months: empty ? [] : ["2026-09", "2026-06"],
          month,
          model,
          color,
          models: month ? ["P703", "U704"] : [],
          colors: month ? (model === "U704" ? ["Blue"] : ["White", "Blue"]) : [],
        },
      });
    if (url.pathname.endsWith("summaries"))
      return r.fulfill({
        json: {
          ...common,
          month,
          model,
          color,
          weeks: empty
            ? []
            : [
                {
                  week: 2,
                  measured_date_min: "2026-09-13",
                  measured_date_max: "2026-09-13",
                  cards: [
                    {
                      model: "P703",
                      color: "White",
                      vehicle_count: 3,
                      point_count: 3,
                      measured_date_min: "2026-09-13",
                      measured_date_max: "2026-09-13",
                    },
                  ],
                },
              ],
        },
      });
    if (url.pathname.endsWith("points")) return r.fulfill({ json: historyPoints() });
    return r.fulfill({
      json: {
        ...common,
        month,
        week: 2,
        model,
        color,
        items: [
          historyVehicle,
          { ...historyVehicle, vehicle_id: "b".repeat(64), serial_no: "SECOND-SERIAL" },
          {
            ...historyVehicle,
            vehicle_id: "c".repeat(64),
            serial_no: null,
            identity_complete: false,
            expected_point_count: null,
          },
        ],
        page: { offset: 0, limit: 50, total: 3, returned: 3 },
      },
    });
  });
  await page.route("**/api/v1/measurements/41", (r) => r.fulfill({ json: measurement }));
  return requests;
}
export async function openHistoryPoint(page: Page) {
  await page.goto(
    `/plant/aat?dataView=history&month=2026-09&model=P703&color=White&week=2&vehicle=${historyVehicleId}`,
  );
}
