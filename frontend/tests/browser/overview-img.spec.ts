/**
 * Overview IMG popup over the landing map, against controlled fixtures.
 *
 * Only the two /img/overview reads are mocked; the landing page itself runs as it is.
 * The fixture values are invented for this test and are never shipped: the point is the
 * layout, the states and the access rules, not the numbers.
 */
import { expect, test, type Page, type Route } from "@playwright/test";
import { mockLanding } from "../landing-fixture";

// GET /landing/status is controlled so the landing chrome never depends on live data.
test.beforeEach(async ({ page }) => mockLanding(page));

const SHOTS = "test-results/img-polish";
const none = {
  SETTING_EXCLUDED: 0,
  INCOMPLETE_TOTAL: 0,
  UNKNOWN_ORIENTATION: 0,
  INVALID_VALUE: 0,
  DUPLICATE_LAYER: 0,
};

function series(
  plant: string,
  family: string,
  metric: "CF" | "FILM",
  orient: "H" | "V",
  mean: string | null,
  measure: string,
  over: Record<string, unknown> = {},
) {
  const film = metric === "FILM";
  return {
    id: `${plant}|${family}|${metric}|${orient}|${film ? measure : "-"}`,
    plant_code: plant,
    family_key: family,
    family_name: family,
    orient,
    metric,
    unit: film ? "micron" : "CF",
    film_measure: film ? measure : null,
    mean,
    included_count: mean === null ? 0 : 12,
    count_unit: film
      ? measure === "CALCULATED_TOTAL"
        ? "FILM_POINT"
        : "LAYER_READING"
      : "CF_READING",
    availability: mean === null ? "NO_ELIGIBLE_READINGS" : "AVAILABLE",
    member_models: [{ model_code: `${family} MODEL`, model_name: `${family} MODEL` }],
    models: mean === null ? [] : [{ key: `${family} MODEL`, included_count: 12 }],
    colors:
      mean === null
        ? []
        : [
            { key: "Arctic White", included_count: 7 },
            { key: "Meteor Grey", included_count: 5 },
          ],
    locations: mean === null ? [] : [{ key: "HOOD", included_count: 12 }],
    exclusions: none,
    ...over,
  };
}

function report(month: string, measure: string) {
  const film =
    measure === "CALCULATED_TOTAL" ? ["101.3513274509803921568627451", "99.19"] : ["21.5", "20.75"];
  return {
    month,
    film_measure: measure,
    plants: ["FTM", "FVL", "SAP", "AAT"],
    source: "fixture",
    aggregation: "Fixture aggregation note.",
    series:
      month === "2099-03"
        ? []
        : [
            series("FTM", "P703", "CF", "H", "63.87679551522943037974683544", measure),
            series("FTM", "P703", "CF", "V", "52.95", measure),
            series("FTM", "P703", "FILM", "H", film[0], measure),
            series("FTM", "P703", "FILM", "V", film[1], measure),
            series("FVL", "CX743", "FILM", "H", "108.27", measure),
            series("FVL", "CX743", "FILM", "V", "112.58", measure),
            series("FVL", "V363", "FILM", "H", null, measure, {
              availability: "EXCLUDED_OR_INCOMPLETE",
              exclusions: { ...none, SETTING_EXCLUDED: 2, INCOMPLETE_TOTAL: 5 },
            }),
            series("FVL", "V363", "FILM", "V", null, measure),
            series("AAT", "P703", "CF", "H", "62.59", measure),
            series("AAT", "P703", "CF", "V", "50.29", measure),
            series("AAT", "U704", "CF", "H", "63.70", measure),
            series("AAT", "U704", "CF", "V", "51.91", measure),
            series("AAT", "UNMAPPED:X999", "CF", "H", "55.5", measure, { family_name: "X999" }),
            series("AAT", "UNMAPPED:X999", "CF", "V", "50.5", measure, { family_name: "X999" }),
          ],
  };
}

