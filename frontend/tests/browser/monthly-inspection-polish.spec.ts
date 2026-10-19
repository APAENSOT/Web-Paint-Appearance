import { expect, test } from "@playwright/test";

test("Model Detail keeps saved anchors intact while orbiting", async ({ page }, info) => {
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/point-profiles/") && request.method() !== "GET")
      writes.push(request.url());
  });
  await page.goto("/plant/FTM?modelView=inspection");
  const canvas = page.getByTestId("model-studio-stage").locator("canvas");
  await expect(canvas).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".studio-point-marker").first()).toBeAttached({ timeout: 30000 });
  const markers = await page.locator(".studio-point-marker").count();
  const bounds = await canvas.boundingBox();
  await page.mouse.move(bounds!.x + bounds!.width * 0.35, bounds!.y + bounds!.height * 0.6);
  await page.mouse.down();
  await page.mouse.move(bounds!.x + bounds!.width * 0.65, bounds!.y + bounds!.height * 0.6, {
    steps: 30,
  });
  await page.mouse.up();
  await expect(page.locator(".studio-point-marker")).toHaveCount(markers);
  expect(writes).toEqual([]);
  await page.screenshot({ path: info.outputPath("model-detail-orbit.png") });
});

for (const domain of ["wavescan", "film"] as const) {
  for (const width of [390, 1600]) {
    test(`${domain} point averages and graph values at ${width}px`, async ({
      page,
      request,
    }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      const profileResponse = await request.get(
        `http://127.0.0.1:8012/api/v1/plants/FTM/point-profiles/P703%20DBL%20RANGER/${domain}`,
      );
      expect(profileResponse.ok()).toBeTruthy();
      const profile = await profileResponse.json();
      const first = profile.points.find((p: { anchor: unknown }) => p.anchor);
      expect(first).toBeTruthy();
      const items = profile.points.map((p: { point_key: string }, i: number) => ({
        point_key: p.point_key,
        mean: i === 2 ? null : "32.361333333333333333",
        reading_count: i === 2 ? 0 : 3,
        status:
          i === 2 ? null : ["PASS", "WARNING", "FAIL", "OVER"][i % (domain === "film" ? 4 : 3)],
      }));
      await page.route("**/monthly-detail/point-statuses?**", (route) =>
        route.fulfill({
          json: {
            plant_code: "FTM",
            domain,
            month: "2026-09",
            model_code: profile.model_code,
            color_name: "Arctic White",
            metric: domain === "film" ? "clear" : "cf",
            unit: domain === "film" ? "µm" : "index",
            items,
            active_data_source: domain === "film" ? "filmthickness_active" : "v_wavescan_active",
          },
        }),
      );
      await page.route("**/monthly-detail/points?**", (route) => {
        const url = new URL(route.request().url());
        const metric = url.searchParams.get("metric");
        return route.fulfill({
          json: {
            plant_code: "FTM",
            domain,
            month: "2026-09",
            model_code: profile.model_code,
            color_name: "Arctic White",
            metric,
            unit: domain === "film" ? "µm" : "index",
            point_key: url.searchParams.get("point_key"),
            orientation: "H",
            standard_scope: "PLANT",
            reference_lines: [],
            sample_count: 3,
            checked_sample_count: 3,
            reading_count: 3,
            status: "PASS",
            box: {
              box_min: "31.5",
              box_max: "33.5",
              q1: "31.75",
              q3: "32.75",
              median: "32",
              mean: "32.333333333333333333",
              whisker_lo: "31.5",
              whisker_hi: "33.5",
              outliers: [],
            },
            samples: ["31.5", "32", "33.5"].map((value, i) => ({
              vehicle_id: `fixture-${i}`,
              serial_no: `Fixture ${i + 1}`,
              measured_date: `2026-09-${10 + i}`,
              readings: [{ value, load_id: 1, source_row: i + 1 }],
            })),
            unaligned_reading_count: 0,
            active_data_source: domain === "film" ? "filmthickness_active" : "v_wavescan_active",
          },
        });
      });
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(`/tests/fixtures/monthly-inspection.html?domain=${domain}`);
      if (width === 1600)
        await page.evaluate(() => document.documentElement.classList.remove("dark"));
      await expect(page.locator(".studio-point-marker").first()).toBeAttached({ timeout: 30000 });
      await expect(page.locator(".studio-point-marker b")).toHaveCount(0);
      await expect(
        page.locator('.monthly-point-buttons button[data-status="PASS"]').first(),
      ).toContainText("Avg 32.36");
      const dot = page.locator('.studio-point-marker[style*="visibility: visible"]').first();
      await expect(dot).toBeVisible();
      await expect(dot).toHaveAttribute("data-status", /PASS|WARNING|FAIL|OVER|NO_DATA/);
      await dot.click();
      await expect(page.getByRole("heading", { name: "Monthly distribution" })).toBeVisible();
      await expect(page.locator(".monthly-mean-marker text")).toHaveText("Avg 32.33");
      await expect(page.locator(".monthly-reading-value")).toHaveText(["31.5", "32", "33.5"]);
      await page.getByRole("button", { name: /Sample 1 reading 1:/ }).click();
      await expect(page.locator(".monthly-selected-reading")).toContainText("31.5");
      await page.getByRole("button", { name: /Sample 2 reading 1:/ }).focus();
      await page.keyboard.press("Enter");
      await expect(page.locator(".monthly-selected-reading")).toContainText("Fixture 2");
      const canvas = page.locator(".studio-canvas canvas");
      await canvas.scrollIntoViewIfNeeded();
      const bounds = await canvas.boundingBox();
      await page.mouse.move(bounds!.x + bounds!.width * 0.4, bounds!.y + bounds!.height * 0.6);
      await page.mouse.down();
      await page.mouse.move(bounds!.x + bounds!.width * 0.7, bounds!.y + bounds!.height * 0.6, {
        steps: 20,
      });
      await page.mouse.up();
      await expect(page.locator(".studio-point-marker[aria-pressed=true]")).toHaveCount(1);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      ).toBeTruthy();
      expect(errors).toEqual([]);
      await page.screenshot({ path: info.outputPath(`${domain}-${width}.png`), fullPage: true });
    });
  }
}
