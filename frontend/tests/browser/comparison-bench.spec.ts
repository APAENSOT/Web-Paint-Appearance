import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { candidatesFor, mockComparison } from "../comparison-fixtures";
import { overviewBox } from "../overview-fixtures";
import { filmBox, filmOverviewFixture } from "../film-overview-fixtures";
import { vehicleVisuals } from "../studio-fixtures";

// mockComparison serves model P703 with cars in 2026-06 and 2026-07; the overviews below give
// that model boxes so the deck cards and bench charts have something to draw.
const box = (color_name: string, orient: "Horizontal" | "Vertical", mean: string) => ({
  ...overviewBox,
  model_code: "P703",
  color_name,
  orient,
  mean,
});

async function mockBench(page: Page) {
  await mockComparison(page);
  await page.route("**/comparison/vehicle-visuals**", (route) =>
    route.fulfill({
      json: vehicleVisuals(new URL(route.request().url()).searchParams.getAll("vehicle_id")),
    }),
  );
  await page.route("**/api/v1/plants/*/wavescan/overview**", (route) => {
    const month = new URL(route.request().url()).searchParams.get("month") ?? "2026-07";
    const json: components["schemas"]["WavescanOverviewOut"] = {
      plant_code: "AAT",
      plant_is_active: true,
      month,
      models: [],
      colors: [],
      available_months: ["2026-07", "2026-06"],
      model_options: ["P703"],
      // API family order, deliberately not alphabetical.
      color_options: [
        { color_name: "Meteor Grey", family_code: "MM" },
        { color_name: "Arctic White", family_code: "LS" },
      ],
      // June has no Meteor Grey: the chart must not leave a blank slot for it.
      boxes:
        month === "2026-06"
          ? [box("Arctic White", "Horizontal", "58"), box("Arctic White", "Vertical", "48")]
          : [
              box("Arctic White", "Horizontal", "61"),
              box("Arctic White", "Vertical", "50"),
              box("Meteor Grey", "Horizontal", "63"),
              box("Meteor Grey", "Vertical", "52"),
            ],
      active_data_source: "v_wavescan_active",
    };
    return route.fulfill({ json });
  });
  await page.route("**/api/v1/plants/*/filmthickness/overview**", (route) => {
    const month = new URL(route.request().url()).searchParams.get("month") ?? "2026-07";
    return route.fulfill({
      json: {
        ...filmOverviewFixture,
        month,
        available_months: ["2026-07", "2026-06"],
        boxes: (["H", "V"] as const).map((orient) =>
          filmBox({ model_code: "P703", color_name: "Arctic White", layer_code: "ECOAT", orient }),
        ),
      },
    });
  });
}

async function openComparison(page: Page, url = "/plant/AAT") {
  await page.goto(url);
  if ((page.viewportSize()?.width ?? 1440) < 1024)
    await page.getByRole("button", { name: "Views & filters" }).click();
  await page.getByRole("button", { name: "Comparison", exact: true }).click();
}

const slots = (page: Page) =>
  page.getByRole("list", { name: "On the bench" }).locator(".cmp-slot__title");

