import { expect, test, type Page } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { filmBox, filmOverviewFixture } from "../film-overview-fixtures";

for (const width of [390, 1440]) {
  for (const theme of ["light", "dark"]) {
    test(`compact coating selector ${width} ${theme}: labelled, keyboard usable and bounded`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((value) => localStorage.setItem("ct-theme", value), theme);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await mockFilmOverview(page);
      await page.goto("/plant/FTM?paint=film");
      const selector = page.locator(".film-stack-panel");
      await expect(selector).toContainText("Coating layer");
      await expect(page.getByRole("tablist", { name: "Coating layers" })).toBeVisible();
      const bounds = await selector.boundingBox();
      expect(bounds!.height).toBeLessThan(115);
      if (width === 1440) {
        expect(bounds!.width).toBeLessThanOrEqual(310);
        const title = await page
          .getByRole("heading", { name: "Film Thickness", exact: true })
          .boundingBox();
        expect(bounds!.x).toBeGreaterThan(title!.x + title!.width);
      }
      for (const label of ["E-coat", "Primer", "Base", "Clear"]) {
        const tab = page.getByRole("tab", { name: label, exact: true });
        const target = await tab.boundingBox();
        expect(target!.height).toBeGreaterThanOrEqual(44);
        expect(target!.width).toBeGreaterThanOrEqual(44);
        await tab.click();
        await expect(tab).toHaveAttribute("aria-selected", "true");
        await expect(page.getByRole("tabpanel")).toHaveAttribute("data-state", "active");
      }
      await page.getByRole("tab", { name: "E-coat", exact: true }).focus();
      await page.keyboard.press("ArrowRight");
      await expect(page.getByRole("tab", { name: "Primer", exact: true })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await page.getByText("Standards & colour order", { exact: true }).click();
      await expect(
        page.getByText(filmOverviewFixture.standards_note, { exact: true }),
      ).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: `test-results/film-layer-polish/selector-${width}-${theme}.png`,
        fullPage: true,
      });
    });
  }
}

async function mockFilmOverview(
  page: Page,
  role = "viewer",
  boxes = filmOverviewFixture.boxes,
  sequence = filmOverviewFixture.color_sequence,
) {
  await mockHistory(page, role);
  const reads: URL[] = [],
    forbidden: string[] = [];
  await page.route("**/api/v1/**", (route) =>
    route.request().method() === "GET" ? route.fallback() : route.abort(),
  );
  await page.route("**/api/v1/plants/*/filmthickness/**", async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.endsWith("/overview")) {
      forbidden.push(url.pathname);
      return route.abort();
    }

    const month = url.searchParams.get("month") ?? "2026-08";
    const models = url.searchParams.getAll("models"),
      colors = url.searchParams.getAll("colors");
    await route.fulfill({
      json: {
        ...filmOverviewFixture,
        plant_code: url.pathname.split("/")[4],
        month,
        color_sequence: sequence,
        models,
        colors,
        boxes:
          month === "1999-01"
            ? []
            : boxes.filter(
                (box) =>
                  (!models.length || models.includes(box.model_code)) &&
                  (!colors.length || colors.includes(box.color_name)),
              ),
      },
    });
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.endsWith("/filmthickness/overview") && response.ok()) reads.push(url);
  });
  page.on("request", (request) => {
    if (request.url().includes("/wavescan/overview")) forbidden.push(request.url());
  });
  return { reads, forbidden };
}

async function selectOnlyBlue(page: Page) {
  for (const name of ["Absolute / Shadow Black", "Seismic Tan"]) {
    const button = page.getByRole("button", { name, exact: true });
    if ((await button.getAttribute("aria-pressed")) === "true") await button.click();
  }
  const blue = page.getByRole("button", { name: "Blue", exact: true });
  if ((await blue.getAttribute("aria-pressed")) !== "true") await blue.click();
}