function colour(plant: string, color: string, orient: "H" | "V", mean: string | null, over = {}) {
  return {
    id: `${plant}|${color}|CF|${orient}|-`,
    plant_code: plant,
    color_name: color,
    orient,
    unit: "CF",
    mean,
    included_count: mean === null ? 0 : 9,
    count_unit: "CF_READING",
    availability: mean === null ? "EXCLUDED_OR_INCOMPLETE" : "AVAILABLE",
    member_models: [{ model_code: "P703 DBL RANGER", model_name: "P703 DBL RANGER" }],
    models: mean === null ? [] : [{ key: "P703 DBL RANGER", included_count: 9 }],
    locations: mean === null ? [] : [{ key: "HOOD", included_count: 9 }],
    exclusions: mean === null ? { ...none, SETTING_EXCLUDED: 4 } : none,
    ...over,
  };
}

/** Already ranked, as the API returns it: H then V, mean descending, nulls last. */
function colours(month: string) {
  return {
    month,
    plants: ["FTM", "FVL", "SAP", "AAT"],
    source: "fixture",
    aggregation: "Fixture colour aggregation note.",
    series: [
      colour("AAT", "Absolute / Shadow Black", "H", "131.4"),
      colour("FTM", "Arctic White", "H", "120.25"),
      colour("AAT", "Arctic White", "H", "118"),
      colour("SAP", "Lucid Red", "H", "96.5"),
      colour("FTM", "Code Orange", "H", null),
      colour("FTM", "Arctic White", "V", "110.1"),
      colour("AAT", "Absolute / Shadow Black", "V", "102.9"),
    ],
  };
}

async function mockImg(
  page: Page,
  {
    months = ["2099-02", "2099-01", "2099-03"],
    failMonths = false,
    delay = 0,
  }: { months?: string[]; failMonths?: boolean; delay?: number } = {},
) {
  const reads: URL[] = [];
  const state = { failing: failMonths };
  await page.route("**/api/v1/img/overview/months", async (route: Route) => {
    if (delay) await new Promise((r) => setTimeout(r, delay));
    if (state.failing)
      return route.fulfill({
        status: 500,
        json: {
          statusCode: 500,
          error: "Internal Server Error",
          message: "Fixture failure",
          correlationId: "img-500",
        },
      });
    return route.fulfill({
      json: { months, plants: ["FTM", "FVL", "SAP", "AAT"], source: "fixture" },
    });
  });
  await page.route("**/api/v1/img/colors?**", (route: Route) => {
    const url = new URL(route.request().url());
    reads.push(url);
    return route.fulfill({ json: colours(url.searchParams.get("month")!) });
  });
  await page.route("**/api/v1/img/overview?**", (route: Route) => {
    const url = new URL(route.request().url());
    reads.push(url);
    return route.fulfill({
      json: report(
        url.searchParams.get("month")!,
        url.searchParams.get("film_measure") ?? "CALCULATED_TOTAL",
      ),
    });
  });
  return Object.assign(reads, { heal: () => (state.failing = false) });
}

const trigger = (page: Page) => page.getByRole("button", { name: /Overview IMG/ });
const colorTrigger = (page: Page) => page.getByRole("button", { name: /IMG Color/ });
const dialog = (page: Page) => page.getByRole("dialog", { name: "Overview IMG" });

for (const theme of ["dark", "light"] as const) {
  test(`native choices stay readable and keyboard usable in ${theme} theme`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("ct-theme", value), theme);
    await mockImg(page);
    await page.goto("/");
    await trigger(page).click();
    const measure = page.getByLabel("Film measure");
    await expect(measure).toBeVisible();
    // Resolve OKLCH tokens through the browser's colour engine, then check WCAG
    // luminance on the actual option pair rather than comparing token strings.
    const ratios = await dialog(page)
      .locator("option")
      .evaluateAll((options) => {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 1;
        const context = canvas.getContext("2d", { willReadFrequently: true })!;
        const luminance = (color: string) => {
          context.clearRect(0, 0, 1, 1);
          context.fillStyle = color;
          context.fillRect(0, 0, 1, 1);
          const rgba = context.getImageData(0, 0, 1, 1).data;
          if (rgba[3] !== 255) throw new Error("Dropdown colour must be opaque");
          const rgb = Array.from(rgba)
            .slice(0, 3)
            .map((v) => {
              const value = v / 255;
              return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
            });
          return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
        };
        return options.map((option) => {
          const style = getComputedStyle(option);
          const a = luminance(style.color);
          const b = luminance(style.backgroundColor);
          return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        });
      });
    expect(ratios.length).toBeGreaterThan(5);
    expect(Math.min(...ratios)).toBeGreaterThanOrEqual(4.5);
    await measure.focus();
    await page.keyboard.press("Home");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(measure).toHaveValue("PRIMER");
    await expect(page.locator('[data-chart="FILM-H"] figcaption p')).toHaveText("Primer · µm");
    await expect(measure).toBeFocused();
    // Enter can open the native OS popup; dismiss it before closing the dialog.
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await expect(trigger(page)).toBeFocused();
  });
}

