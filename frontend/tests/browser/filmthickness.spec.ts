import { expect, test } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { filmOverviewFixture } from "../film-overview-fixtures";

const vehicleId = "d".repeat(64);

async function mockFilm(page: Parameters<typeof mockHistory>[0], empty = false) {
  const reads: URL[] = [];
  await page.route("**/api/v1/plants/*/filmthickness/**", (route) => {
    const url = new URL(route.request().url());
    reads.push(url);
    const common = {
      plant_code: "FTM",
      plant_is_active: true,
      active_data_source: "filmthickness_active",
    };
    const vehicle = {
      logical_vehicle_id: vehicleId,
      plant_code: "FTM",
      measured_date: "2026-08-12",
      model: "P703 DBL RANGER",
      model_display_name: "Ranger",
      color: "Blue",
      serial_no: null,
      job_nos: ["J-42"],
      identity_complete: true,
      load_ids: [41, 42],
      source_files: ["cab.xlsx", "box.xlsx"],
      mapped_point_count: 1,
      expected_point_count: 94,
      incomplete: true,
    };
    if (url.pathname.endsWith("overview"))
      return route.fulfill({
        json: {
          ...filmOverviewFixture,
          model_options: ["P703 DBL RANGER"],
          color_options: [
            { color_name: "Blue", family_code: null, family_name: null, family_order: null },
            { color_name: "White", family_code: null, family_name: null, family_order: null },
          ],
          month: "2026-08",
          boxes: filmOverviewFixture.boxes.filter((box) => box.model_code === "P703 DBL RANGER"),
        },
      });
    if (url.pathname.endsWith("facets"))
      return route.fulfill({
        json: {
          ...common,
          default_month: empty ? null : "2026-08",
          months: empty ? [] : ["2026-08"],
          month: url.searchParams.get("month"),
          model: url.searchParams.get("model"),
          color: url.searchParams.get("color"),
          models: url.searchParams.has("month") ? ["P703 DBL RANGER"] : [],
          colors: url.searchParams.has("month") ? ["Blue"] : [],
        },
      });
    // T108: the flat grid became week cards, so the list read is now the
    // card's and this read is what the screen opens on.
    if (url.pathname.endsWith("summaries"))
      return route.fulfill({
        json: {
          ...common,
          month: url.searchParams.get("month"),
          model: url.searchParams.get("model"),
          color: url.searchParams.get("color"),
          weeks: empty
            ? []
            : [
                {
                  week: 2,
                  measured_date_min: "2026-08-12",
                  measured_date_max: "2026-08-12",
                  cards: [
                    {
                      model: "P703 DBL RANGER",
                      model_display_name: "Ranger",
                      color: "Blue",
                      vehicle_count: 1,
                      point_count: 2,
                      box_count: 1,
                      no_box_count: 0,
                      incomplete_count: 1,
                      measured_date_min: "2026-08-12",
                      measured_date_max: "2026-08-12",
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
          month: "2026-08",
          model: null,
          color: null,
          items: empty ? [] : [vehicle],
          page: { offset: 0, limit: 50, returned: empty ? 0 : 1, total: empty ? 0 : 1 },
        },
      });
    return route.fulfill({
      json: {
        ...common,
        vehicle,
        items: [
          {
            point_no: 22,
            point_code: "022LTFTDOOR",
            orientation: "V",
            src_location_text: "029LTFTDOOR",
            load_id: 41,
            source_row: 29,
            layers: { ecoat: "62.4", primer: null, base: "12.2", clear: null },
          },
          // T100 (Part D): a point the setting says does not count keeps its
          // readings and its H/V group, and says "Not counted" beside it.
          {
            point_no: 23,
            point_code: "023LTRRDOOR",
            orientation: "V",
            src_location_text: "023LTRRDOOR",
            load_id: 41,
            source_row: 30,
            layers: { ecoat: "60.1", primer: null, base: "11.8", clear: null },
            counted: false,
            is_complete_stop: false,
          },
          {
            point_no: 1,
            point_code: "001HOOD",
            orientation: "H",
            src_location_text: null,
            load_id: null,
            source_row: null,
            layers: { ecoat: null, primer: null, base: null, clear: null },
          },
          {
            point_no: 3,
            point_code: "003MISC",
            orientation: null,
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

test("Viewer opens History film grid with gold and plant labels, null slots, and distinct search keys", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  const reads = await mockFilm(page);
  const wavescan: string[] = [];
  const rawMeasurements: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/wavescan/overview")) wavescan.push(request.url());
    if (new URL(request.url()).pathname === "/api/v1/measurements")
      rawMeasurements.push(request.url());
  });
  await page.goto("/plant/FTM?dataView=history&dataDomain=film&month=2026-08");
  await expect(page.getByRole("heading", { name: "Film Thickness" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Month", exact: true })).toHaveValue("2026-08");
  await expect(page).toHaveURL(/month=2026-08/);
  // T108: Week -> card -> cars. The card is the new first click; the cars
  // behind it are the read this test already pinned.
  await page.getByRole("button", { name: /Ranger \/ Blue/ }).click();
  await expect(page).toHaveURL(/filmWeek=2/);
  await expect(page.getByRole("button", { name: /J-42/ })).toBeVisible();
  await page.getByRole("button", { name: /J-42/ }).click();
  await expect(page).toHaveURL(new RegExp(`filmVehicle=${vehicleId}`));
  await expect(page.getByRole("region", { name: "Horizontal points" })).toContainText("001HOOD");
  await expect(page.getByRole("region", { name: "Horizontal points" })).toContainText(
    "Not measured",
  );
  await expect(page.getByRole("region", { name: "Vertical points" })).toContainText("022LTFTDOOR");
  await expect(page.getByRole("region", { name: "Vertical points" })).toContainText("029LTFTDOOR");
  await expect(page.getByRole("region", { name: "Unassigned points" })).toContainText("003MISC");
  // T100 (Part D): the point that does not count is still in its own group,
  // with its readings, and marked -- it is not hidden.
  const vertical = page.getByRole("region", { name: "Vertical points" });
  await expect(vertical).toContainText("023LTRRDOOR");
  await expect(vertical).toContainText("60.1");
  await expect(page.getByTestId("not-counted-023LTRRDOOR")).toContainText("Not counted");
  await expect(page.getByTestId("not-counted-022LTFTDOOR")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Horizontal points" })).not.toContainText("0.0");
  expect(wavescan).toEqual([]);
  expect(rawMeasurements).toEqual([]);
  expect(
    reads.some(
      (url) => url.pathname.endsWith("vehicles") && url.searchParams.get("month") === "2026-08",
    ),
  ).toBe(true);
  await page.reload();
  // T108: the URL carries the open card and the car, so a reload comes back
  // to the points rather than to the week cards.
  await expect(page.getByRole("region", { name: "Vertical points" })).toContainText("029LTFTDOOR");
  await expect(page.getByRole("button", { name: /Correct/ })).toHaveCount(0);
  await page.screenshot({
    path: "test-results/evidence/T70/history-film-viewer-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/evidence/T70/history-film-viewer-mobile.png",
    fullPage: true,
  });
});

test("film empty plant uses empty copy and makes no vehicle request", async ({ page }) => {
  await mockHistory(page, "viewer");
  const reads = await mockFilm(page, true);
  await page.goto("/plant/FTM?dataView=history&dataDomain=film");
  await expect(
    page.getByText("No Film Thickness measurements for this plant", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/evidence/T70/history-film-empty-desktop.png",
    fullPage: true,
  });
  expect(reads.every((url) => url.pathname.endsWith("facets"))).toBe(true);
});

test("Engineer overview stays read only and uses T66 model and colour options", async ({
  page,
}) => {
  await mockHistory(page, "engineer");
  const reads = await mockFilm(page);
  await page.goto("/plant/FTM?paint=film&filmMonth=2026-08");
  await page.getByRole("button", { name: "P703 DBL RANGER", exact: true }).click();
  await expect(page).toHaveURL(/filmModel=P703/);
  await page.getByRole("button", { name: "Color", exact: true }).click();
  await page.getByRole("button", { name: "White", exact: true }).click();
  await expect(page).toHaveURL(/filmColors=.*Blue/);
  await expect
    .poll(() =>
      reads.some(
        (url) => url.pathname.endsWith("overview") && url.searchParams.get("colors") === "Blue",
      ),
    )
    .toBe(true);
  await expect(page.getByRole("button", { name: /Correct/ })).toHaveCount(0);
  expect(
    reads.some(
      (url) =>
        url.pathname.endsWith("facets") &&
        url.searchParams.has("color") &&
        !url.searchParams.has("month"),
    ),
  ).toBe(false);
});

test("film API refusal shows its message and correlation ID", async ({ page }) => {
  await mockHistory(page, "viewer");
  await page.route("**/api/v1/plants/*/filmthickness/facets**", (route) =>
    route.fulfill({
      status: 403,
      json: {
        statusCode: 403,
        error: "Forbidden",
        message: "Film read denied",
        correlationId: "film-403",
      },
    }),
  );
  await page.goto("/plant/FTM?dataView=history&dataDomain=film&month=2026-08");
  await expect(page.getByRole("alert")).toContainText("Film read denied");
  await expect(page.getByRole("alert")).toContainText("film-403");
});
