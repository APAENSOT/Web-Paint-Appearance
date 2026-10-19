import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import {
  mockHistory,
  openHistoryPoint,
  historyPoints,
  historyPoint,
  historyVehicle,
} from "../history-fixtures";

async function shot(page: Page, name: string) {
  await page.screenshot({
    path: fileURLToPath(new URL(`../../test-results/screenshots/T24-${name}.png`, import.meta.url)),
    fullPage: true,
    animations: "disabled",
  });
}
test("Admin History uses facets and API week cards, drills into distinct vehicles and points", async ({
  page,
}) => {
  const requests = await mockHistory(page, "admin");
  const forbidden: string[] = [];
  page.on("request", (r) => {
    if (/\/measurements\?|\/workbooks/.test(r.url())) forbidden.push(r.url());
  });
  await page.goto("/plant/aat?dataView=history");
  await expect(page.getByRole("heading", { name: "Week 2", exact: true })).toBeVisible();
  await expect(page.getByLabel("Month", { exact: true })).toHaveValue("2026-09");
  await expect(page).toHaveURL(/month=2026-09/);
  await expect(page.getByRole("button", { name: "Upload Data", exact: true })).toBeVisible();
  await shot(page, "admin-history");
  await page.getByRole("button", { name: /P703.*White.*3 vehicles/ }).click();
  await expect(page.getByRole("button", { name: /SECOND-SERIAL/ })).toBeVisible();
  await expect(page.getByText("Identity incomplete", { exact: true })).toBeVisible();
  await expect(page.getByText(/expected not available/)).toBeVisible();
  await page.getByRole("button", { name: /T09-TEST/ }).click();
  await expect(page.getByText("1 of 31 expected points", { exact: true })).toBeVisible();
  await expect(page.getByText("Source row: 2", { exact: true })).toBeVisible();
  await shot(page, "vehicle-points");
  await page.reload();
  await expect(page.locator('[data-measurement-id="41"]')).toBeVisible();
  expect(requests.find((r) => r.pathname.endsWith("vehicles"))?.searchParams.get("week")).toBe("2");
  expect(forbidden).toEqual([]);
});
test("Engineer correction retains T09 string body and refreshes active points", async ({
  page,
}) => {
  await mockHistory(page);
  let writes = 0;
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") posts.push(new URL(r.url()).pathname);
  });
  await page.route("**/api/v1/measurements/41/corrections", (r) => {
    expect(r.request().postDataJSON()).toEqual({ reason: "Instrument check", cf: "63.123456789" });
    writes++;
    return r.fulfill({
      json: {
        measurement: { ...historyPoint, plant: "AAT", measurement_id: 42, cf: "63.123456789" },
        superseded_measurement_id: 41,
        supersession_id: 7,
        audit_action: "measurement.correct",
        note: "Original retained.",
      },
    });
  });
  await page.route("**/history/vehicles/*/points?*", (r) =>
    r.fulfill({
      json: historyPoints(
        writes ? { ...historyPoint, measurement_id: 42, cf: "63.123456789" } : historyPoint,
      ),
    }),
  );
  await openHistoryPoint(page);
  await page.getByRole("button", { name: "Edit measurement 41", exact: true }).click();
  // T111: T43 - the SPA shows the attach chrome to every signed-in user and the
  // backend role decides, so the Upload Data tab stays mounted behind the
  // correction form. This test's claim is the correction body and the refresh.
  await expect(page.getByRole("button", { name: "Upload Data", exact: true })).toHaveCount(1);
  await shot(page, "engineer-correct");
  await page.getByLabel("CF", { exact: false }).fill("63.123456789");
  await page.getByLabel("Reason for correction").fill("Instrument check");
  await page.getByRole("button", { name: "Create correction", exact: true }).click();
  await expect(page.locator('[data-measurement-id="42"]')).toBeVisible();
  await expect(page.locator('[data-measurement-id="41"]')).toHaveCount(0);
  expect(writes).toBe(1);
  expect(posts).toEqual(["/api/v1/measurements/41/corrections"]);
});
test("Viewer is read only and a direct Upload Data link keeps the attach chrome", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  // T111: T43 - a forced `upload` is no longer coerced to History: the SPA shows
  // the attach chrome to every signed-in user and the backend role decides. The
  // Viewer's read-only claim below is unchanged.
  await page.goto("/plant/aat?dataView=upload");
  await expect(page.getByRole("heading", { name: "Upload Data", exact: true })).toBeVisible();
  await expect(page.getByLabel("Attach workbook", { exact: true })).toBeEnabled();
  await openHistoryPoint(page);
  await expect(
    page.getByRole("heading", { name: "Week 2 / P703 / White", exact: true }),
  ).toBeVisible();
  await expect(page.locator('[data-measurement-id="41"]')).toBeVisible();
  await expect(page.getByRole("button", { name: /Edit measurement/ })).toHaveCount(0);
  // T111: T43 - the Upload Data tab is chrome for every signed-in user, so read
  // only means no Correct control, not a missing tab.
  await expect(page.getByRole("button", { name: "Upload Data", exact: true })).toHaveCount(1);
  await shot(page, "viewer-history");
});
test("FVL stays an honest empty History", async ({ page }) => {
  const requests = await mockHistory(page, "viewer");
  await page.goto("/plant/fvl?dataView=history");
  await expect(
    page.getByText("No approved measurements for this plant", { exact: true }),
  ).toBeVisible();
  await shot(page, "fvl-empty");
  expect(requests.every((r) => r.pathname.endsWith("facets"))).toBe(true);
});