test("desktop: bounded popup, grouped bars, Film selector, detail, focus trap, Escape and reopen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 1100 });
  const reads = await mockImg(page);
  await page.goto("/");
  await trigger(page).click();
  const d = dialog(page);
  await expect(d).toBeVisible();
  await expect(page.getByLabel("Measured month")).toBeFocused();
  await expect(page.getByLabel("Measured month")).toHaveValue("2099-02"); // newest by default
  expect(reads.at(-1)?.searchParams.get("film_measure")).toBe("CALCULATED_TOTAL");

  // Bounded by the map area, map context left around it, map not interactive.
  const host = (await page.locator(".img-host").boundingBox())!;
  const box = (await d.boundingBox())!;
  expect(box.x).toBeGreaterThan(host.x);
  expect(box.y).toBeGreaterThan(host.y);
  expect(box.x + box.width).toBeLessThan(host.x + host.width);
  expect(box.y + box.height).toBeLessThan(host.y + host.height + 1);
  await expect(page.locator(".img-host__map")).toHaveAttribute("inert", "");

  // One row per domain: Horizontal left, Vertical right; CF above Film.
  const at = async (key: string) => (await page.locator(`[data-chart="${key}"]`).boundingBox())!;
  const [cfH, cfV, filmH] = [await at("CF-H"), await at("CF-V"), await at("FILM-H")];
  expect(cfH.x).toBeLessThan(cfV.x);
  expect(Math.abs(cfH.y - cfV.y)).toBeLessThan(2);
  expect(filmH.y).toBeGreaterThan(cfH.y);
  const cfChart = page.locator('[data-chart="CF-H"]');
  await expect(cfChart.locator(".img-chart__plant")).toHaveText(["FTM", "FVL", "SAP", "AAT"]);
  await expect(cfChart.locator(".img-bar__family")).toHaveText(["P703", "P703", "U704", "X999"]);
  await expect(cfChart.locator(".img-bar__value")).toHaveText(["63.9", "62.6", "63.7", "55.5"]);
  // Uncatalogued models are named once, with where to fix them.
  await expect(d.getByRole("note")).toContainText("Not in the model catalogue");
  await expect(d.getByRole("note")).toContainText("X999");
  await expect(d.getByRole("note").getByRole("link", { name: "Admin" })).toHaveAttribute(
    "href",
    "/admin",
  );
  // A cropped axis says so, in words and with a break mark.
  await expect(cfChart.locator("figcaption")).toContainText("axis starts at");
  await expect(cfChart.locator(".img-chart__break")).toHaveCount(1);
  await expect(cfChart.locator(".img-chart__none")).toHaveCount(2);
  // Shared, zero-based scale for H and V of one measure.
  const ticks = (key: string) =>
    page.locator(`[data-chart="${key}"] .img-chart__axis span`).allTextContents();
  expect(await ticks("CF-H")).toEqual(await ticks("CF-V"));
  // Cropped like the owner's reference, but below the lowest bar (50.29) and above the highest.
  const cf = (await ticks("CF-H")).map(Number);
  expect(cf[0]).toBeGreaterThan(0);
  expect(cf[0]).toBeLessThan(50.29);
  expect(cf.at(-1)).toBeGreaterThan(63.88);
  // A null series is a reason, not a zero bar.
  const excluded = page.locator('[data-series="FVL|V363|FILM|H|CALCULATED_TOTAL"]');
  await expect(excluded).toContainText("Excluded · 7");
  await expect(excluded.locator(".img-bar__fill")).toHaveCount(0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOTS}/OVERVIEW-IMG-desktop.png` });

  // Film measure: one shared choice, fetched from the API.
  await page.getByLabel("Film measure").selectOption("ECOAT");
  await expect(page.locator('[data-chart="FILM-H"] figcaption p')).toHaveText("Ecoat · µm");
  expect(reads.at(-1)?.searchParams.get("film_measure")).toBe("ECOAT");
  await expect(page.locator('[data-chart="FILM-H"] .img-bar__value').first()).toHaveText("21.5");

  // Keyboard bar selection opens a readable detail; Close details returns focus to the bar.
  const bar = page.locator('[data-series="FTM|P703|CF|H|-"]');
  await bar.focus();
  await page.keyboard.press("Enter");
  const detail = page.getByRole("complementary", { name: "FTM P703 detail" });
  await expect(detail).toBeVisible();
  await expect(detail).toContainText("63.87679551522943037974683544 CF");
  await expect(detail).toContainText("12 CF readings");
  await expect(detail).toContainText("Arctic White");
  await expect(detail).toContainText("Wave Scan CF · Horizontal · February 2099");
  await expect(detail.getByRole("heading", { level: 3 })).toBeFocused();
  await page.waitForTimeout(300); // let the 220 ms detail entrance finish before capturing
  await page.screenshot({ path: `${SHOTS}/OVERVIEW-IMG-detail.png` });
  await detail.getByRole("button", { name: "Close details" }).click();
  await expect(bar).toBeFocused();

  // Excluded detail lists reasons and counts.
  await page.locator('[data-series="FVL|V363|FILM|H|ECOAT"]').click();
  const nullDetail = page.getByRole("complementary", { name: "FVL V363 detail" });
  await expect(nullDetail).toContainText("No average");
  await expect(nullDetail).toContainText("Excluded by point settings");
  await expect(nullDetail).toContainText("Missing a layer (not in Total)");
  await nullDetail.getByRole("button", { name: "Close details" }).click();

  // Focus is trapped: Shift+Tab from the first control wraps to the last.
  await page.getByLabel("Measured month").focus();
  await page.keyboard.press("Shift+Tab");
  const inside = await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'));
  expect(inside).toBe(true);

  // Change month, Escape, focus back on the trigger, map interactive again.
  await page.getByLabel("Measured month").selectOption("2099-01");
  await page.keyboard.press("Escape");
  await expect(d).toBeHidden();
  await expect(trigger(page)).toBeFocused();
  await expect(page.locator(".img-host__map")).not.toHaveAttribute("inert", "");

  // Reopen keeps the still-valid month and the Film measure.
  await trigger(page).click();
  await expect(page.getByLabel("Measured month")).toHaveValue("2099-01");
  await expect(page.getByLabel("Film measure")).toHaveValue("ECOAT");
  await dialog(page).getByRole("button", { name: "Close", exact: true }).click();
  await expect(dialog(page)).toBeHidden();
  await expect(trigger(page)).toBeFocused();
});

test("valid month with no readings says so instead of drawing zeros", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mockImg(page, { months: ["2099-03"] });
  await page.goto("/");
  await trigger(page).click();
  await expect(dialog(page).getByRole("status")).toContainText(
    "No eligible readings in March 2099",
  );
  await expect(page.locator(".img-bar")).toHaveCount(0);
  await expect(page.locator(".img-chart")).toHaveCount(0); // one report-level empty state
  await page.screenshot({ path: `${SHOTS}/OVERVIEW-IMG-absent-month.png` });
});

test("no measured months, loading and API error states", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mockImg(page, { months: [], delay: 600 });
  await page.goto("/");
  await trigger(page).click();
  await expect(dialog(page)).toContainText("Loading measured months");
  await expect(dialog(page)).toContainText("No measured months yet");
  await expect(page.getByLabel("Measured month")).toBeDisabled();
  await page.screenshot({ path: `${SHOTS}/OVERVIEW-IMG-no-months.png` });
});

test("API error shows a retry that recovers", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const img = await mockImg(page, { failMonths: true });
  await page.goto("/");
  await trigger(page).click();
  const alert = dialog(page).getByRole("alert");
  await expect(alert).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/OVERVIEW-IMG-error.png` });
  img.heal();
  await alert.getByRole("button", { name: "Retry" }).click();
  await expect(page.locator('[data-chart="CF-H"] .img-bar')).toHaveCount(4);
});

