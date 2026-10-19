import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { historyPoints, historyVehicleId, mockHistory } from "../history-fixtures";
import { workbookFixture } from "../workbook-fixtures";

const filmVehicleId = "f".repeat(64);
const filmVehicle: components["schemas"]["FilmVehicleOut"] = {
  logical_vehicle_id: filmVehicleId,
  plant_code: "AAT",
  measured_date: "2026-09-13",
  date_is_month_only: false,
  model: "P703 DBL RANGER",
  model_display_name: "Ranger",
  color: "White",
  serial_no: null,
  job_nos: ["J-42"],
  identity_complete: true,
  load_ids: [201],
  source_files: ["film-build.xlsx"],
  mapped_point_count: 1,
  expected_point_count: 94,
  incomplete: true,
  // T103: AAT's list names no complete stop, so there is no box section and
  // the server sends no tag.
  box: null,
  identity_note: null,
};

async function mockFilmHistory(page: Page) {
  const reads: URL[] = [];
  await page.route("**/api/v1/plants/*/filmthickness/**", (route) => {
    const url = new URL(route.request().url());
    reads.push(url);
    const common = {
      plant_code: "AAT",
      plant_is_active: true,
      active_data_source: "filmthickness_active",
    };
    if (url.pathname.endsWith("facets"))
      return route.fulfill({
        json: {
          ...common,
          default_month: "2026-10",
          months: ["2026-10", "2026-09"],
          month: url.searchParams.get("month"),
          model: url.searchParams.get("model"),
          color: url.searchParams.get("color"),
          models: [],
          colors: [],
        },
      });
    // T108: Film History opens on week cards, so the card read comes first
    // and the car list is what one card holds.
    if (url.pathname.endsWith("summaries"))
      return route.fulfill({
        json: {
          ...common,
          month: url.searchParams.get("month"),
          model: url.searchParams.get("model"),
          color: url.searchParams.get("color"),
          weeks: [
            {
              week: 2,
              measured_date_min: filmVehicle.measured_date,
              measured_date_max: filmVehicle.measured_date,
              cards: [
                {
                  model: filmVehicle.model,
                  model_display_name: filmVehicle.model_display_name,
                  color: filmVehicle.color,
                  vehicle_count: 1,
                  point_count: 2,
                  box_count: 0,
                  no_box_count: 0,
                  incomplete_count: 1,
                  measured_date_min: filmVehicle.measured_date,
                  measured_date_max: filmVehicle.measured_date,
                },
              ],
            },
          ],
        },
      });
    if (url.pathname.endsWith("vehicles"))
      return route.fulfill({
        json: {
          ...common,
          month: url.searchParams.get("month"),
          week: Number(url.searchParams.get("week")) || null,
          model: null,
          color: null,
          items: [filmVehicle],
          page: { offset: 0, limit: 200, returned: 1, total: 1 },
        },
      });
    return route.fulfill({
      json: {
        ...common,
        vehicle: filmVehicle,
        items: [
          {
            point_no: 1,
            point_code: "001HOOD",
            orientation: "H",
            src_location_text: "001HOOD",
            load_id: 201,
            source_row: 1,
            layers: { ecoat: "62.4", primer: null, base: null, clear: null },
          },
          {
            point_no: 22,
            point_code: "022LTFTDOOR",
            orientation: "V",
            src_location_text: null,
            load_id: null,
            source_row: null,
            layers: { ecoat: null, primer: null, base: null, clear: null },
          },
        ],
      },
    });
  });
  return reads;
}

test("Upload Data tags mixed files and filters without a domain API query", async ({ page }) => {
  await mockHistory(page, "engineer");
  const wave = {
    ...workbookFixture,
    source_file: "wavescan.xlsx",
    sheets: workbookFixture.sheets.map((sheet) => ({
      ...sheet,
      batch: { ...sheet.batch, domain: "WAVESCAN" },
    })),
  };
  const film = {
    ...workbookFixture,
    file_hash: "b".repeat(64),
    source_file: "film-build.xlsx",
    sheets: workbookFixture.sheets.map((sheet) => ({
      ...sheet,
      batch: { ...sheet.batch, domain: "FILMTHICKNESS" },
    })),
  };
  const reads: URL[] = [];
  await page.route("**/api/v1/plants/*/workbooks?*", (route) => {
    reads.push(new URL(route.request().url()));
    return route.fulfill({
      json: {
        plant_code: "AAT",
        plant_is_active: true,
        items: [wave, film],
        page: { offset: 0, limit: 200, returned: 2, total: 2 },
      },
    });
  });
  await page.goto("/plant/AAT?dataView=upload");
  const filter = page.getByRole("combobox", { name: "Paint Appearance" });
  await expect(filter).toHaveValue("both");
  await expect(page.getByRole("article").filter({ hasText: "wavescan.xlsx" })).toContainText(
    "WaveScan",
  );
  await expect(page.getByRole("article").filter({ hasText: "film-build.xlsx" })).toContainText(
    "Film Thickness",
  );
  await page.screenshot({
    path: "test-results/screenshots/T50-upload-mixed-desktop.png",
    fullPage: true,
  });
  await filter.selectOption("wavescan");
  await expect(page.getByText("film-build.xlsx")).toHaveCount(0);
  await expect(page).toHaveURL(/dataDomain=wavescan/);
  await filter.selectOption("film");
  await expect(page.getByText("wavescan.xlsx")).toHaveCount(0);
  await page.reload();
  await expect(filter).toHaveValue("film");
  await expect(page.getByText("film-build.xlsx")).toBeVisible();
  await filter.selectOption("both");
  await expect(page.getByText("wavescan.xlsx")).toBeVisible();
  await expect(page.getByText("film-build.xlsx")).toBeVisible();
  expect(reads.every((url) => !url.searchParams.has("domain"))).toBe(true);
});

