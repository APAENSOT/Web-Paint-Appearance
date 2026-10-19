import { expect, test } from "@playwright/test";
import { historyPoints, mockHistory, openHistoryPoint } from "../history-fixtures";

test("Viewer History uses API facets, keeps filters in the URL, and never fetches the parked raw list", async ({
  page,
}) => {
  const requests = await mockHistory(page, "viewer");
  const rawReads: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/measurements?")) rawReads.push(request.url());
  });
  await page.goto("/plant/AAT?dataView=measurements");
  await expect(page.getByRole("heading", { name: "Week 2", exact: true })).toBeVisible();
  await expect(page.getByText("Read only", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Edit measurement/ })).toHaveCount(0);
  await page.getByRole("combobox", { name: "Model", exact: true }).selectOption("U704");
  await expect(page).toHaveURL(/model=U704/);
  await expect(page.getByRole("combobox", { name: "Colour", exact: true })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "Colour", exact: true })).toContainText("Blue");
  expect(
    requests.some(
      (url) => url.pathname.endsWith("facets") && url.searchParams.get("model") === "U704",
    ),
  ).toBe(true);
  expect(rawReads).toEqual([]);
  await page.goto("/plant/fvl?dataView=history");
  await expect(
    page.getByText("No approved measurements for this plant", { exact: true }),
  ).toBeVisible();
});

test("History API errors quote the envelope and can be retried", async ({ page }) => {
  await mockHistory(page, "viewer");
  let fails = true;
  await page.route("**/history/summaries?*", (route) =>
    route.fulfill(
      fails
        ? {
            status: 503,
            json: {
              statusCode: 503,
              error: "Unavailable",
              message: "History offline",
              correlationId: "t24-history",
            },
          }
        : {
            json: {
              plant_code: "AAT",
              plant_is_active: true,
              active_data_source: "v_wavescan_active",
              month: "2026-09",
              model: null,
              color: null,
              weeks: [],
            },
          },
    ),
  );
  await page.goto("/plant/AAT?dataView=history");
  await expect(page.getByRole("alert")).toContainText("History offline");
  await expect(page.getByRole("alert")).toContainText("t24-history");
  fails = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(
    page.getByText("No approved measurements for this selection", { exact: true }),
  ).toBeVisible();
});

test("Admin correction refusal quotes the API envelope without retrying the write", async ({
  page,
}) => {
  await mockHistory(page, "admin");
  await page.route("**/history/vehicles/*/points?*", (route) =>
    route.fulfill({ json: historyPoints() }),
  );
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST") writes.push(new URL(request.url()).pathname);
  });
  await page.route("**/api/v1/measurements/41/corrections", (route) =>
    route.fulfill({
      status: 403,
      json: {
        statusCode: 403,
        error: "Forbidden",
        message: "Correction denied",
        correlationId: "t15-denied",
      },
    }),
  );
  await openHistoryPoint(page);
  await page.getByRole("button", { name: "Edit measurement 41", exact: true }).click();
  await page.getByLabel("CF", { exact: false }).fill("63");
  await page.getByLabel("Reason for correction").fill("Instrument check");
  await page.getByRole("button", { name: "Create correction", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("t15-denied");
  await expect(page.getByRole("alert")).toContainText("Correction denied");
  expect(writes).toEqual(["/api/v1/measurements/41/corrections"]);
});

test("Overview is the default plant lens; graded bays stay empty and do not fetch History", async ({
  page,
}) => {
  const overviewReads: string[] = [];
  const historyReads: string[] = [];
  await mockHistory(page, "viewer");
  await page.route("**/filmthickness/facets**", (route) =>
    route.fulfill({
      json: {
        plant_code: "AAT",
        plant_is_active: true,
        default_month: null,
        months: [],
        month: null,
        models: [],
        model: null,
        colors: [],
        color: null,
        active_data_source: "filmthickness_active",
      },
    }),
  );
  page.on("request", (request) => {
    if (request.url().includes("/wavescan/overview")) overviewReads.push(request.url());
    if (request.url().includes("/history/")) historyReads.push(request.url());
  });
  await page.goto("/plant/AAT");
  await expect(page.getByRole("button", { name: "Monthly Overview", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // T112: owner 2026-10-11 — WARNING reads Acceptable
  await expect(page.getByText("Acceptable", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("61.2", { exact: true }).first()).toBeVisible();
  const dashboard = page.locator("header[aria-label='Plant dashboard']");
  await expect(dashboard).toContainText("First Run OK");
  await expect(dashboard).not.toContainText("96.4");
  expect(overviewReads.length).toBeGreaterThan(0);
  expect(historyReads).toEqual([]);
  await page.getByRole("button", { name: "Film Thickness", exact: true }).click();
  await expect(page.getByText("No Film Thickness measurements for this plant.")).toBeVisible();
  const before = overviewReads.length;
  await expect.poll(() => overviewReads.length).toBe(before);
});

test("unknown metadata code uses honest copy and keeps route-scoped Overview", async ({ page }) => {
  await mockHistory(page, "viewer");
  await page.goto("/plant/sap");
  await expect(page.locator("header")).toContainText("Unknown plant: code not found in metadata.");
  await expect(page.getByRole("button", { name: "Monthly Overview", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

// The parked PlantDataPane and MeasurementTable retain focused coverage in tests/measurements.test.ts.