test("narrow width: single column, detail as a sheet, touch-sized targets", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await mockImg(page);
  await page.goto("/");
  await trigger(page).scrollIntoViewIfNeeded();
  await trigger(page).click();
  await expect(dialog(page)).toBeVisible();
  const cfH = (await page.locator('[data-chart="CF-H"]').boundingBox())!;
  const filmH = (await page.locator('[data-chart="FILM-H"]').boundingBox())!;
  expect(filmH.y).toBeGreaterThan(cfH.y);
  const bar = (await page.locator(".img-bar").first().boundingBox())!;
  expect(bar.width).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await dialog(page).screenshot({ path: `${SHOTS}/OVERVIEW-IMG-narrow.png` });
  await page.locator('[data-series="FTM|P703|CF|H|-"]').click();
  await expect(page.getByRole("complementary", { name: "FTM P703 detail" })).toBeVisible();
  await page.waitForTimeout(300);
  await dialog(page).screenshot({ path: `${SHOTS}/OVERVIEW-IMG-narrow-detail.png` });
});

test("reduced motion: no transforms on open, no bar interpolation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mockImg(page);
  await page.goto("/");
  await trigger(page).click();
  await expect(dialog(page)).toBeVisible();
  expect(await dialog(page).evaluate((el) => el.getAnimations().length)).toBe(0);
  const fill = page.locator(".img-bar__fill").first();
  await expect(fill).toHaveAttribute("data-reduced", "true");
  expect(await fill.evaluate((el) => getComputedStyle(el).transitionDuration)).toMatch(
    /^0s|0\.001ms|1e-06s/,
  );
  await page.keyboard.press("Escape");
  await expect(dialog(page)).toBeHidden();
});

