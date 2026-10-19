import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { mockHistory } from "../history-fixtures";
import { interactionsFixture as polishFixture } from "../film-overview-interactions-fixtures";
import { boxKey, groupFilmBoxes } from "../../src/features/filmthickness/film-overview-display";

async function mockOverview(page: Page, role = "viewer") {
  await mockHistory(page, role);
  const reads: URL[] = [],
    forbidden: string[] = [];
  let current = polishFixture;
  await page.route("**/api/v1/**", (route) => {
    const req = route.request();
    if (
      req.method() !== "GET" ||
      /filmthickness\/(?!overview)|wavescan\/overview/.test(new URL(req.url()).pathname)
    ) {
      forbidden.push(req.url());
      return route.abort();
    }
    return route.fallback();
  });
  await page.route("**/filmthickness/overview**", (route) => {
    const url = new URL(route.request().url());
    reads.push(url);
    const models = url.searchParams.getAll("models"),
      colors = url.searchParams.getAll("colors");
    return route.fulfill({
      json: {
        ...current,
        month: url.searchParams.get("month") ?? current.month,
        models,
        colors,
        boxes: current.boxes.filter(
          (box) =>
            (!models.length || models.includes(box.model_code)) &&
            (!colors.length || colors.includes(box.color_name)),
        ),
      },
    });
  });
  return {
    reads,
    forbidden,
    replace: (next: typeof polishFixture) => {
      current = next;
    },
  };
}
const panel = (page: Page, model: string, orient: string) =>
  page.getByRole("region", { name: `${model} ${orient}`, exact: true });
const detail = (page: Page, model: string, orient: string) =>
  panel(page, model, orient).getByRole("region", { name: "Box detail" });