test("deck to bench: preset months, baseline, family colour order, no blank slots, car overlay and spectrum", async ({
  page,
}) => {
  await mockBench(page);
  await openComparison(page);
  await expect(page.getByRole("article", { name: "Jul 2026" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Jun 2026" })).toBeVisible();

  await page.getByRole("button", { name: "Latest vs previous", exact: true }).click();
  await expect(slots(page)).toHaveText(["Jun 2026", "Jul 2026"]);
  await expect(page.getByRole("button", { name: "Jun 2026 is the baseline" })).toBeVisible();

  const horizontal = page.getByRole("region", { name: "P703 Horizontal", exact: true });
  await expect(horizontal.locator('[data-testid^="comparison-box-"]')).toHaveCount(3);
  await expect(horizontal.locator('[data-testid^="comparison-gap-"]')).toHaveCount(0);
  await expect(horizontal.getByTestId("comparison-baseline")).toHaveCount(1);
  await expect(horizontal.locator(".cmp-colour-label tspan")).toHaveText([
    "Meteor Grey",
    "Arctic White",
  ]);

  // Focus one colour from the chart, then bring every colour back.
  await horizontal.getByRole("button", { name: "Focus Arctic White" }).click();
  await expect(horizontal.locator(".cmp-colour-label")).toHaveCount(1);
  await horizontal.getByRole("button", { name: "Show all colours" }).click();
  await expect(horizontal.locator(".cmp-colour-label")).toHaveCount(2);

  await page
    .getByRole("article", { name: "Jul 2026" })
    .getByRole("button", { name: "Cars", exact: true })
    .click();
  const [car] = candidatesFor("WAVESCAN").filter(
    (c) => c.measured_date.startsWith("2026-07") && c.serial_no,
  );
  await page
    .getByRole("button", { name: `Add ${car.serial_no} to bench`, exact: true })
    .first()
    .click();
  await expect(slots(page)).toHaveCount(3);
  await expect(horizontal.getByTestId("comparison-car-marker")).toHaveCount(1);
  await expect(
    page.getByRole("region", { name: "Horizontal structure spectrum", exact: true }),
  ).toBeVisible();

  await page
    .getByRole("group", { name: "Colour lines by" })
    .getByRole("button", { name: "Location" })
    .click();
  await expect(page.getByRole("list", { name: "Horizontal lines" })).toContainText("Hood");
  const spectrum = page.getByRole("region", { name: "Horizontal structure spectrum", exact: true });
  await spectrum.locator(".recharts-line-dots circle").first().hover();
  await expect(spectrum.locator(".cmp-tip")).toContainText(car.color!);
  await expect(spectrum.locator(".cmp-tip")).toContainText(car.measured_date);

  await page.getByRole("button", { name: "Table", exact: true }).first().click();
  await expect(page.getByRole("table").first()).toContainText("Arctic White");
});

test("paint switches restore separate WaveScan and Film benches", async ({ page }) => {
  await mockBench(page);
  await openComparison(page);
  await page.getByRole("button", { name: "Add Jul 2026 to bench", exact: true }).click();
  await page
    .getByRole("group", { name: "Measurement" })
    .getByRole("button", { name: "Film Thickness" })
    .click();
  await page.getByRole("button", { name: "Add Jun 2026 to bench", exact: true }).click();
  await expect(slots(page)).toHaveText(["Jun 2026"]);
  await expect(page.getByRole("region", { name: "P703 Horizontal", exact: true })).toBeVisible();
  await page
    .getByRole("group", { name: "Measurement" })
    .getByRole("button", { name: "WaveScan", exact: true })
    .click();
  await expect(slots(page)).toHaveText(["Jul 2026"]);
  await page.getByRole("button", { name: "Film Thickness", exact: true }).first().click();
  await expect(slots(page)).toHaveText(["Jun 2026"]);
});

test("changing models retargets selected months, keeps cars, and survives a shared link", async ({
  page,
}, info) => {
  await mockBench(page);
  const other = {
    ...candidatesFor("WAVESCAN")[0],
    vehicle_id: "c".repeat(64),
    model: "U704",
    serial_no: "U704-FIXTURE",
    measured_date: "2026-07-03",
  };
  const pointRequests: URL[] = [];
  await page.route("**/comparison/vehicles**", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("model") !== "U704") return route.fallback();
    const hasMonth = !url.searchParams.getAll("month").includes("2026-06");
    if (!hasMonth && url.searchParams.getAll("month").length === 1)
      return route.fulfill({ status: 422, json: { detail: "model is not offered in this month" } });
    return route.fulfill({
      json: {
        plant_code: "AAT",
        domain: "WAVESCAN",
        available_months: ["2026-07"],
        model_options: ["P703", "U704"],
        color_options: ["Arctic White"],
        week_options: [],
        items: hasMonth ? [other] : [],
        page: { total: hasMonth ? 1 : 0, offset: 0, limit: 50, returned: hasMonth ? 1 : 0 },
      },
    });
  });
  await page.route("**/comparison/points**", (route) => {
    const url = new URL(route.request().url());
    pointRequests.push(url);
    if (url.searchParams.get("model") !== "U704") return route.fallback();
    expect(url.searchParams.getAll("vehicle_id")).toEqual([other.vehicle_id]);
    return route.fulfill({
      json: {
        domain: "WAVESCAN",
        model: "U704",
        metric: url.searchParams.get("metric"),
        columns: [other],
        locations: [
          {
            point_no: 1,
            code: "OTHER_HOOD",
            orientation: "H",
            cells: [
              {
                vehicle_id: other.vehicle_id,
                readings: [{ value: "18.75", measurement_id: 8000 }],
                missing: false,
              },
            ],
          },
        ],
        unaligned_locations: [],
      },
    });
  });
  await page.route("**/wavescan/overview**", (route) =>
    route.fulfill({
      json: {
        plant_code: "AAT",
        month: "2026-07",
        available_months: ["2026-07"],
        color_options: [{ color_name: "Arctic White" }],
        boxes: [
          box("Arctic White", "Horizontal", "61"),
          { ...box("Arctic White", "Horizontal", "45"), model_code: "U704" },
        ],
      },
    }),
  );
  await openComparison(page);
  await page.getByRole("button", { name: "Add Jul 2026 to bench", exact: true }).click();
  await page.getByRole("button", { name: "Add Jun 2026 to bench", exact: true }).click();
  await page
    .getByRole("article", { name: "Jul 2026", exact: true })
    .getByRole("button", { name: "Cars", exact: true })
    .click();
  await page
    .getByRole("button", { name: /^Add VIN-.*to bench$/ })
    .first()
    .click();
  await page.getByRole("combobox", { name: "Vehicle model" }).selectOption("U704");
  await expect(page.getByRole("list", { name: "On the bench" })).toContainText("U704");
  await expect(page.getByRole("list", { name: "On the bench" })).not.toContainText("Jun 2026");
  await expect(page.getByRole("status")).toContainText("1 month has no readings");
  await page.locator(".cmp-notice").getByRole("button", { name: "Undo" }).click();
  await expect(page.getByRole("combobox", { name: "Vehicle model" })).toHaveValue("P703");
  await expect(page.getByRole("list", { name: "On the bench" })).toContainText("Jun 2026");
  await page.getByRole("combobox", { name: "Vehicle model" }).selectOption("U704");
  await expect(page.getByRole("list", { name: "On the bench" })).not.toContainText("Jun 2026");
  await page.getByRole("button", { name: "Add U704-FIXTURE to bench", exact: true }).click();
  await expect(slots(page)).toHaveCount(3);
  await expect(page.getByRole("group", { name: "Cars" })).toContainText(
    "Arctic White · 2026-07-03",
  );
  await expect(page.getByLabel("Car line patterns")).toContainText("Arctic White · 2026-07-03");
  await expect(page.getByRole("region", { name: "U704 Horizontal", exact: true })).toBeVisible();
  await expect(page.getByRole("list", { name: "Horizontal lines" })).toContainText("U704");
  await expect(page.getByRole("list", { name: "Horizontal lines" })).toContainText("P703");
  expect(pointRequests.some((url) => url.searchParams.get("model") === "P703")).toBeTruthy();
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("button", { name: "Copy link", exact: true }).click();
  const href = await page.evaluate(() => navigator.clipboard.readText());
  await page.goto(href);
  await expect(slots(page)).toHaveCount(3);
  await expect(page.getByRole("list", { name: "Horizontal lines" })).toContainText("U704");
  await page.screenshot({ path: info.outputPath("cross-model-desktop.png"), fullPage: true });
});

for (const width of [390, 1440])
  test(`Film layers and friendly filters at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockBench(page);
    await openComparison(page);
    await page
      .getByRole("group", { name: "Measurement" })
      .getByRole("button", { name: "Film Thickness", exact: true })
      .click();
    await page.getByRole("button", { name: "Add Jul 2026 to bench", exact: true }).click();
    await page
      .getByRole("article", { name: "Jul 2026", exact: true })
      .getByRole("button", { name: "Cars", exact: true })
      .click();
    await page
      .getByRole("button", { name: /^Add VIN-.*to bench$/ })
      .first()
      .click();
    const layers = page.getByRole("group", { name: "Paint layer", exact: true });
    await expect(layers.getByRole("button", { name: "E-coat", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await layers.getByRole("button", { name: "Base", exact: true }).click();
    await expect(layers.locator('[aria-pressed="true"]')).toHaveCount(1);
    await expect(
      page
        .getByRole("group", { name: "Film layer", exact: true })
        .getByRole("button", { name: "Base", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("heading", { name: "Vertical · Base" })).toBeVisible();
    await page.locator(".cmp-filter-group summary").first().click();
    await expect(page.getByRole("group", { name: "Colour", exact: true })).toBeVisible();
    await page
      .getByRole("group", { name: "Colour", exact: true })
      .getByRole("button", { name: "Arctic White", exact: true })
      .click();
    await expect(page.locator(".cmp-filter-group summary").first()).toContainText("1 selected");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
    await page.evaluate(() => document.documentElement.classList.toggle("dark", true));
    await page.screenshot({ path: info.outputPath(`film-filters-${width}.png`), fullPage: true });
  });

test("Film cross-model car inspection sends separate catalogue requests", async ({ page }) => {
  await mockBench(page);
  const first = candidatesFor("FILMTHICKNESS")[0];
  const other = { ...candidatesFor("FILMTHICKNESS")[1], vehicle_id: "d".repeat(64), model: "U704" };
  const calls: URL[] = [];
  await page.route("**/comparison/points**", (route) => {
    const url = new URL(route.request().url());
    calls.push(url);
    const car = url.searchParams.get("model") === "U704" ? other : first;
    expect(url.searchParams.getAll("vehicle_id")).toEqual([car.vehicle_id]);
    expect(url.searchParams.get("domain")).toBe("FILMTHICKNESS");
    return route.fulfill({
      json: {
        domain: "FILMTHICKNESS",
        model: car.model,
        metric: url.searchParams.get("metric"),
        columns: [car],
        locations: [
          {
            point_no: 1,
            code: "001HOOD",
            orientation: "H",
            cells: [
              {
                vehicle_id: car.vehicle_id,
                readings: [{ value: car === first ? "20.5" : "24.75", measurement_id: null }],
                missing: false,
              },
            ],
          },
        ],
        unaligned_locations: [],
      },
    });
  });
  const shared = {
    domain: "FILMTHICKNESS",
    model: "P703",
    months: [],
    cars: [first.vehicle_id, other.vehicle_id],
    carModels: { [first.vehicle_id]: "P703", [other.vehicle_id]: "U704" },
    baseline: null,
  };
  await page.goto(`/plant/AAT?compare=${encodeURIComponent(JSON.stringify(shared))}`);
  await expect(slots(page)).toHaveCount(2);
  const profile = page.getByRole("region", { name: "Horizontal location profile", exact: true });
  await profile.getByRole("button", { name: "Table", exact: true }).click();
  await expect(profile.getByRole("table")).toContainText("P703 · 01 001HOOD");
  await expect(profile.getByRole("table")).toContainText("U704 · 01 001HOOD");
  await expect(profile.getByRole("table")).toContainText("24.75");
  expect(new Set(calls.map((url) => url.searchParams.get("model")))).toEqual(
    new Set(["P703", "U704"]),
  );
});

test("a shared link rebuilds the bench and opens Comparison", async ({ page }) => {
  await mockBench(page);
  const car = candidatesFor("WAVESCAN").find((c) => c.serial_no)!;
  const shared = {
    domain: "WAVESCAN",
    model: "P703",
    months: ["2026-06", "2026-07"],
    cars: [car.vehicle_id],
    baseline: "2026-06",
  };
  await page.goto(`/plant/AAT?compare=${encodeURIComponent(JSON.stringify(shared))}`);
  await expect(slots(page)).toHaveText(["Jun 2026", "Jul 2026", car.serial_no!]);
  await expect(page.getByRole("button", { name: "Jun 2026 is the baseline" })).toBeVisible();
  await expect(page).not.toHaveURL(/compare=/);
});