test("IMG Color: H and V rankings, highest first, zero-based, with detail and focus return", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 1100 });
  const reads = await mockImg(page);
  await page.goto("/");
  await colorTrigger(page).click();
  const d = page.getByRole("dialog", { name: "IMG Color" });
  await expect(d).toBeVisible();
  await expect.poll(() => reads.at(-1)?.pathname).toBe("/api/v1/img/colors");
  await d.getByRole("button", { name: "Expand report" }).click();
  await expect(page.locator(".img-overlay")).toHaveAttribute("data-expanded", "true");
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
  await d.getByRole("button", { name: "Fit report to map" }).click();
  await expect(page.locator(".img-overlay")).not.toHaveAttribute("data-expanded");
  expect(reads.at(-1)?.searchParams.get("month")).toBe("2099-02");
  const h = page.locator('[data-chart="COLOR-H"]');
  const v = page.locator('[data-chart="COLOR-V"]');
  expect((await v.boundingBox())!.x).toBeGreaterThan((await h.boundingBox())!.x);
  await expect(h.locator(".img-rank__row:not([data-empty]) .img-rank__value")).toHaveText([
    "131.4CF",
    "120.3CF",
    "118.0CF",
    "96.5CF",
  ]);
  await expect(h.locator(".img-rank__name")).toHaveText([
    "Absolute / Shadow BlackAAT · 9 CF readings",
    "Arctic WhiteFTM · 9 CF readings",
    "Arctic WhiteAAT · 9 CF readings",
    "Lucid RedSAP · 9 CF readings",
    "Code OrangeFTM · 0 CF readings",
  ]);
  const heights = await h
    .locator(".img-rank__fill")
    .evaluateAll((els) =>
      els.map((el) => Number(getComputedStyle(el).transform.split(",")[0].replace("matrix(", ""))),
    );
  expect([...heights].sort((a, b) => b - a)).toEqual(heights); // ranked descending
  await expect(h.locator("figcaption p")).toContainText("shared scale 0–150 CF");
  await expect(v.locator("figcaption p")).toContainText("shared scale 0–150 CF");
  const empty = page.locator('[data-series="FTM|Code Orange|CF|H|-"]');
  await expect(empty).toContainText("Excluded · 4");
  await expect(empty.locator(".img-rank__fill")).toHaveCount(0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOTS}/IMG-COLOR-desktop.png` });

  await page.locator('[data-series="FTM|Arctic White|CF|H|-"]').click();
  const detail = page.getByRole("complementary", { name: "Arctic White FTM detail" });
  await expect(detail).toContainText("120.25 CF");
  await expect(detail).toContainText("9 CF readings");
  await expect(detail).toContainText("Average CF · Horizontal · February 2099");
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/IMG-COLOR-detail.png` });
  await page.keyboard.press("Escape");
  await expect(d).toBeHidden();
  await expect(colorTrigger(page)).toBeFocused();
});

