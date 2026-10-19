import { expect, test } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { overviewPayload } from "../overview-fixtures";
import { filmOverviewFixture } from "../film-overview-fixtures";
import { mockLanding } from "../landing-fixture";

// GET /landing/status is controlled so the landing chrome never depends on live data.
test.beforeEach(async ({ page }) => mockLanding(page));

test("Monthly Overview is the default for every plant and Film Thickness does not request it", async ({
  page,
}) => {
  const reads: string[] = [];
  await mockHistory(page, "viewer");
  await page.route("**/filmthickness/overview**", (route) =>
    route.fulfill({
      json: {
        ...filmOverviewFixture,
        plant_code: "SAP",
        month: null,
        available_months: [],
        model_options: [],
        color_options: [],
        boxes: [],
      },
    }),
  );
  page.on("request", (request) => {
    if (request.url().includes("/wavescan/overview")) reads.push(request.url());
  });
  for (const code of ["FTM", "AAT", "FVL", "SAP"]) {
    await page.goto(`/plant/${code}`);
    await expect(
      page.getByRole("button", { name: "Monthly Overview", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "WaveScan", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  }
  expect(reads.length).toBeGreaterThan(0);
  const before = reads.length;
  await page.getByRole("button", { name: "Film Thickness", exact: true }).click();
  await expect(page.getByText("No Film Thickness measurements for this plant.")).toBeVisible();
  await page.waitForTimeout(200);
  expect(reads).toHaveLength(before);
  expect(reads.every((url) => !url.includes("micron"))).toBe(true);
});

test("FTM stacks Horizontal then Vertical from the API status and mean, using plant filter options", async ({
  page,
}) => {
  const reads: URL[] = [];
  await mockHistory(page, "viewer");
  page.on("request", (request) => {
    if (request.url().includes("/wavescan/overview")) reads.push(new URL(request.url()));
  });
  await page.goto("/plant/FTM");
  await expect(page.getByRole("heading", { name: "P703 DBL RAPTOR", exact: true })).toBeVisible();
  const raptor = page.getByRole("region", { name: "P703 DBL RAPTOR" });
  await expect(raptor.getByRole("heading", { name: "Horizontal · CF" })).toBeVisible();
  await expect(raptor.getByRole("heading", { name: "Vertical · CF" })).toBeVisible();
  // T112: owner 2026-10-11 — WARNING reads Acceptable
  await expect(raptor.getByText("Acceptable", { exact: true })).toBeVisible();
  await expect(raptor.getByText("61.2", { exact: true })).toBeVisible();
  await expect(raptor.getByText("Pass", { exact: true })).toBeVisible();
  await expect(raptor.getByText("No standard", { exact: true })).toBeVisible();
  await expect(raptor.getByText("57.4", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "P703 DBL RANGER", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Color", exact: true })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await page.getByRole("button", { name: "Color", exact: true }).click();
  await expect(page.getByRole("button", { name: "Aluminum Metallic", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Arctic White", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "P703 DBL RAPTOR", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByRole("button", { name: "P703 DBL RANGER", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByRole("button", { name: "Arctic White", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "P703 DBL RANGER", exact: true }).click();
  await expect(page.getByRole("heading", { name: "P703 DBL RANGER", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "P703 DBL RAPTOR", exact: true })).toBeVisible();
  await expect
    .poll(() => reads.some((url) => url.searchParams.getAll("model").includes("P703 DBL RAPTOR")))
    .toBe(true);
});

test("a month without calendar readings opens the latest available month", async ({ page }) => {
  await mockHistory(page, "viewer");
  await page.route("**/api/v1/plants/*/wavescan/overview**", (route) => {
    const url = new URL(route.request().url());
    const plant = url.pathname.split("/")[4];
    const month = url.searchParams.get("month");
    const payload = overviewPayload(plant, month);
    payload.available_months = ["2026-06"];
    payload.boxes = month === "2026-06" ? payload.boxes : [];
    return route.fulfill({ json: payload });
  });
  await page.goto("/plant/FTM");
  await expect(page.getByRole("button", { name: "2026-06", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByText("There are no active readings for this month.")).toHaveCount(0);
  await expect(page.getByText("61.2", { exact: true }).first()).toBeVisible();
});