test("facets cascade, All model permits a colour, and filter changes close drills", async ({
  page,
}) => {
  const requests = await mockHistory(page, "viewer");
  await page.goto("/plant/aat?dataView=history");
  await expect(page.getByRole("heading", { name: "Week 2", exact: true })).toBeVisible();
  expect(requests[0].search).toBe("");
  await page.getByLabel("Colour", { exact: true }).selectOption("White");
  await expect
    .poll(() =>
      requests
        .filter((r) => r.pathname.endsWith("summaries"))
        .at(-1)
        ?.searchParams.get("color"),
    )
    .toBe("White");
  expect(
    requests
      .filter((r) => r.pathname.endsWith("summaries"))
      .at(-1)
      ?.searchParams.has("model"),
  ).toBe(false);
  await page.getByLabel("Model", { exact: true }).selectOption("U704");
  await expect(page.getByLabel("Colour", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Colour", { exact: true }).locator("option")).toHaveText([
    "All",
    "Blue",
  ]);
  await openHistoryPoint(page);
  await page.getByLabel("Month", { exact: true }).selectOption("2026-06");
  await expect(page).not.toHaveURL(/vehicle=|week=|model=|color=/);
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue("");
});

test("Admin Upload Data and History requests are mutually exclusive", async ({ page }) => {
  const requests = await mockHistory(page, "admin");
  let workbooks = 0;
  await page.route("**/api/v1/plants/AAT/workbooks?*", (r) => {
    workbooks++;
    return r.fulfill({
      json: {
        plant_code: "AAT",
        plant_is_active: true,
        items: [],
        page: { offset: 0, limit: 200, returned: 0, total: 0 },
        uploaded_month: "2026-09",
      },
    });
  });
  await page.goto("/plant/aat?dataView=upload");
  await expect(page.getByRole("heading", { name: "Upload Data", exact: true })).toBeVisible();
  // T111: T106 judgement call 4 - the plant Upload Data input is named
  // "Attach workbook"; "Upload workbooks" is the /batches intake screen.
  await expect(page.getByLabel("Attach workbook", { exact: true })).toBeEnabled();
  expect(requests).toHaveLength(0);
  const workbookCount = workbooks;
  await page.getByRole("button", { name: "Measurement History", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Week 2", exact: true })).toBeVisible();
  expect(workbooks).toBe(workbookCount);
  const historyCount = requests.length;
  await page.getByRole("button", { name: "Upload Data", exact: true }).click();
  await page.getByRole("button", { name: "Refresh uploads", exact: true }).click();
  await expect.poll(() => workbooks).toBeGreaterThan(workbookCount);
  expect(requests).toHaveLength(historyCount);
});

test("an unlisted month falls back to the default and the API envelope does not loop", async ({
  page,
}) => {
  await page.clock.install();
  await mockHistory(page, "viewer");
  const monthReads: string[] = [];
  // T111: T50 - the History month menu is the union of the WaveScan and Film
  // facet months, and T49 - a month the menu does not offer falls back to the
  // API default. So `month=2026-13` never reaches the API at all, and the 422
  // envelope has to answer the month-scoped facets read that does fire.
  await page.route("**/history/facets**", (r) => {
    const month = new URL(r.request().url()).searchParams.get("month");
    if (!month) return r.fallback();
    monthReads.push(month);
    return r.fulfill({
      status: 422,
      json: {
        statusCode: 422,
        error: "Invalid month",
        message: "month must be YYYY-MM",
        correlationId: "t24-month",
      },
    });
  });
  await page.goto("/plant/aat?dataView=history&month=2026-13");
  await expect(page.getByText("month must be YYYY-MM", { exact: true })).toBeVisible();
  await expect(page.getByText("Correlation ID: t24-month", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/month=2026-09/);
  expect([...new Set(monthReads)]).toEqual(["2026-09"]);
  // React StrictMode can cancel and remount the initial read in development.
  expect(monthReads.length).toBeLessThanOrEqual(2);
  const settledReads = monthReads.length;
  await page.clock.runFor(60000);
  expect(monthReads.length).toBe(settledReads);
});

test("vehicles and points paginate using API totals and offsets", async ({ page }) => {
  await mockHistory(page);
  const offsets: string[] = [];
  await page.route("**/history/vehicles?*", (r) => {
    const q = new URL(r.request().url()).searchParams;
    offsets.push(q.get("offset")!);
    return r.fulfill({
      json: {
        plant_code: "AAT",
        plant_is_active: true,
        month: "2026-09",
        week: 2,
        model: "P703",
        color: "White",
        items: [
          { ...historyVehicle, serial_no: q.get("offset") === "0" ? "FIRST-PAGE" : "SECOND-PAGE" },
        ],
        page: { offset: Number(q.get("offset")), limit: 50, total: 2, returned: 1 },
        active_data_source: "v_wavescan_active",
      },
    });
  });
  await page.goto("/plant/aat?dataView=history&month=2026-09&week=2&model=P703&color=White");
  await expect(page.getByRole("button", { name: /FIRST-PAGE/ })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("button", { name: /SECOND-PAGE/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  expect([...new Set(offsets)]).toEqual(["0", "1"]);
  await page.route("**/history/vehicles/*/points?*", (r) => {
    const offset = Number(new URL(r.request().url()).searchParams.get("offset"));
    return r.fulfill({
      json: {
        ...historyPoints({ ...historyPoint, measurement_id: offset === 0 ? 41 : 42 }),
        page: { offset, limit: 50, total: 2, returned: 1 },
      },
    });
  });
  await page.getByRole("button", { name: /SECOND-PAGE/ }).click();
  await expect(page.locator('[data-measurement-id="41"]')).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator('[data-measurement-id="42"]')).toBeVisible();
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
});

test("points and correction fit a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockHistory(page);
  await openHistoryPoint(page);
  await page.getByRole("button", { name: "Edit measurement 41", exact: true }).click();
  await expect(page.getByLabel("Reason for correction")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await shot(page, "vehicle-mobile");
});

test("API week and vehicle identity are authoritative even for repeated serials", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  await page.route("**/history/summaries?*", (r) =>
    r.fulfill({
      json: {
        plant_code: "AAT",
        plant_is_active: true,
        month: "2026-09",
        model: null,
        color: null,
        weeks: [
          {
            week: 5,
            measured_date_min: "2026-09-13",
            measured_date_max: "2026-09-13",
            cards: [
              {
                model: "P703",
                color: "White",
                vehicle_count: 2,
                point_count: 2,
                measured_date_min: "2026-09-13",
                measured_date_max: "2026-09-13",
              },
            ],
          },
        ],
        active_data_source: "v_wavescan_active",
      },
    }),
  );
  await page.route("**/history/vehicles?*", (r) => {
    expect(new URL(r.request().url()).searchParams.get("week")).toBe("5");
    return r.fulfill({
      json: {
        plant_code: "AAT",
        plant_is_active: true,
        month: "2026-09",
        week: 5,
        model: "P703",
        color: "White",
        items: [historyVehicle, { ...historyVehicle, load_id: 124, vehicle_id: "d".repeat(64) }],
        page: { limit: 50, offset: 0, total: 2, returned: 2 },
        active_data_source: "v_wavescan_active",
      },
    });
  });
  await page.goto("/plant/aat?dataView=history&month=2026-09");
  await expect(page.getByRole("heading", { name: "Week 5", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Week 2", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: /P703.*White.*2 vehicles/ }).click();
  await expect(page.getByRole("button", { name: /T09-TEST/ })).toHaveCount(2);
});

test("retired correction prefill quotes 404 and re-reads the vehicle without a write", async ({
  page,
}) => {
  await mockHistory(page);
  let retired = false;
  let pointReads = 0;
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") writes.push(r.url());
  });
  await page.route("**/history/vehicles/*/points?*", (r) => {
    pointReads++;
    return r.fulfill({
      json: historyPoints(retired ? { ...historyPoint, measurement_id: 42 } : historyPoint),
    });
  });
  await page.route("**/api/v1/measurements/41", (r) => {
    retired = true;
    return r.fulfill({
      status: 404,
      json: {
        statusCode: 404,
        error: "Not found",
        message: "Measurement retired",
        correlationId: "t24-prefill",
      },
    });
  });
  await openHistoryPoint(page);
  const initialReads = pointReads;
  await page.getByRole("button", { name: "Edit measurement 41", exact: true }).click();
  await expect(page.locator('[data-measurement-id="42"]')).toBeVisible();
  await expect(page.getByText("Correlation ID: t24-prefill", { exact: true })).toBeVisible();
  expect(pointReads).toBeGreaterThan(initialReads);
  expect(writes).toEqual([]);
});

test("T53 History heading uses the API plant panel label", async ({ page }) => {
  await mockHistory(page, "viewer");
  await openHistoryPoint(page);
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Edit measurement/ })).toHaveCount(0);
  const point = page.locator('[data-measurement-id="41"]');
  // T94 CHANGE (D-94-4): the heading is the stored POSITION, so a rough
  // spelling is never displayed as a position. The fixture's own
  // `src_zone_text` is `01 RRHOOD` and its `panel_label` is `RRHOOD`.
  await expect(point.getByRole("heading", { name: "RRHOOD", exact: true })).toBeVisible();
  await expect(point.getByText("Catalogue zone: RRHOOD", { exact: true })).toBeVisible();
  await point.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "test-results/screenshots/T53-history-panel-label-desktop.png",
    animations: "disabled",
  });
});