test("IMG Color mobile: readable CF rows, search, expand, detail and focus return", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await mockImg(page);
  await page.goto("/");
  await colorTrigger(page).click();
  const d = page.getByRole("dialog", { name: "IMG Color" });
  await expect(d.locator(".img-rank__row")).toHaveCount(7);
  const search = d.getByRole("searchbox", { name: "Find a colour" });
  await search.fill("arctic");
  await expect(d.locator(".img-rank__row")).toHaveCount(3);
  await d.getByRole("button", { name: "Expand report" }).click();
  const row = d.locator('[data-series="FTM|Arctic White|CF|H|-"]');
  await row.click();
  await expect(d.getByRole("complementary")).toContainText("120.25 CF");
  await d.getByRole("button", { name: "Close details" }).click();
  await expect(row).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `${SHOTS}/IMG-COLOR-mobile.png` });
  await d.getByRole("button", { name: "Close", exact: true }).click();
  await expect(d).toBeHidden();
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe("hidden");
});

test("IMG Color: plant filter keeps the scale, legend names plants, light theme reads", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 1100 });
  await mockImg(page);
  await page.goto("/");
  await colorTrigger(page).click();
  const h = page.locator('[data-chart="COLOR-H"]');
  await expect(h.locator(".img-rank__row")).toHaveCount(5);
  await expect(h.locator(".img-rank__legend li")).toHaveText(["AAT", "FTM", "SAP"]);
  const scale = await h.locator("figcaption p").innerText();
  await page
    .getByRole("group", { name: "Show plant" })
    .getByRole("button", { name: "FTM" })
    .click();
  await expect(h.locator(".img-rank__row")).toHaveCount(2);
  await expect(h.locator(".img-rank__row:not([data-empty]) .img-rank__value")).toHaveText([
    "120.3CF",
  ]);
  expect(await h.locator("figcaption p").innerText()).toEqual(scale);
  await expect(h.locator('.img-rank__row[data-plant="FTM"]')).toHaveCount(2);
  await page
    .getByRole("group", { name: "Show plant" })
    .getByRole("button", { name: "All plants" })
    .click();
  await expect(h.locator(".img-rank__row")).toHaveCount(5);
  await page.getByRole("searchbox", { name: "Find a colour" }).fill("arctic");
  await expect(h.locator(".img-rank__row")).toHaveCount(2);
  await page.getByRole("searchbox", { name: "Find a colour" }).fill("no such colour");
  await expect(h.getByRole("status")).toContainText("No matching CF readings");
  await page.getByRole("searchbox", { name: "Find a colour" }).fill("");

  for (const report of ["IMG-COLOR", "OVERVIEW-IMG"]) {
    await page.evaluate(() => {
      document.documentElement.classList.remove("dark");
      document.documentElement.style.colorScheme = "light";
    });
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/${report}-light.png` });
    if (report === "IMG-COLOR") {
      // Reopening during the 160 ms close must not be shut by the old report's close.
      await page.keyboard.press("Escape");
      await trigger(page).click();
      await page.waitForTimeout(400);
      await expect(dialog(page)).toBeVisible();
    }
  }
});