test("T67 four tabs, model order, stacked per-box specs and accessible exact details without vehicle grid", async ({
  page,
}) => {
  const { reads, forbidden } = await mockFilmOverview(page);
  await page.goto(`/plant/FTM?paint=film&filmVehicle=${"d".repeat(64)}`);
  for (const name of ["E-coat", "Primer", "Base", "Clear"])
    await expect(page.getByRole("tab", { name, exact: true })).toBeVisible();
  await expect(page).toHaveURL(/filmMonth=2026-08/);
  await expect(page.getByRole("heading", { level: 3 })).toHaveText(
    filmOverviewFixture.model_options,
  );
  await expect(page.locator("[data-film-box]")).toHaveCount(4);
  await expect(page.locator('[data-spec="lo"][data-value="0"]')).toHaveCount(1);
  // Only the RAPTOR Vertical panel is empty; colours without readings get no slot.
  await expect(page.getByText("No Vertical readings", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Gold point", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: "test-results/film-layer-polish/evidence/T71/fixture-mixed-specs-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.screenshot({
    path: "test-results/film-layer-polish/evidence/T71/fixture-mixed-specs-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  const box = page
    .locator("[data-film-box]")
    .filter({ has: page.locator("title", { hasText: "Absolute / Shadow Black; Horizontal" }) });
  await box.focus();
  await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(0);
  await box.press("Enter");
  await page
    .getByRole("region", { name: "Box detail" })
    .locator("summary")
    .filter({ hasText: "Detailed measurements" })
    .click();
  await expect(page.getByRole("region", { name: "Box detail" })).toContainText(
    "10.00000000000000001",
  );
  await expect(page.getByRole("region", { name: "Box detail" })).toContainText(
    "18.12345678901234567",
  );
  await page.screenshot({
    path: "test-results/film-layer-polish/evidence/T71/fixture-decimal-details-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await box.press("Enter");
  await box.press("Escape");
  await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(0);
  await box.click();
  await expect(page.getByRole("region", { name: "Box detail" })).toBeVisible();
  await page.keyboard.press("Escape");
  const requests = reads.length;
  await page.getByRole("tab", { name: "Primer", exact: true }).click();
  await expect(page.getByText("No readings for this layer.")).toBeVisible();
  await page.getByRole("tab", { name: "Primer", exact: true }).press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Base", exact: true })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.locator("[data-film-box]")).toHaveCount(1);
  await expect(page.locator("[data-spec]")).toHaveCount(0);
  await page.locator("[data-film-box]").press("Enter");
  await expect(page.getByRole("region", { name: "Box detail" })).toContainText("No standard");
  await page.getByRole("tab", { name: "Clear", exact: true }).click();
  await expect(page.locator('[data-spec="target"][data-value="46"]')).toHaveCount(2);
  expect(reads.length).toBe(requests);
  expect(forbidden).toEqual([]);
});

for (const role of ["viewer", "engineer", "admin"])
  test(`T67 ${role} overview options, default URL, filters, month clearing, refresh and back/forward`, async ({
    page,
  }) => {
    const { reads, forbidden } = await mockFilmOverview(page, role);
    await page.goto(
      "/plant/FTM?paint=film&filmModel=P703%20DBL%20RANGER&filmColor=Absolute%20%2F%20Shadow%20Black",
    );
    await expect(page).toHaveURL(/filmMonth=2026-08/);
    await expect(page).toHaveURL(/filmColor=Absolute/);
    await expect(page.locator("[data-film-box]")).toHaveCount(2);
    await expect.poll(() => reads.length).toBe(2);
    expect(reads[0].searchParams.has("month")).toBe(false);
    expect(reads[1].searchParams.getAll("colors")).toEqual(["Absolute / Shadow Black"]);
    expect(reads[1].searchParams.getAll("models")).toEqual(["P703 DBL RANGER"]);
    await page.getByRole("tab", { name: "Clear", exact: true }).click();
    await page.reload();
    await expect(page.getByRole("tab", { name: "E-coat" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.locator("[data-film-box]")).toHaveCount(2);
    await page.getByRole("button", { name: "P703 DBL RANGER", exact: true }).click();
    await expect(page).not.toHaveURL(/filmModel|filmColor|filmVehicle/);
    await page.getByRole("button", { name: "Color", exact: true }).click();
    await expect(page.getByRole("button", { name: "Blue", exact: true })).toBeVisible();
    await selectOnlyBlue(page);
    await expect(page.locator("[data-film-box]")).toHaveCount(1);
    await page.getByRole("button", { name: "2026-07", exact: true }).click();
    await expect(page).toHaveURL(/filmMonth=2026-07/);
    await expect(page).not.toHaveURL(/filmModel|filmColor|filmVehicle/);
    await page.goBack();
    await expect(page).toHaveURL(/filmColors=.*Blue/);
    await expect(page.locator("[data-film-box]")).toHaveCount(1);
    await page.goForward();
    await expect(page).toHaveURL(/filmMonth=2026-07/);
    await expect(page.locator("[data-film-box]")).toHaveCount(4);
    expect(forbidden).toEqual([]);
  });

test("T67 explicit unknown month, old colour and null month stay honest without loops", async ({
  page,
}) => {
  const { reads, forbidden } = await mockFilmOverview(page);
  await page.goto("/plant/FTM?paint=film&filmMonth=1999-01");
  await expect(
    page.getByText("No active Film Thickness readings for this selection."),
  ).toBeVisible();
  await expect(page.getByText("January 1999 · µm")).toBeVisible();
  await expect(page).toHaveURL(/filmMonth=1999-01/);
  expect(reads.length).toBe(1);
  await page.goto("/plant/FTM?paint=film&filmMonth=2026-08&filmColor=Shadow%20Black");
  await expect(
    page.getByText("No active Film Thickness readings for this selection."),
  ).toBeVisible();
  await expect(page).toHaveURL(/filmColor=Shadow/);
  await page.route("**/filmthickness/overview**", (route) =>
    route.fulfill({
      json: { ...filmOverviewFixture, month: null, available_months: [], boxes: [] },
    }),
  );
  await page.goto("/plant/FVL?paint=film");
  await expect(page.getByText("No Film Thickness measurements for this plant.")).toBeVisible();
  await expect(page).not.toHaveURL(/filmMonth/);
  await expect(page.getByRole("tab")).toHaveCount(4);
  expect(forbidden).toEqual([]);
});

for (const status of [401, 403, 404, 422, 503])
  test(`T67 ${status} shows actual envelope and Retry replaces error`, async ({ page }) => {
    await mockFilmOverview(page);
    let denied = true;
    await page.route("**/filmthickness/overview**", (route) =>
      denied
        ? route.fulfill({
            status,
            json: {
              statusCode: status,
              error: "Read refused",
              message: `Actual film read ${status}`,
              correlationId: `film-${status}`,
            },
          })
        : route.fallback(),
    );
    await page.goto("/plant/FTM?paint=film&filmMonth=2026-08");
    await expect(page.getByRole("alert")).toContainText(`Actual film read ${status}`);
    await expect(page.getByRole("alert")).toContainText(`film-${status}`);
    await expect(page.locator("[data-film-box]")).toHaveCount(0);
    await expect(
      page.getByText("No active Film Thickness readings for this selection."),
    ).toHaveCount(0);
    if (status === 503)
      await page.screenshot({
        path: "test-results/film-layer-polish/evidence/T71/fixture-error-503.png",
        fullPage: true,
        animations: "disabled",
      });
    denied = false;
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expect(page.locator("[data-film-box]")).toHaveCount(4);
  });

test("T67 obsolete month/filter/plant reads cannot display stale boxes while loading", async ({
  page,
}) => {
  const { forbidden } = await mockFilmOverview(page);
  const aborted: string[] = [];
  page.on("requestfailed", (request) => {
    if (request.url().includes("month=2026-07")) aborted.push(request.failure()?.errorText ?? "");
  });
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/filmthickness/overview**", async (route) => {
    if (new URL(route.request().url()).searchParams.get("month") !== "2026-07")
      return route.fallback();
    await gate;
    await route
      .fulfill({
        json: {
          ...filmOverviewFixture,
          month: "2026-07",
          boxes: [filmBox({ color_name: "Obsolete colour" })],
        },
      })
      .catch(() => {});
  });
  await page.goto("/plant/FTM?paint=film&filmMonth=2026-08");
  await expect(page.locator("[data-film-box]")).toHaveCount(4);
  await page.getByRole("button", { name: "2026-07", exact: true }).click();
  await expect(page.getByText("Loading Film Thickness overview...")).toBeVisible();
  await expect(page.locator("[data-film-box]")).toHaveCount(0);
  await page.goBack();
  await expect(page.locator("[data-film-box]")).toHaveCount(4);
  await expect.poll(() => aborted.length).toBeGreaterThan(0);
  release();
  await expect(page.getByText("Obsolete colour", { exact: true })).toHaveCount(0);
  await page.goto("/plant/SAP?paint=film&filmMonth=2026-08&filmColor=Blue");
  await expect(page.locator("[data-film-box]")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "SAP", exact: true })).toBeVisible();
  expect(forbidden).toEqual([]);
});

test("T67 colour/model clear legacy vehicle, same-scope refetch preserves layer, clear-all restores WaveScan", async ({
  page,
}) => {
  const { reads } = await mockFilmOverview(page);
  await page.goto(`/plant/FTM?paint=film&filmMonth=2026-08&filmVehicle=${"d".repeat(64)}`);
  await expect(page.locator("[data-film-box]")).toHaveCount(4);
  await page.getByRole("button", { name: "Color", exact: true }).click();
  await selectOnlyBlue(page);
  await expect(page).not.toHaveURL(/filmVehicle/);
  await page.getByRole("tab", { name: "Clear", exact: true }).click();
  const beforeRefetch = reads.length;
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect.poll(() => reads.length).toBeGreaterThan(beforeRefetch);
  await expect(page.getByRole("tab", { name: "Clear", exact: true })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("button", { name: "P703 DBL RANGER", exact: true }).click();
  await expect(page).not.toHaveURL(/filmColor|filmVehicle/);
  expect(
    reads.every((url) => !url.searchParams.has("model") && !url.searchParams.has("color")),
  ).toBe(true);
  await page.getByRole("button", { name: /Clear all/i }).click();
  await expect(page).not.toHaveURL(/paint=film|filmMonth|filmModel|filmColor|filmVehicle/);
  await expect(page.getByRole("region", { name: "Film Monthly Overview" })).toHaveCount(0);
});

for (const width of [390, 768, 1440])
  for (const theme of ["light", "dark"])
    test(`T67 ${width}px ${theme} many colours local scroll, full labels and touch detail`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      const boxes = Array.from({ length: 8 }, (_, index) => [
        filmBox({
          color_rank: index + 1,
          color_name: `Canonical long colour ${index}`,
          orient: "H",
        }),
        filmBox({
          color_rank: index + 1,
          color_name: `Canonical long colour ${index}`,
          orient: "V",
        }),
      ]).flat();
      await mockFilmOverview(
        page,
        "viewer",
        boxes,
        Array.from({ length: 8 }, (_, index) => ({
          ...filmOverviewFixture.color_sequence[0],
          rank: index + 1,
          color_name: `Canonical long colour ${index}`,
        })),
      );
      await page.goto("/plant/AAT?paint=film&filmMonth=2026-08");
      await page.evaluate((theme) => {
        document.documentElement.classList.toggle("dark", theme === "dark");
        document.documentElement.style.colorScheme = theme;
      }, theme);
      await expect(page.locator("[data-film-box]")).toHaveCount(16);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      const scroll = page.getByRole("region", { name: /horizontally scrollable/ }).first();
      expect(await scroll.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(
        true,
      );
      await scroll.focus();
      await scroll.press("ArrowRight");
      await expect.poll(() => scroll.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
      await page.locator("[data-film-box]").first().click();
      await expect(page.getByRole("region", { name: "Box detail" })).toContainText(
        "Canonical long colour 0",
      );
      expect(
        (await page.locator(".recharts-wrapper").first().boundingBox())!.height,
      ).toBeGreaterThanOrEqual(300);
      await page.screenshot({
        path: `test-results/film-layer-polish/evidence/T71/fixture-${width}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
      await page.setViewportSize({ width: width === 390 ? 768 : 390, height: 900 });
      await expect(page.locator("[data-film-box]")).toHaveCount(16);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.getByRole("tab", { name: "Clear", exact: true }).click();
      await expect(page.getByText("No readings for this layer.")).toBeVisible();
    });

test("T67 read-only live planted scopes and spec lines across SAP/AAT/FTM/FVL", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const mutations: string[] = [],
    evidence: unknown[] = [];
  await page.route("**/api/v1/**", (route) => {
    if (route.request().method() !== "GET") {
      mutations.push(route.request().url());
      return route.abort();
    }
    return route.continue();
  });
  for (const code of ["SAP", "AAT", "FTM", "FVL"]) {
    const response = await page.request.get(
      `http://localhost:8012/api/v1/plants/${code}/filmthickness/overview`,
    );
    expect(response.status()).toBe(200);
    const data = await response.json();
    evidence.push({ code, data });
    await page.goto(`/plant/${code}?paint=film${code === "FTM" ? "&filmMonth=2026-05" : ""}`);
    await expect(page.getByRole("tab")).toHaveCount(4);
    if (code === "SAP") {
      await expect(page.getByText("No readings for this layer.")).toBeVisible();
      await page.screenshot({
        path: "test-results/film-layer-polish/evidence/T71/live-SAP-ecoat-empty.png",
        animations: "disabled",
        fullPage: true,
      });
      await page.getByRole("tab", { name: "Primer", exact: true }).click();
      await expect(page.getByText("No readings for this layer.")).toBeVisible();
      await page.getByRole("tab", { name: "Base", exact: true }).click();
      await expect(page.locator("[data-film-box]")).toHaveCount(2);
      await expect(page.locator("[data-spec]")).toHaveCount(0);
    } else if (code === "AAT") {
      await page.getByRole("tab", { name: "Primer", exact: true }).click();
      const none = page
        .locator("[data-film-box]")
        .filter({ has: page.locator("title", { hasText: "Seismic Tan; Horizontal" }) });
      await none.first().press("Enter");
      await expect(page.getByRole("region", { name: "Box detail" }).first()).toContainText(
        "No standard",
      );
      await page.screenshot({
        path: "test-results/film-layer-polish/evidence/T71/live-AAT-primer-none.png",
        animations: "disabled",
        fullPage: true,
      });
      await page.getByRole("tab", { name: "Base", exact: true }).click();
      await expect(page.locator("[data-film-box]")).toHaveCount(
        data.boxes.filter((box: { layer_code: string }) => box.layer_code === "BASE").length,
      );
      await page
        .locator("[data-film-box]")
        .filter({ has: page.locator("title", { hasText: "Seismic Tan; Horizontal" }) })
        .first()
        .press("Enter");
      await expect(page.getByRole("region", { name: "Box detail" }).first()).toContainText(
        "No standard",
      );
      await page.screenshot({
        path: "test-results/film-layer-polish/evidence/T71/live-AAT-base-none.png",
        animations: "disabled",
        fullPage: true,
      });
      await page.getByRole("tab", { name: "Clear", exact: true }).click();
      await expect(page.locator('[data-spec="target"]')).toHaveCount(
        data.boxes.filter(
          (box: { layer_code: string; target: string | null }) =>
            box.layer_code === "CLEAR" && box.target !== null,
        ).length,
      );
      await expect(page.locator('[data-spec="hi"]')).toHaveCount(0);
    } else if (code === "FTM") {
      await page.getByRole("tab", { name: "Clear", exact: true }).click();
      await expect(page.locator('[data-spec="lo"][data-value="36.00"]')).toHaveCount(1);
      await expect(page.locator('[data-spec="lo"][data-value="30.00"]')).toHaveCount(1);
      await expect(page.locator('[data-spec="target"][data-value="46.00"]')).toHaveCount(2);
    } else {
      await expect(page.locator('[data-spec="lo"][data-value="20.00"]')).toHaveCount(2);
      await expect(page.locator('[data-spec="hi"]')).toHaveCount(0);
    }
    for (const theme of ["light", "dark"]) {
      await page.evaluate((theme) => {
        document.documentElement.classList.toggle("dark", theme === "dark");
        document.documentElement.style.colorScheme = theme;
      }, theme);
      await page.screenshot({
        path: `test-results/film-layer-polish/evidence/T71/live-${code}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
    }
  }
  await test.info().attach("live-get-payloads", {
    body: JSON.stringify(evidence, null, 2),
    contentType: "application/json",
  });
  expect(mutations).toEqual([]);
});

test("T67 pointer and actual touch expose singleton details and coincident dashed zero specs", async ({
  browser,
}) => {
  const context = await browser.newContext({
    hasTouch: true,
    viewport: { width: 390, height: 900 },
  });
  const page = await context.newPage();
  await mockFilmOverview(page, "viewer", [
    filmBox({
      q1: "12.25",
      median: "12.25",
      q3: "12.25",
      whisker_lo: "12.25",
      whisker_hi: "12.25",
      box_min: "12.25",
      box_max: "12.25",
      mean: "12.25",
      outliers: [],
      n: 1,
      lo: "0",
      hi: "0",
      target: "0",
      hi_label: "Maximum",
      target_label: "Fixture target",
    }),
  ]);
  await page.goto("http://localhost:5173/plant/FTM?paint=film&filmMonth=2026-08");
  const box = page.locator("[data-film-box]");
  await box.hover();
  await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(0);
  await box.tap();
  const detail = page.getByRole("region", { name: "Box detail" });
  await detail.locator("summary").filter({ hasText: "Detailed measurements" }).click();
  await expect(detail).toContainText("Average12.25");
  await expect(detail).toContainText("Minimum0");
  await expect(detail).toContainText("Maximum0");
  await expect(detail).toContainText("Fixture target0");
  const lines = await box.locator("[data-spec]").evaluateAll((elements) =>
    elements.map((element) => ({
      x1: element.getAttribute("x1"),
      x2: element.getAttribute("x2"),
      y: element.getAttribute("y1"),
      dash: element.getAttribute("stroke-dasharray"),
    })),
  );
  expect(lines).toHaveLength(3);
  expect(new Set(lines.map((line) => line.y)).size).toBe(1);
  expect(lines.every((line) => Number(line.x2) > Number(line.x1) && line.dash)).toBe(true);
  await page.screenshot({
    path: "test-results/film-layer-polish/evidence/T71/fixture-mobile-singleton-zero.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await box.focus();
  await page.screenshot({
    path: "test-results/film-layer-polish/evidence/T71/fixture-desktop-singleton-zero.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
  await context.close();
});

test("T67 switching Film and WaveScan retains independent WaveScan model and colour selections", async ({
  page,
}) => {
  const { reads } = await mockFilmOverview(page);
  const wavescan: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/wavescan/overview")) wavescan.push(request.url());
  });
  await page.goto("/plant/FTM");
  await expect(page.getByRole("heading", { name: "P703 DBL RANGER", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "P703 DBL RANGER", exact: true }).click();
  await expect(page.getByRole("heading", { name: "P703 DBL RANGER", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Color", exact: true }).click();
  await page.getByRole("button", { name: "Arctic White", exact: true }).click();
  await expect(page.getByRole("button", { name: "Arctic White", exact: true })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  const before = wavescan.length;
  await page.getByRole("button", { name: "Film Thickness", exact: true }).click();
  await expect(page.locator("[data-film-box]")).toHaveCount(4);
  await selectOnlyBlue(page);
  await expect(page.locator("[data-film-box]")).toHaveCount(1);
  await page.getByRole("tab", { name: "Clear", exact: true }).click();
  expect(wavescan.length).toBe(before);
  expect(
    reads.every((url) => !url.searchParams.has("model") && !url.searchParams.has("color")),
  ).toBe(true);
  await page.getByRole("button", { name: "WaveScan", exact: true }).click();
  await expect(page.getByRole("button", { name: "P703 DBL RANGER", exact: true })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await expect(page.getByRole("button", { name: "P703 DBL RAPTOR", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByRole("button", { name: "Arctic White", exact: true })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await expect(
    page.getByRole("button", { name: "Aluminum Metallic", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: "P703 DBL RAPTOR", exact: true })).toBeVisible();
});