for (const width of [390, 768, 1440])
  for (const theme of ["light", "dark"]) {
    test(`T70 fixture tiles/cards ${width} ${theme}, dates, independent summaries and clean plot`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.clock.setSystemTime(new Date("2026-10-06T00:00:00Z"));
      const { reads, forbidden } = await mockOverview(page);
      await page.goto("/plant/AAT?paint=film&filmMonth=2026-09");
      await page.evaluate(
        (theme) => document.documentElement.classList.toggle("dark", theme === "dark"),
        theme,
      );
      await expect(page.locator("[data-film-box]")).toHaveCount(8);
      const tiles = page.getByRole("tab");
      await expect(tiles).toHaveText(["E-coat", "Primer", "Base", "Clear"]);
      const positions = await tiles.evaluateAll((elements) =>
        elements.map((el) => {
          const r = el.getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height };
        }),
      );
      expect(positions.every((r) => r.height >= 44)).toBe(true);
      // The compact selector presents four labelled layers in one row.
      expect(new Set(positions.map((r) => Math.round(r.y))).size).toBe(1);
      expect(
        Math.max(...positions.map((r) => r.width)) - Math.min(...positions.map((r) => r.width)),
      ).toBeLessThan(2);
      const layerIcons = page.locator(".film-coating-stack svg");
      await expect(layerIcons).toHaveCount(4);
      expect(
        await layerIcons.evaluateAll((icons) =>
          icons.every((icon) => icon.getAttribute("aria-hidden") === "true"),
        ),
      ).toBe(true);
      await expect(
        page.locator("[data-film-point], .film-point, .film-box circle, .film-box path"),
      ).toHaveCount(0);
      await expect(page.locator("[data-highlight='WARNING'].film-slot-band")).toHaveCount(1);
      await expect(page.locator("[data-highlight='FAIL'].film-slot-band")).toHaveCount(1);
      const h = panel(page, "U704", "Horizontal"),
        v = panel(page, "U704", "Vertical");
      expect((await v.boundingBox())!.y).toBeGreaterThan((await h.boundingBox())!.y);
      await expect(v.locator(".film-slot-band")).toHaveCount(0);
      const fail = h.locator("[data-film-box]").first();
      await fail.hover();
      await fail.focus();
      await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(0);
      await fail.press("Enter");
      await expect(detail(page, "U704", "Horizontal")).toBeVisible();
      await expect(detail(page, "U704", "Horizontal").locator(".film-summary-primary")).toHaveText(
        "Average9 µmObserved minimum10 µmObserved maximum40 µm",
      );
      await expect(fail).toHaveAttribute("data-status", "critical");
      await expect(fail.locator("[data-mean]")).toHaveText("9");
      await v.locator("[data-film-box]").first().focus();
      await v.locator("[data-film-box]").first().press(" ");
      await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(2);
      await h
        .getByRole("button", { name: "Absolute / Shadow Black; Horizontal summary", exact: true })
        .click();
      const hd = detail(page, "U704", "Horizontal");
      await expect(hd).toContainText("Pass");
      await hd.locator("summary").filter({ hasText: "Outside-limit readings" }).click();
      const readings = hd.getByRole("list", { name: "Outside-limit reading details" });
      await expect(readings.locator("li")).toHaveCount(4);
      expect(await readings.locator("li").allTextContents()).toEqual([
        "Measurement date12 Aug 2026PointLOW-01Value (µm)14.12345678901234567Published limitBelow minimum",
        "Measurement dateDate unavailablePointLOW-01Value (µm)14.12345678901234567Published limitBelow minimum",
        "Measurement dateDate unavailablePointLOW-01Value (µm)14.12345678901234567Published limitBelow minimum",
        "Measurement date25 Aug 2026PointLOW-02Value (µm)14.12345678901234567Published limitBelow minimum",
      ]);
      await hd.locator("summary").filter({ hasText: "Detailed measurements" }).click();
      await expect(hd).toContainText("18.12345678901234567");
      const body = await page.locator("body").textContent();
      expect(body).not.toMatch(/[a-f0-9]{64}/);
      expect(body).not.toContain("API status:");
      expect(body).not.toContain("Family order");
      await panel(page, "P703 DBL RANGER", "Horizontal").locator("[data-film-box]").click();
      await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(3);
      await page.screenshot({
        path: `test-results/evidence/T71/fixture-independent-${width}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
      await hd.getByRole("button", { name: "Close detail" }).click();
      await expect(hd).toHaveCount(0);
      await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(2);
      await v.locator("[data-film-box]").first().press("Escape");
      await expect(detail(page, "U704", "Vertical")).toHaveCount(0);
      await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(1);
      await h.getByRole("button", { name: "Aqua; Horizontal summary", exact: true }).click();
      await expect(h.locator("[data-film-box]").nth(1)).toHaveAttribute("data-status", "over");
      await expect(h.locator("[data-mean]").nth(1)).toHaveText("25");
      await detail(page, "U704", "Horizontal")
        .locator("summary")
        .filter({ hasText: "Outside-limit readings" })
        .click();
      await expect(detail(page, "U704", "Horizontal")).toContainText("25 Aug 2026");
      await expect(detail(page, "U704", "Horizontal")).toContainText("Above maximum");
      const specColours = await h.locator("[data-spec]").evaluateAll((elements) =>
        elements.map((el) => ({
          field: el.getAttribute("data-spec"),
          colour: getComputedStyle(el).stroke,
        })),
      );
      expect(specColours.find((s) => s.field === "lo")!.colour).not.toBe(
        specColours.find((s) => s.field === "hi")!.colour,
      );
      expect(specColours.find((s) => s.field === "hi")!.colour).toBe(
        specColours.find((s) => s.field === "target")!.colour,
      );
      await page.screenshot({
        path: `test-results/evidence/T71/fixture-interactions-${width}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
      const before = reads.length;
      const ecoat = page.getByRole("tab", { name: "E-coat", exact: true });
      await ecoat.focus();
      await ecoat.press("ArrowRight");
      await expect(page.getByRole("tab", { name: "Primer", exact: true })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await page.getByRole("tab", { name: "Primer", exact: true }).press("End");
      await expect(page.getByRole("tab", { name: "Clear", exact: true })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(0);
      const clear = panel(page, "U704", "Horizontal");
      await clear.locator("[data-film-box]").first().click();
      await expect(detail(page, "U704", "Horizontal")).toContainText("Not graded");
      await expect(clear.locator("[data-spec='lo']")).toHaveCount(2);
      await expect(clear.locator("[data-spec='hi']")).toHaveCount(0);
      await expect(page.getByText("No Vertical readings", { exact: true })).toBeVisible();
      const target = clear.locator("[data-spec='target']");
      expect(
        await target.evaluate((el) => {
          const line = el.getBoundingClientRect(),
            svg = el.closest("svg")!.getBoundingClientRect();
          return line.top > svg.top && line.bottom < svg.bottom;
        }),
      ).toBe(true);
      await page.screenshot({
        path: `test-results/evidence/T71/fixture-interactions-clear-${width}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
      await page.getByRole("tab", { name: "Clear", exact: true }).press("Home");
      await expect(ecoat).toHaveAttribute("aria-selected", "true");
      expect(reads.length).toBe(before);
      expect(forbidden).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      expect(await ecoat.evaluate((el) => getComputedStyle(el).transitionDuration)).toBe("0s");
    });
  }

for (const role of ["viewer", "engineer", "admin"])
  test(`T70 ${role} multi-colour GET, legacy URL, retained deselection, reset and back/forward`, async ({
    page,
  }) => {
    const { reads, forbidden } = await mockOverview(page, role);
    await page.goto("/plant/AAT?paint=film&filmMonth=2026-09&filmColor=Zulu%20White");
    await expect(page.locator("[data-film-box]")).toHaveCount(2);
    await page.getByRole("button", { name: "Color", exact: true }).click();
    await page.getByRole("button", { name: "Absolute / Shadow Black", exact: true }).click();
    await expect(page.locator("[data-film-box]")).toHaveCount(4);
    expect(reads.at(-1)!.searchParams.getAll("colors")).toEqual([
      "Zulu White",
      "Absolute / Shadow Black",
    ]);
    await expect(page).toHaveURL(/filmColors=/);
    await expect(page).not.toHaveURL(/filmColor=/);
    await page.reload();
    await expect(page.locator("[data-film-box]")).toHaveCount(4);
    await page.getByRole("button", { name: "Color", exact: true }).click();
    await page.getByRole("button", { name: "Zulu White", exact: true }).click();
    await expect(page.locator("[data-film-box]")).toHaveCount(2);
    expect(reads.at(-1)!.searchParams.getAll("colors")).toEqual(["Absolute / Shadow Black"]);
    await page.goBack();
    await expect(page.locator("[data-film-box]")).toHaveCount(4);
    await page.goForward();
    await expect(page.locator("[data-film-box]")).toHaveCount(2);
    await expect(page.getByRole("button", { name: "All colours", exact: true })).toHaveCount(0);
    if (
      (await page
        .getByRole("button", { name: "Color", exact: true })
        .getAttribute("aria-expanded")) === "false"
    )
      await page.getByRole("button", { name: "Color", exact: true }).click();
    await page.getByRole("button", { name: "Absolute / Shadow Black", exact: true }).click();
    await expect(page).not.toHaveURL(/filmColors?=/);
    await expect(page.locator("[data-film-box]")).toHaveCount(8);
    expect(reads.at(-1)!.searchParams.has("colors")).toBe(false);
    await expect(page).toHaveURL(/filmMonth=2026-09/);
    await page.goto(
      "/plant/AAT?paint=film&filmMonth=2026-09&filmColors=" +
        encodeURIComponent(JSON.stringify(["Zulu White", "Aqua", "Zulu White", null, 42, ""])) +
        "&filmColor=Legacy",
    );
    await expect(page.locator("[data-film-box]")).toHaveCount(4);
    expect(reads.at(-1)!.searchParams.getAll("colors")).toEqual(["Zulu White", "Aqua"]);
    await page.getByRole("button", { name: "U704", exact: true }).click();
    await expect(page).not.toHaveURL(/filmColors?=/);
    await expect(page).toHaveURL(/filmModel=U704/);
    await page.getByRole("button", { name: "2026-08", exact: true }).click();
    await expect(page).not.toHaveURL(/filmModel|filmColors?=/);
    await page.getByRole("button", { name: /Clear all/i }).click();
    await expect(page).not.toHaveURL(/paint=film|filmMonth|filmModel|filmColors?=/);
    expect(forbidden.filter((url) => !url.includes("wavescan"))).toEqual([]);
  });

test("T70 stale response/scope reset and same-scope removed selection", async ({ page }) => {
  const mock = await mockOverview(page);
  await page.goto("/plant/AAT?paint=film&filmMonth=2026-09");
  await panel(page, "U704", "Horizontal").locator("[data-film-box]").first().click();
  await panel(page, "U704", "Vertical").locator("[data-film-box]").first().click();
  await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(2);
  mock.replace({
    ...polishFixture,
    boxes: polishFixture.boxes.filter((box) => box.color_name !== "Zulu White"),
  });
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect(page.locator("[data-film-box]")).toHaveCount(6);
  await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(0);
  await panel(page, "U704", "Horizontal").locator("[data-film-box]").first().click();
  await page.getByRole("button", { name: "2026-08", exact: true }).click();
  await expect(page).toHaveURL(/filmMonth=2026-08/);
  await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(0);
});

test("T70 touch opens only selected card summary", async ({ browser }) => {
  const context = await browser.newContext({
    hasTouch: true,
    viewport: { width: 390, height: 900 },
  });
  const page = await context.newPage();
  await mockOverview(page);
  await page.goto("http://localhost:5173/plant/AAT?paint=film&filmMonth=2026-09");
  const box = panel(page, "U704", "Horizontal").locator("[data-film-box]").first();
  await box.hover();
  await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(0);
  await box.tap();
  await expect(detail(page, "U704", "Horizontal")).toBeVisible();
  await context.close();
});

test("T70 live GET-only dated summaries, clean plots, all plants and plural colours", async ({
  page,
}) => {
  // Four live plants, all layers and full-page captures exceed the single-page budget.
  test.setTimeout(90000);
  const forbidden: string[] = [];
  await page.route("**/api/v1/**", (route) => {
    const req = route.request();
    if (
      req.method() !== "GET" ||
      /filmthickness\/(?!overview)|wavescan\/overview/.test(new URL(req.url()).pathname)
    ) {
      forbidden.push(req.url());
      return route.abort();
    }
    return route.continue();
  });
  for (const code of ["AAT", "FVL", "SAP", "FTM"]) {
    const response = await page.request.get(
      `http://localhost:8012/api/v1/plants/${code}/filmthickness/overview${code === "FTM" ? "?month=2026-05" : ""}`,
    );
    expect(response.status()).toBe(200);
    const data = await response.json();
    mkdirSync("test-results/evidence/T71", { recursive: true });
    writeFileSync(
      `test-results/evidence/T71/live-${code}-payload.json`,
      JSON.stringify(data, null, 2),
    );
    await page.goto(`/plant/${code}?paint=film&filmMonth=${data.month}`);
    for (const layer of [
      { code: "ECOAT", name: "E-coat" },
      { code: "PRIMER", name: "Primer" },
      { code: "BASE", name: "Base" },
      { code: "CLEAR", name: "Clear" },
    ] as const) {
      await page.getByRole("tab", { name: layer.name, exact: true }).click();
      const groups = groupFilmBoxes(data, layer.code);
      const boxes = groups.flatMap((g) => [...g.horizontal, ...g.vertical]);
      await expect(page.locator("[data-film-box]")).toHaveCount(boxes.length);
      expect(
        await page
          .locator("[data-film-box]")
          .evaluateAll((elements) => elements.map((el) => el.getAttribute("data-film-box"))),
      ).toEqual(boxes.map(boxKey));
      await expect(page.locator("[data-film-point],.film-point")).toHaveCount(0);
      for (const group of groups) {
        for (const orient of ["Horizontal", "Vertical"]) {
          const card = panel(page, group.model, orient);
          const actual = orient === "Horizontal" ? group.horizontal : group.vertical;
          const chosen = actual.find((b) => b.out_of_spec.length) || actual[0];
          if (!chosen) continue;
          await card
            .getByRole("button", { name: `${chosen.color_name}; ${orient} summary`, exact: true })
            .click();
          const summary = card.getByRole("region", { name: "Box detail" });
          await summary.locator("summary").filter({ hasText: "Outside-limit readings" }).click();
          if (chosen.out_of_spec.length) {
            await expect(summary.getByRole("list").locator("li")).toHaveCount(
              chosen.out_of_spec.length,
            );
            expect(await summary.getByRole("list").locator("li").allTextContents()).not.toEqual([]);
          }
          expect(await summary.textContent()).not.toMatch(/[a-f0-9]{64}/);
        }
      }
      for (const theme of ["light", "dark"]) {
        await page.evaluate(
          (theme) => document.documentElement.classList.toggle("dark", theme === "dark"),
          theme,
        );
        await page.screenshot({
          path: `test-results/evidence/T71/live-interactions-${code}-${layer.code}-${theme}.png`,
          fullPage: true,
          animations: "disabled",
        });
      }
    }
    if (code === "AAT") {
      await page.getByRole("tab", { name: "Primer", exact: true }).click();
      const colours = data.color_options
        .slice(0, 2)
        .map((option: { color_name: string }) => option.color_name);
      await page.goto(
        `/plant/AAT?paint=film&filmMonth=${data.month}&filmColors=${encodeURIComponent(JSON.stringify(colours))}`,
      );
      await page.getByRole("tab", { name: "Primer", exact: true }).click();
      await expect(page.locator("[data-film-box]")).toHaveCount(
        data.boxes.filter(
          (box: { layer_code: string; color_name: string }) =>
            box.layer_code === "PRIMER" && colours.includes(box.color_name),
        ).length,
      );
      await page.screenshot({
        path: "test-results/evidence/T71/live-AAT-multiple-colours.png",
        fullPage: true,
        animations: "disabled",
      });
    }
  }
  expect(forbidden).toEqual([]);
});
