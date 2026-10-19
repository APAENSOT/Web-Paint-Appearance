import type { Page } from "@playwright/test";
import type { components } from "../src/api/types";
import { mockHistory } from "./history-fixtures";
type Candidate = components["schemas"]["ComparisonCandidate"];
type Domain = Candidate["domain"];
export const candidatesFor = (domain: Domain): Candidate[] =>
  Array.from({ length: 55 }, (_, i) => ({
    vehicle_id: (domain === "WAVESCAN" ? "a" : "b") + i.toString(16).padStart(63, "0"),
    domain,
    measured_date: i % 2 ? "2026-06-24" : "2026-07-03",
    date_is_month_only: false,
    week: i % 2 ? 4 : 1,
    model: "P703",
    color: i === 53 ? null : i % 2 ? "Meteor Grey" : "Arctic White",
    serial_no: i === 0 || i === 53 ? null : `VIN-${String(i + 1).padStart(2, "0")}`,
    identity_complete: i !== 53,
    point_count: 2,
    expected_point_count: domain === "FILMTHICKNESS" ? 3 : 31,
    incomplete: true,
    load_id: domain === "WAVESCAN" ? 100 + i : null,
    source_file: domain === "WAVESCAN" ? `measured-${i}.xlsx` : null,
    source_sheet: domain === "WAVESCAN" ? "WaveScan" : null,
    job_nos: domain === "FILMTHICKNESS" && i !== 53 ? [`JOB-${i + 1}`] : null,
    load_ids: domain === "FILMTHICKNESS" ? [100 + i, 200 + i] : null,
    source_files: domain === "FILMTHICKNESS" ? [`coat-${i}.xlsx`, `coat-extra-${i}.xlsx`] : null,
  })).sort((a, b) => {
    const date = b.measured_date.localeCompare(a.measured_date);
    if (date) return date;
    const identityA = a.serial_no ?? a.job_nos?.[0] ?? null;
    const identityB = b.serial_no ?? b.job_nos?.[0] ?? null;
    return (
      (identityA === null ? 1 : 0) - (identityB === null ? 1 : 0) ||
      (identityA ?? "").localeCompare(identityB ?? "") ||
      a.vehicle_id.localeCompare(b.vehicle_id)
    );
  });
export const reading = (value: string, id: number) => ({
  value,
  measurement_id: id,
  panel_label: "Original HOOD",
  source_file: "approved.xlsx",
  source_sheet: "WaveScan",
  source_row: id,
  load_id: 100,
  src_location_text: null,
});
export async function mockComparison(page: Page) {
  await mockHistory(page, "viewer");
  const requests: URL[] = [];
  await page.route("**/api/v1/plants/*/comparison/**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const domain = url.searchParams.get("domain") as Domain;
    const plant = url.pathname.split("/")[4];
    const all = candidatesFor(domain);
    const months = url.searchParams.getAll("month");
    if (url.pathname.endsWith("vehicles")) {
      const selected = months.length ? months : ["2026-07"];
      const model = url.searchParams.get("model");
      const colors = url.searchParams.getAll("color"),
        periods = url.searchParams.getAll("period");
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const items = model
        ? all.filter(
            (v) =>
              selected.includes(v.measured_date.slice(0, 7)) &&
              (!colors.length || colors.includes(v.color!)) &&
              (!periods.length || periods.includes(`${v.measured_date.slice(0, 7)}-W${v.week}`)) &&
              (!q ||
                v.serial_no?.toLowerCase().includes(q) ||
                v.job_nos?.some((j) => j.toLowerCase().includes(q))),
          )
        : [];
      const offset = Number(url.searchParams.get("offset") ?? 0),
        limit = Number(url.searchParams.get("limit") ?? 50);
      const empty = plant === "FVL";
      const result: components["schemas"]["ComparisonVehiclesOut"] = {
        plant_code: plant,
        plant_is_active: !empty,
        domain,
        default_month: empty ? null : "2026-07",
        selected_months: empty ? [] : selected,
        available_months: empty ? [] : ["2026-07", "2026-06"],
        model_options: empty ? [] : ["P703", "U704"],
        color_options: model ? ["Arctic White", "Meteor Grey"] : [],
        week_options: model
          ? ["2026-07", "2026-06"]
              .filter((month) => selected.includes(month))
              .flatMap((month) => [{ month, week: month === "2026-06" ? 4 : 1 }])
          : [],
        items: empty || model === "U704" ? [] : items.slice(offset, offset + limit),
        page: {
          offset,
          limit,
          total: empty || model === "U704" ? 0 : items.length,
          returned: empty || model === "U704" ? 0 : items.slice(offset, offset + limit).length,
        },
        active_data_source: domain === "WAVESCAN" ? "v_wavescan_active" : "filmthickness_active",
      };
      return route.fulfill({ json: result });
    }
    const ids = url.searchParams.getAll("vehicle_id");
    const columns = ids.map((id) => all.find((v) => v.vehicle_id === id)!);
    const cells = (empty = false) =>
      columns.map((v, i) => ({
        vehicle_id: v.vehicle_id,
        missing: empty || i === 1,
        readings:
          empty || i === 1
            ? []
            : domain === "WAVESCAN"
              ? [reading("0", i * 2 + 1), reading("62.4000", i * 2 + 2)]
              : [
                  {
                    ...reading("18.2500", i + 1),
                    measurement_id: null,
                    panel_label: null,
                    source_sheet: null,
                    source_file: null,
                    src_location_text: "Original hood",
                  },
                ],
      }));
    const result: components["schemas"]["ComparisonPointsOut"] = {
      plant_code: plant,
      domain,
      model: "P703",
      metric: url.searchParams.get(
        "metric",
      ) as components["schemas"]["ComparisonPointsOut"]["metric"],
      columns,
      locations: [
        {
          point_no: 1,
          code: "HOOD",
          orientation: domain === "WAVESCAN" ? "Horizontal" : null,
          cells: cells(),
        },
        {
          point_no: 2,
          code: "DOOR",
          orientation: domain === "WAVESCAN" ? "Vertical" : "V",
          cells: cells(),
        },
        { point_no: 3, code: "ROOF", orientation: null, cells: cells(true) },
      ],
      unaligned_locations:
        domain === "WAVESCAN"
          ? [
              {
                vehicle_id: ids[0],
                checkzone: "OLDHOOD",
                reading: reading("71.0300", 999),
                retired: false,
              },
            ]
          : [],
      active_data_source: domain === "WAVESCAN" ? "v_wavescan_active" : "filmthickness_active",
    };
    return route.fulfill({ json: result });
  });
  return requests;
}