test("Viewer History shows WaveScan and film lists, and film drill has no Correct", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  await mockFilmHistory(page);
  await page.goto("/plant/AAT?dataView=history&month=2026-09");
  await expect(page.getByRole("combobox", { name: "Paint Appearance" })).toHaveValue("both");
  await expect(page.getByRole("heading", { name: "Week 2", exact: true }).first()).toBeVisible();
  // T108: both lists now show week cards. The film card is the first click.
  await expect(page.getByRole("button", { name: /Ranger \/ White/ })).toBeVisible();
  await page.screenshot({
    path: "test-results/screenshots/T50-history-both-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: /Ranger \/ White/ }).click();
  await expect(page.getByRole("button", { name: /Job J-42/ })).toBeVisible();
  await page.getByRole("button", { name: /Job J-42/ }).click();
  await expect(page).toHaveURL(new RegExp(`filmVehicle=${filmVehicleId}`));
  await expect(page.getByRole("region", { name: "Horizontal points" })).toContainText("62.4");
  await expect(page.getByRole("region", { name: "Vertical points" })).toContainText("Not measured");
  await expect(page.getByRole("button", { name: /Correct/ })).toHaveCount(0);
  await page.getByRole("combobox", { name: "Month" }).selectOption("2026-10");
  // T108 (D-105-3 for Film): changing the month closes the open card, so the
  // month's own week cards are what comes back.
  await expect(page.getByRole("button", { name: /Ranger \/ White/ })).toBeVisible();
  await expect(page).not.toHaveURL(/filmVehicle/);
  await expect(page.getByText("No approved measurements for this plant")).toHaveCount(0);
});

test("Film-only History keeps its month and vehicle keys separate and makes no T23 read", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  const filmReads = await mockFilmHistory(page);
  const historyReads: URL[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/history/")) historyReads.push(new URL(request.url()));
  });
  await page.goto(
    `/plant/AAT?dataView=history&dataDomain=film&month=2026-10&vehicle=${"a".repeat(64)}`,
  );
  // T108: Film has week cards of its own now, so "Week 2" is no longer proof
  // of a WaveScan read. The WaveScan section itself is.
  await expect(page.getByRole("button", { name: /Ranger \/ White/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "WaveScan History" })).toHaveCount(0);
  await expect(page).toHaveURL(/month=2026-10/);
  await expect(page).toHaveURL(/vehicle=aaaa/);
  await expect(page).toHaveURL(/dataDomain=film/);
  await page.screenshot({
    path: "test-results/screenshots/T50-history-film-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/screenshots/T50-history-film-mobile.png",
    fullPage: true,
  });
  expect(historyReads).toEqual([]);
  expect(
    filmReads.some(
      (url) => url.pathname.endsWith("summaries") && url.searchParams.get("month") === "2026-10",
    ),
  ).toBe(true);
});

test("Engineer WaveScan History keeps Correct and does not request film", async ({ page }) => {
  await mockHistory(page, "engineer");
  const filmReads: URL[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.includes("/api/v1/plants/") && url.pathname.includes("/filmthickness/"))
      filmReads.push(url);
  });
  await page.route("**/history/vehicles/*/points?*", (route) =>
    route.fulfill({ json: historyPoints() }),
  );
  await page.goto(
    `/plant/AAT?dataView=history&dataDomain=wavescan&month=2026-09&model=P703&color=White&week=2&vehicle=${historyVehicleId}`,
  );
  await expect(page.getByRole("button", { name: "Edit measurement 41" })).toBeVisible();
  await page.getByRole("button", { name: "Edit measurement 41" }).click();
  await expect(page.getByRole("button", { name: "Create correction" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Paint Appearance" })).toHaveValue("wavescan");
  expect(filmReads).toEqual([]);
});
