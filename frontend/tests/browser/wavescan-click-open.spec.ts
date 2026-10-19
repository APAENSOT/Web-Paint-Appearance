import { expect, test, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { mockHistory } from "../history-fixtures";
import { wavescanClickFixture } from "../wavescan-click-fixtures";

async function mock(page: Page, role = "viewer") {
  await mockHistory(page, role);
  let current = wavescanClickFixture;
  const reads: URL[] = [];
  await page.route("**/api/v1/**", (route) =>
    route.request().method() === "GET" ? route.fallback() : route.abort(),
  );
  await page.route("**/wavescan/overview**", (route) => {
    const url = new URL(route.request().url());
    reads.push(url);
    const models = url.searchParams.getAll("model"),
      colors = url.searchParams.getAll("color");
    return route.fulfill({
      json: {
        ...current,
        plant_code: url.pathname.split("/")[4],
        month: url.searchParams.get("month") ?? current.month,
        models,
        colors,
        boxes: current.boxes.filter(
          (b) =>
            (!models.length || models.includes(b.model_code)) &&
            (!colors.length || colors.includes(b.color_name)),
        ),
      },
    });
  });
  return {
    reads,
    replace: (data: typeof current) => {
      current = data;
    },
  };
}
const card = (page: Page, model = "P703 DBL RAPTOR", orient = "Horizontal") =>
  page.getByRole("region", { name: `${model} ${orient}`, exact: true });

for (const width of [390, 768, 1440])
  for (const theme of ["light", "dark"])
    test(`T72 ${width} ${theme} click-only independent CF inspection`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.emulateMedia({ reducedMotion: theme === "light" ? "reduce" : "no-preference" });
      const { reads } = await mock(page);
      await page.goto("/plant/FTM");
      await expect(page.locator("[data-wavescan-box]")).toHaveCount(4);
      await page.evaluate(
        (t) => document.documentElement.classList.toggle("dark", t === "dark"),
        theme,
      );
      const h = card(page),
        v = card(page, undefined, "Vertical"),
        ranger = card(page, "P703 DBL RANGER");
      const box = h.locator("[data-wavescan-box]").first();
      const before = reads.length;
      await box.hover();
      await box.focus();
      await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
      await expect(box).toHaveAccessibleName("Absolute / Shadow Black; Horizontal box summary");
      await box.press("Enter");
      const detail = h.getByRole("region", { name: "WaveScan box detail" });
      await expect(detail).toContainText("Fail");
      await expect(detail.locator(".wavescan-summary-primary")).toHaveText(
        "Average62.0 CFObserved minimum12.1 CFObserved maximum91.0 CF",
      );
      await detail.locator("summary").filter({ hasText: "Detailed measurements" }).click();
      await expect(detail).toContainText("61.99999999999999999");
      await expect(detail).toContainText("90.98765432109876543");
      await expect(detail).toContainText("Statistical outliers70");
      await v.locator("[data-wavescan-box]").first().focus();
      await v.locator("[data-wavescan-box]").first().press(" ");
      await ranger.locator("[data-wavescan-box]").first().click();
      await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(3);
      await h.locator("[data-wavescan-label]").nth(1).click();
      await expect(detail).toContainText("No standard");
      await expect(detail.locator(".wavescan-published-standard")).toContainText(
        "StandardNot setMinimumNot set",
      );
      await detail.locator("summary").filter({ hasText: "Detailed measurements" }).click();
      await expect(detail).toContainText("Statistical outliersNone");
      const label = h.locator("[data-wavescan-label]").nth(1);
      await detail.getByRole("button", { name: "Close detail" }).click();
      await expect(label).toBeFocused();
      await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(2);
      await v.locator("[data-wavescan-box]").first().press("Escape");
      await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(1);
      await box.click();
      await expect(box).toHaveAttribute("aria-expanded", "true");
      await expect(h.locator("[data-wavescan-box][tabindex='0']")).toHaveCount(2);
      await expect(h.locator("[role='img']")).toHaveCount(0);
      expect(await box.evaluate((el) => el.getBoundingClientRect().width)).toBeGreaterThanOrEqual(
        44,
      );
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      expect(reads.length).toBe(before);
      const text = await page.locator(".wavescan-overview").textContent();
      expect(text).not.toMatch(/µm|Outside-limit readings|No point below|\bOver\b/);
      const hits = await h.locator(".wavescan-box-hit").evaluateAll((nodes) =>
        nodes.map((node) => {
          const r = node.getBoundingClientRect();
          return { left: r.left, right: r.right };
        }),
      );
      expect(hits[1].left - hits[0].right).toBeGreaterThanOrEqual(8);
      await page.locator(".wavescan-chart-scroll").evaluateAll((nodes) =>
        nodes.forEach((node) => {
          node.scrollLeft = 0;
        }),
      );
      await page.screenshot({
        path: `test-results/evidence/T72/fixture-${width}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
    });

test("T72 current-response refetch, removed grain, no entrance replay and connected focus return", async ({
  page,
}) => {
  const fixture = await mock(page);
  await page.goto("/plant/FTM");
  const h = card(page),
    target = h.locator("[data-wavescan-box]").first();
  await target.click();
  const detail = h.getByRole("region", { name: "WaveScan box detail" });
  await detail.evaluate(async (el) => {
    await Promise.all(el.getAnimations().map((a) => a.finished));
  });
  const node = await detail.elementHandle();
  await detail.locator("summary").filter({ hasText: "Detailed measurements" }).click();
  await target.hover();
  expect(await detail.evaluate((el) => el.getAnimations().length)).toBe(0);
  fixture.replace({
    ...wavescanClickFixture,
    boxes: wavescanClickFixture.boxes.map((b, i) =>
      i === 0 ? { ...b, mean: "42.123456789", status: "PASS" } : b,
    ),
  });
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect(detail.locator(".wavescan-summary-primary")).toContainText("Average42.1 CF");
  await expect(detail).toContainText("Pass");
  expect(await detail.evaluate((el, old) => el === old, node)).toBe(true);
  expect(await detail.evaluate((el) => el.getAnimations().length)).toBe(0);
  await detail.getByRole("button", { name: "Close detail" }).click();
  await expect(target).toBeFocused();
  await target.click();
  fixture.replace({ ...wavescanClickFixture, boxes: wavescanClickFixture.boxes.slice(1) });
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect(page.locator("[data-wavescan-box]")).toHaveCount(3);
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  fixture.replace(wavescanClickFixture);
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect(page.locator("[data-wavescan-box]")).toHaveCount(4);
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
});

test("T72 pending colour scope, model/month/plant changes and leaving WaveScan remove old details", async ({
  page,
}) => {
  await mock(page);
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let hold = true;
  await page.route("**/wavescan/overview**", async (route) => {
    if (hold && new URL(route.request().url()).searchParams.has("color")) await gate;
    return route.fallback();
  });
  await page.goto("/plant/FTM");
  await card(page).locator("[data-wavescan-box]").first().click();
  await card(page, undefined, "Vertical").locator("[data-wavescan-box]").first().click();
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(2);
  await page.getByRole("button", { name: "Color", exact: true }).click();
  await page.getByRole("button", { name: "Arctic White", exact: true }).click();
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  hold = false;
  release();
  await expect(page.locator("[data-wavescan-box]")).toHaveCount(3);
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  await card(page).locator("[data-wavescan-box]").first().click();
  await page.getByRole("button", { name: "P703 DBL RANGER", exact: true }).click();
  await expect(card(page, "P703 DBL RANGER")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  await card(page).locator("[data-wavescan-box]").first().click();
  await page.getByRole("button", { name: "2026-06", exact: true }).click();
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  await card(page).locator("[data-wavescan-box]").first().click();
  await page.goto("/plant/AAT");
  await expect(page.locator("[data-wavescan-box]")).toHaveCount(4);
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  await card(page).locator("[data-wavescan-box]").first().click();
  await page.getByRole("button", { name: "Monthly Detail", exact: true }).click();
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  await page.getByRole("button", { name: "Monthly Overview", exact: true }).click();
  await expect(page.locator("[data-wavescan-box]")).toHaveCount(4);
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
});

test("T72 loading/error/retry and empty response cannot retain inspection", async ({ page }) => {
  const fixture = await mock(page);
  await page.goto("/plant/FTM");
  await card(page).locator("[data-wavescan-box]").first().click();
  let failed = true;
  await page.route("**/wavescan/overview**", (route) =>
    failed
      ? route.fulfill({
          status: 503,
          json: {
            statusCode: 503,
            error: "Unavailable",
            message: "T72 read refused",
            correlationId: "t72-read",
          },
        })
      : route.fallback(),
  );
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect(page.getByRole("alert")).toContainText("T72 read refused");
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.locator("[data-wavescan-box]")).toHaveCount(4);
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  await card(page).locator("[data-wavescan-box]").first().click();
  fixture.replace({ ...wavescanClickFixture, boxes: [] });
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect(page.getByText("There are no active readings for this month.")).toBeVisible();
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
});

for (const role of ["viewer", "engineer", "admin"])
  test(`T72 ${role} inspection remains local and role-neutral`, async ({ page }) => {
    const { reads } = await mock(page, role);
    await page.goto("/plant/FTM");
    await expect(page.locator("[data-wavescan-box]")).toHaveCount(4);
    const before = reads.length;
    const target = card(page).locator("[data-wavescan-box]").first();
    const rect = target.locator(".animate-grow-y");
    await rect.evaluate((el) => el.setAttribute("data-test-retained", "true"));
    const geometry = await target.evaluate((el) =>
      [...el.querySelectorAll("line,circle,rect:not(.wavescan-box-hit),text")].map(
        (node) => node.outerHTML,
      ),
    );
    await target.click();
    await expect(card(page).getByRole("region", { name: "WaveScan box detail" })).toBeVisible();
    expect(
      await target.evaluate((el) =>
        [...el.querySelectorAll("line,circle,rect:not(.wavescan-box-hit),text")].map(
          (node) => node.outerHTML,
        ),
      ),
    ).toEqual(geometry);
    await expect(rect).toHaveAttribute("data-test-retained", "true");
    await target.press("Escape");
    expect(reads.length).toBe(before);
  });

test("T72 touch and normal/reduced-motion entrances", async ({ browser }) => {
  const context = await browser.newContext({
    hasTouch: true,
    viewport: { width: 390, height: 1000 },
  });
  const page = await context.newPage();
  await mock(page);
  await page.goto("http://localhost:5173/plant/FTM");
  await card(page).locator("[data-wavescan-box]").first().tap();
  const detail = card(page).getByRole("region", { name: "WaveScan box detail" });
  await expect(detail).toBeVisible();
  await detail.evaluate(async (el) => {
    await Promise.all(el.getAnimations().map((a) => a.finished));
  });
  await detail.getByRole("button", { name: "Close detail" }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await card(page).locator("[data-wavescan-box]").first().tap();
  expect(await detail.evaluate((el) => el.getAnimations().length)).toBe(0);
  await context.close();
});

test("T72 live GET-only WaveScan CF summaries match actual responses", async ({ page }) => {
  const forbidden: string[] = [];
  await page.route("**/api/v1/**", (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    if (
      req.method() !== "GET" ||
      /filmthickness|standards|history|vehicles|points|batches/.test(path)
    ) {
      forbidden.push(req.url());
      return route.abort();
    }
    return route.continue();
  });
  for (const plant of ["FTM", "AAT", "FVL", "SAP"]) {
    const first = await page.request.get(
      `http://localhost:8012/api/v1/plants/${plant}/wavescan/overview?month=2026-10`,
    );
    expect(first.status()).toBe(200);
    let data = await first.json();
    if (data.available_months.length) {
      const response = await page.request.get(
        `http://localhost:8012/api/v1/plants/${plant}/wavescan/overview?month=${data.available_months[0]}`,
      );
      expect(response.status()).toBe(200);
      data = await response.json();
    }
    writeFileSync(
      `test-results/evidence/T72/live-${plant}-payload.json`,
      JSON.stringify(data, null, 2),
    );
    await page.goto(`/plant/${plant}`);
    await expect(page.locator("[data-wavescan-box]")).toHaveCount(data.boxes.length);
    for (const model of [
      ...new Set<string>(data.boxes.map((b: { model_code: string }) => b.model_code)),
    ]) {
      for (const orient of ["Horizontal", "Vertical"]) {
        const b = data.boxes.find(
          (box: { model_code: string; orient: string }) =>
            box.model_code === model && box.orient === orient,
        );
        if (!b) continue;
        const panel = card(page, model, orient);
        await panel.locator("[data-wavescan-box]").first().click();
        const detail = panel.getByRole("region", { name: "WaveScan box detail" });
        await expect(detail.locator(".wavescan-summary-primary")).toContainText(
          `Average${Number(b.mean).toFixed(1)} CF`,
        );
        await expect(detail.locator(".wavescan-summary-primary")).toContainText(
          `Observed minimum${Number(b.box_min).toFixed(1)} CF`,
        );
        await expect(detail.locator(".wavescan-summary-primary")).toContainText(
          `Observed maximum${Number(b.box_max).toFixed(1)} CF`,
        );
        await expect(detail.locator("[data-wavescan-status]")).toHaveText(
          b.status === "PASS"
            ? "Pass"
            : b.status === "WARNING"
              ? "Acceptable" // T112: owner 2026-10-11 — WARNING reads Acceptable
              : b.status === "FAIL"
                ? "Fail"
                : "No standard",
        );
        await detail.locator("summary").filter({ hasText: "Detailed measurements" }).click();
        for (const field of [
          "mean",
          "box_min",
          "box_max",
          "q1",
          "median",
          "q3",
          "whisker_lo",
          "whisker_hi",
        ])
          await expect(detail).toContainText(b[field]);
        await expect(detail).toContainText(b.ford ?? "Not set");
        await expect(detail).toContainText(b.minimum ?? "Not set");
      }
    }
    for (const theme of ["light", "dark"]) {
      await page.evaluate(
        (t) => document.documentElement.classList.toggle("dark", t === "dark"),
        theme,
      );
      await page.screenshot({
        path: `test-results/evidence/T72/live-${plant}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
    }
  }
  expect(forbidden).toEqual([]);
});

test("T72 obsolete month cancellation and repeated multi-colour/model filters remain intact", async ({
  page,
}) => {
  const fixture = await mock(page);
  fixture.replace({
    ...wavescanClickFixture,
    color_options: [
      ...wavescanClickFixture.color_options,
      { color_name: "Seismic Tan", family_code: "LS" },
    ],
  });
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const aborted: string[] = [];
  page.on("requestfailed", (request) => {
    if (request.url().includes("month=2026-06")) aborted.push(request.url());
  });
  await page.route("**/wavescan/overview**", async (route) => {
    if (new URL(route.request().url()).searchParams.get("month") !== "2026-06")
      return route.fallback();
    await gate;
    await route
      .fulfill({
        json: {
          ...wavescanClickFixture,
          month: "2026-06",
          boxes: [{ ...wavescanClickFixture.boxes[0], color_name: "Obsolete Wave colour" }],
        },
      })
      .catch(() => {});
  });
  await page.goto("/plant/FTM");
  await expect(page.getByRole("button", { name: "2026-09", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await card(page).locator("[data-wavescan-box]").first().click();
  await page.getByRole("button", { name: "2026-06", exact: true }).click();
  await expect(page.locator("[data-wavescan-box][aria-expanded='true']")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "WaveScan box detail" })).toHaveCount(0);
  await page.getByRole("button", { name: "2026-09", exact: true }).click();
  await expect(page.locator("[data-wavescan-box]")).toHaveCount(4);
  await expect.poll(() => aborted.length).toBeGreaterThan(0);
  release();
  await expect(page.getByText("Obsolete Wave colour")).toHaveCount(0);
  await page.getByRole("button", { name: "Color", exact: true }).click();
  await page.getByRole("button", { name: "Seismic Tan", exact: true }).click();
  await expect
    .poll(() => fixture.reads.at(-1)?.searchParams.getAll("color"))
    .toEqual(["Absolute / Shadow Black", "Arctic White"]);
  await page.getByRole("button", { name: "Arctic White", exact: true }).click();
  await expect(page.locator("[data-wavescan-box]")).toHaveCount(3);
  await expect
    .poll(() => fixture.reads.at(-1)?.searchParams.getAll("color"))
    .toEqual(["Absolute / Shadow Black"]);
  await page.getByRole("button", { name: "P703 DBL RANGER", exact: true }).click();
  await expect
    .poll(() => fixture.reads.at(-1)?.searchParams.getAll("model"))
    .toEqual(["P703 DBL RAPTOR"]);
  await expect(page.locator("[data-wavescan-box]")).toHaveCount(2);
});
