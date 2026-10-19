import { expect, test, type Page } from "@playwright/test";
import { mockStudio, studioPreview } from "../studio-fixtures";

async function open(page: Page) {
  const calls = await mockStudio(page);
  await page.goto("/plant/AAT");
  await page.getByRole("button", { name: "Comparison", exact: true }).click();
  return calls;
}
async function lane(page: Page, model = "P703") {
  await page.getByLabel("Add model lane").selectOption(model);
  await page.getByRole("button", { name: "Add model", exact: true }).click();
}
async function add(page: Page, name: string) {
  await page.getByRole("button", { name: `Add ${name} to P703`, exact: true }).click();
}
async function group(page: Page, name = "Group A", model = "P703") {
  await page.getByLabel(`Lane actions for ${model}`, { exact: true }).click();
  await page.getByLabel(`New group name for ${model}`).fill(name);
  await page.getByRole("button", { name: `Add group to ${model}`, exact: true }).click();
  await page.getByLabel(`Lane actions for ${model}`, { exact: true }).click();
  await page.getByLabel("Shelf destination").selectOption({ label: name });
}
async function actions(page: Page, name: string) {
  await page.getByLabel(`Actions for ${name}`, { exact: true }).click();
}
async function screenshot(page: Page, name: string) {
  await page.screenshot({
    path: `test-results/screenshots/T85-${name}.png`,
    fullPage: true,
    animations: "disabled",
  });
}

test("T85 absorbs Summary and puts all colours in full-width H then V with a focused pair per colour", async ({
  page,
}) => {
  const calls = await open(page);
  await expect(page.getByRole("button", { name: "Monthly Summary", exact: true })).toHaveCount(0);
  await lane(page);
  await add(page, "Jun 2026");
  await add(page, "Jul 2026");
  const stage = page.getByRole("region", { name: "P703 / CF distributions", exact: true });
  await expect(stage.locator("svg[role=group]")).toHaveCount(2);
  for (const orientation of ["Horizontal", "Vertical"]) {
    const plot = stage.getByRole("region", { name: `${orientation} distributions`, exact: true });
    await expect(plot).toContainText("Arctic White");
    await expect(plot).toContainText("Meteor Grey");
    await expect(plot.getByTestId("studio-month-box")).toHaveCount(4);
  }
  const h = await stage
    .getByRole("region", { name: "Horizontal distributions", exact: true })
    .boundingBox();
  const v = await stage
    .getByRole("region", { name: "Vertical distributions", exact: true })
    .boundingBox();
  expect(v!.y).toBeGreaterThan(h!.y + h!.height);
  expect(Math.abs(v!.width - h!.width)).toBeLessThan(1);
  const profiles = page.getByRole("region", { name: "Monthly profiles", exact: true });
  await expect(profiles.getByRole("region", { name: "Horizontal DU-WE", exact: true })).toHaveCount(
    2,
  );
  await expect(profiles.getByRole("region", { name: "Vertical DU-WE", exact: true })).toHaveCount(
    2,
  );
  await expect(page.getByLabel("Profile focus")).toHaveValue(
    (await page.getByLabel("Profile focus").locator("option").first().getAttribute("value")) ?? "",
  );
  const count = calls.previews.length;
  await page.getByRole("button", { name: "Meteor Grey", exact: true }).click();
  await expect(profiles.getByRole("region", { name: "Horizontal DU-WE", exact: true })).toHaveCount(
    1,
  );
  expect(calls.previews.length).toBe(count);
  await page.getByRole("button", { name: "Restore all colours", exact: true }).click();
  await expect(profiles.getByRole("region", { name: "Horizontal DU-WE", exact: true })).toHaveCount(
    2,
  );
});

test("T85 three-month group keeps real members, API diamond and contribution details; model lanes reject cross-model moves", async ({
  page,
}) => {
  const calls = await open(page);
  await lane(page);
  await group(page);
  for (const month of ["Jun 2026", "Jul 2026", "Aug 2026"]) await add(page, month);
  const stage = page.getByRole("region", { name: "P703 / CF distributions", exact: true });
  await expect(stage.getByTestId("studio-month-box")).toHaveCount(12);
  await expect(stage.getByTestId("studio-group-marker")).toHaveCount(4);
  await expect(stage.getByTestId("monthly-group-bracket")).toHaveCount(4);
  const marker = stage
    .getByRole("button", { name: /Group A \/ P703 \/ Arctic White Group mean 50/ })
    .first();
  await marker.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Equal-month mean: 50");
  await expect(dialog).toContainText("Not measured");
  await expect(dialog).toContainText("2026-08");
  await expect(dialog).not.toContainText("q1");
  await expect(dialog).not.toContainText("Status");
  await page.keyboard.press("Escape");
  await expect(marker).toBeFocused();
  const box = stage
    .getByRole("button", { name: /Group A \/ 2026-07 \/ P703 \/ Arctic White Mean 60/ })
    .first();
  await box.click();
  await expect(dialog).toContainText("q1");
  await expect(dialog).toContainText("62.4000");
  await expect(dialog).toContainText("35.0000");
  await page.keyboard.press("Escape");
  await lane(page, "U704");
  await group(page, "Other", "U704");
  await page.getByRole("button", { name: "Add Jun 2026 to U704", exact: true }).click();
  await page.getByRole("button", { name: "View P703 charts", exact: true }).click();
  await actions(page, "Group A");
  await page.getByLabel("Move destination for Group A").selectOption({ label: "U704 / Other" });
  await page.getByRole("button", { name: "Move 2026-06 from Group A", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("cannot move across model lanes");
  await actions(page, "Group A");
  await expect(
    page
      .getByRole("region", { name: "P703 model lane", exact: true })
      .locator(".studio-connected-months span"),
  ).toHaveCount(3);
  expect(
    calls.previews.every(
      (body) => Object.keys(body).sort().join() === "domain,metric,model,months",
    ),
  ).toBe(true);
  await screenshot(page, "group-desktop");
  await stage.screenshot({
    path: "test-results/screenshots/T85-all-colour-boxes-desktop.png",
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await screenshot(page, "group-mobile");
  await stage.screenshot({
    path: "test-results/screenshots/T85-all-colour-boxes-mobile.png",
    animations: "disabled",
  });
  const scrolls = stage.locator(".studio-chart-scroll");
  await scrolls.first().focus();
  await page.keyboard.press("ArrowRight");
  await expect
    .poll(() => scrolls.first().evaluate((element) => element.scrollLeft))
    .toBeGreaterThan(0);
  for (const scroll of await scrolls.all())
    await scroll.evaluate((element) => {
      element.scrollLeft = element.scrollWidth;
    });
  await stage.screenshot({
    path: "test-results/screenshots/T85-all-colour-boxes-mobile-scrolled.png",
    animations: "disabled",
  });
});

test("T85 one focused item per colour, smooth measured dots, missing segments, searchable location focus and exact monthly values", async ({
  page,
}) => {
  await open(page);
  await lane(page);
  await group(page);
  await add(page, "Jun 2026");
  await add(page, "Jul 2026");
  await page.getByLabel("Shelf destination").selectOption("");
  await add(page, "Jun 2026");
  const profiles = page.getByRole("region", { name: "Monthly profiles", exact: true });
  const white = profiles.getByRole("region", { name: "Arctic White focused profile", exact: true });
  await expect(profiles.getByRole("region", { name: "Horizontal DU-WE", exact: true })).toHaveCount(
    2,
  );
  await expect(white.getByTestId("profile-measured-dot")).toHaveCount(10);
  const curve = white.locator("path.recharts-line-curve").first();
  await expect(curve).toHaveAttribute("d", /C/);
  const path = await curve.getAttribute("d");
  expect(path!.split("M")).toHaveLength(3); // WC is null: two disconnected pieces.
  await white.getByRole("button", { name: /1\. HOOD/ }).click();
  await expect(white.getByRole("region", { name: "Profile exact values" })).toContainText(
    "Equal-month mean: 50",
  );
  await white.getByRole("button", { name: "WC Not measured", exact: true }).click();
  await expect(white.getByRole("region", { name: "Profile exact values" })).toContainText(
    "Missing months: 2026-06, 2026-07",
  );
  await white.getByLabel("Search location or source").fill("DOOR");
  await expect(white.getByRole("button", { name: /1\. HOOD/ })).toHaveCount(0);
  await white.getByRole("button", { name: /2\. DOOR/ }).click();
  await expect(white.locator(".recharts-line-curve").first()).toHaveAttribute(
    "stroke-opacity",
    "0.18",
  );
  await expect(profiles).toContainText("4 historical unaligned source rows");
  await white.getByText("Unproved orientation locations", { exact: true }).click();
  await white.getByRole("button", { name: "3. ROOF", exact: true }).click();
  await expect(white.getByRole("region", { name: "Profile exact values" })).toContainText(
    "Unproved orientation",
  );
  await white.getByLabel("Search location or source").fill("");
  await white.getByRole("button", { name: /1\. HOOD/ }).click();
  await white.screenshot({
    path: "test-results/screenshots/T85-colour-profile-desktop.png",
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await white.screenshot({
    path: "test-results/screenshots/T85-colour-profile-mobile.png",
    animations: "disabled",
  });
  await page.getByLabel("Profile focus").selectOption({ label: "Jun 2026" });
  await white.getByRole("button", { name: /1\. HOOD/ }).click();
  await expect(white.getByRole("region", { name: "Profile exact values" })).toContainText(
    "Month 2026-06 / Mean: 40 / n 1",
  );
  await expect(white.getByRole("region", { name: "Profile exact values" })).not.toContainText(
    "Equal-month",
  );
});

test("T85 Film layer boxes use returned lines and status; unavailable means are not zero and Film has no profile", async ({
  page,
}) => {
  const calls = await open(page);
  await page.getByLabel("Monthly domain", { exact: true }).selectOption("FILMTHICKNESS");
  await page.getByLabel("Monthly metric", { exact: true }).selectOption("clear");
  await lane(page);
  await group(page);
  for (const month of ["Jun 2026", "Jul 2026", "Aug 2026"]) await add(page, month);
  await expect(page.getByRole("region", { name: "Monthly profiles" })).toHaveCount(0);
  const stage = page.getByRole("region", { name: "P703 / CLEAR distributions", exact: true });
  await expect(stage.locator("svg[role=group]")).toHaveCount(2);
  const box = stage
    .getByRole("button", { name: /Group A \/ 2026-06 \/ P703 \/ Arctic White Mean 40/ })
    .first();
  await expect(box).toHaveAttribute("data-status", "WARNING");
  await box.click();
  const dialog = page.getByRole("dialog");
  for (const value of [
    "No point below",
    "30.0000",
    "Minimum requirement",
    "46.0000",
    "Standard scope",
  ])
    await expect(dialog).toContainText(value);
  await page.keyboard.press("Escape");
  await stage
    .getByRole("button", { name: /Group A \/ P703 \/ Meteor Grey Group mean Not measured/ })
    .first()
    .click();
  await expect(dialog).toContainText("Equal-month mean: Not measured");
  await page.keyboard.press("Escape");
  expect(calls.previews.at(-1)?.metric).toBe("clear");
  await screenshot(page, "film-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await screenshot(page, "film-mobile");
});

test.describe("T85 touch and keyboard board", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, reducedMotion: "reduce" });
  test("compact actions reorder, move out/in, rename and dissolve connected groups without losing members", async ({
    page,
  }) => {
    await open(page);
    await lane(page);
    await group(page, "Touch");
    await add(page, "Jun 2026");
    await add(page, "Jul 2026");
    await expect(
      page.getByRole("button", { name: "Dissolve Touch", exact: true }),
    ).not.toBeVisible();
    await page.getByLabel("Actions for Touch", { exact: true }).tap();
    await page.getByRole("button", { name: "Earlier 2026-07 in Touch", exact: true }).focus();
    await page.keyboard.press("Enter");
    const laneRegion = page.getByRole("region", { name: "P703 model lane", exact: true });
    await expect(laneRegion.locator(".studio-connected-months span").first()).toHaveText(
      "Jul 2026",
    );
    await page.getByRole("button", { name: "Move 2026-06 from Touch", exact: true }).tap();
    await expect(page.getByRole("status")).toContainText("Moved 2026-06");
    await actions(page, "Touch");
    await actions(page, "2026-06");
    await page.getByLabel("Move destination for 2026-06").selectOption({ label: "P703 / Touch" });
    await page.getByRole("button", { name: "Move 2026-06 from 2026-06", exact: true }).tap();
    await actions(page, "Touch");
    await page.getByLabel("Rename Touch", { exact: true }).fill("Renamed");
    await page.getByRole("button", { name: "Dissolve Renamed", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(laneRegion.locator("article")).toHaveCount(2);
    await expect(laneRegion.locator("article").first()).toContainText("Jul 2026");
    await add(page, "May 2026"); // Dissolving also releases the shelf's former group destination.
    await expect(laneRegion.locator("article")).toHaveCount(3);
    await actions(page, "2026-07");
    await page.getByRole("button", { name: "Remove 2026-07", exact: true }).tap();
    await expect(laneRegion.locator("article")).toHaveCount(2);
    await page.getByLabel("Monthly domain", { exact: true }).selectOption("FILMTHICKNESS");
    await expect(page.getByLabel("Monthly metric", { exact: true })).toHaveValue("ecoat");
    await page.getByLabel("Monthly domain", { exact: true }).selectOption("WAVESCAN");
    await expect(laneRegion.locator("article")).toHaveCount(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
});

test("T85 six-point monotone curve intersects each exact measured coordinate without local overshoot; catalogue location search focuses dense lines", async ({
  page,
}) => {
  await open(page);
  await page.route("**/comparison/monthly-preview", (route) => {
    const data = studioPreview(route.request().postDataJSON());
    // Supplied fixture response: a peak and shoulder, six exact values and 24 H locations.
    const values = ["0.00000000000000000", "12.2500", "60.2000", "28.1000", "29.3000", "25.4500"];
    const hood = data.profiles[0];
    hood.metrics.forEach((metric, index) => {
      metric.mean = values[index];
      metric.monthly = [{ month: "2026-06", mean: values[index], n: 1 }];
      metric.contributing_months = ["2026-06"];
      metric.missing_months = [];
      metric.contributing_month_count = 1;
    });
    data.profiles.splice(
      3,
      0,
      ...Array.from({ length: 23 }, (_, i) => ({
        ...hood,
        point_no: i + 4,
        code: `HOOD-${String(i + 1).padStart(2, "0")}`,
      })),
    );
    return route.fulfill({ json: data });
  });
  await lane(page);
  await add(page, "Jun 2026");
  const white = page.getByRole("region", { name: "Arctic White focused profile", exact: true });
  const horizontal = white.getByRole("region", { name: "Horizontal DU-WE", exact: true });
  await expect(horizontal.locator(".recharts-line-curve")).toHaveCount(24);
  const curve = horizontal.locator(".recharts-line-curve").first();
  await expect(curve).toHaveAttribute("d", /C/);
  const result = await horizontal.evaluate((element) => {
    const path = element.querySelector<SVGPathElement>(".recharts-line-curve")!;
    const dots = Array.from(
      element.querySelectorAll<SVGCircleElement>('[data-line="p1-HOOD"]'),
    ).map((dot) => ({ x: Number(dot.getAttribute("cx")), y: Number(dot.getAttribute("cy")) }));
    const length = path.getTotalLength();
    const samples = Array.from({ length: 3001 }, (_, i) =>
      path.getPointAtLength((length * i) / 3000),
    );
    const distances = dots.map((dot) =>
      Math.min(...samples.map((point) => Math.hypot(point.x - dot.x, point.y - dot.y))),
    );
    const overshoots = samples.filter((point) => {
      const right = dots.findIndex((dot) => dot.x >= point.x);
      if (right <= 0) return false;
      const lo = Math.min(dots[right - 1].y, dots[right].y) - 0.1;
      const hi = Math.max(dots[right - 1].y, dots[right].y) + 0.1;
      return point.y < lo || point.y > hi;
    }).length;
    return { count: dots.length, distances, overshoots };
  });
  expect(result.count).toBe(6);
  expect(Math.max(...result.distances)).toBeLessThan(0.5);
  expect(result.overshoots).toBe(0);
  await white.getByLabel("Search location or source").fill("HOOD-23");
  await expect(horizontal.getByRole("button")).toHaveCount(1);
  await horizontal.getByRole("button", { name: /HOOD-23/ }).click();
  await expect(white.getByRole("region", { name: "Profile exact values" })).toContainText(
    "0.00000000000000000",
  );
  await expect(curve).toHaveAttribute("stroke-opacity", "0.18");
  await white.getByRole("button", { name: "Show all locations", exact: true }).click();
  await expect(curve).toHaveAttribute("stroke-opacity", "1");
  await horizontal.getByRole("button", { name: /HOOD-23/ }).click();
  await white.screenshot({
    path: "test-results/screenshots/T85-dense-profile-desktop.png",
    animations: "disabled",
  });
});

test("T85 loading, failed query and retry preserve board; absent colour/orientation and exact zero stay distinct", async ({
  page,
}) => {
  await open(page);
  let fail = true;
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/comparison/monthly-preview", async (route) => {
    if (fail) {
      await gate;
      return route.fulfill({
        status: 503,
        json: {
          message: "Preview unavailable",
          correlationId: "T85-retry",
          statusCode: 503,
          error: "Unavailable",
        },
      });
    }
    const data = studioPreview(route.request().postDataJSON());
    data.group_means.reverse(); // Returned domain colour order differs from name order.
    data.month_boxes[0].wavescan_boxes = data.month_boxes[0].wavescan_boxes.filter(
      (box) => box.orient === "Horizontal" && box.color_name === "Meteor Grey",
    );
    data.month_boxes[0].wavescan_boxes[0].mean = "0.00000000000000000";
    data.profiles[3].metrics[0].monthly[0].mean = "0.00000000000000000";
    return route.fulfill({ json: data });
  });
  await lane(page);
  await add(page, "Jun 2026");
  await expect(page.getByText("Loading P703 / 2026-06...", { exact: true })).toBeVisible();
  release();
  await expect(page.getByRole("alert").first()).toContainText("T85-retry");
  fail = false;
  await page.getByRole("button", { name: "Retry", exact: true }).first().click();
  const h = page.getByRole("region", { name: "Horizontal distributions", exact: true });
  await expect(h.getByTestId("comparison-mean")).toHaveText("0.00000000000000000");
  expect(
    await h
      .locator("[data-colour]")
      .evaluateAll((elements) => elements.map((element) => element.getAttribute("data-colour"))),
  ).toEqual(["Meteor Grey", "Arctic White"]);
  await expect(h.getByRole("button", { name: /Arctic White Mean Not measured/ })).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Vertical distributions", exact: true })
      .getByTestId("comparison-mean"),
  ).toHaveCount(0);
  const grey = page.getByRole("region", { name: "Meteor Grey focused profile", exact: true });
  await grey.getByRole("button", { name: /1\. HOOD/ }).click();
  await expect(
    grey.getByRole("button", { name: "DU 0.00000000000000000", exact: true }),
  ).toBeVisible();
});
