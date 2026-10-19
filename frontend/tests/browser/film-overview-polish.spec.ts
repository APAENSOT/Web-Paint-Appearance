import { test, expect } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { mockHistory } from "../history-fixtures";
import { polishFixture } from "../film-overview-polish-fixtures";
import {
  boxKey,
  statusPresentation,
  groupFilmBoxes,
} from "../../src/features/filmthickness/film-overview-display";

for (const width of [390, 768, 1440])
  for (const theme of ["light", "dark"]) {
    test(`T69 fixture ${width} ${theme}: authoritative stacked geometry, points, details and selector`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await mockHistory(page);
      const forbidden: string[] = [];
      let reads = 0;
      await page.route("**/api/v1/**", (route) => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        if (
          request.method() !== "GET" ||
          /filmthickness\/(?!overview)|wavescan\/overview/.test(path)
        ) {
          forbidden.push(request.url());
          return route.abort();
        }
        return route.fallback();
      });
      await page.route("**/filmthickness/overview**", (route) => {
        reads++;
        return route.fulfill({ json: polishFixture });
      });
      await page.goto("/plant/AAT?paint=film&filmMonth=2026-09");
      await page.evaluate((theme) => {
        document.documentElement.classList.toggle("dark", theme === "dark");
        document.documentElement.style.colorScheme = theme;
      }, theme);
      await expect(page.locator("[data-film-box]")).toHaveCount(8);
      await expect(page.getByRole("heading", { level: 3 })).toHaveText(["U704", "P703 DBL RANGER"]);
      const model = page.getByRole("region", { name: "U704 Horizontal", exact: true });
      const vertical = page.getByRole("region", { name: "U704 Vertical", exact: true });
      expect((await vertical.boundingBox())!.y).toBeGreaterThan((await model.boundingBox())!.y);
      expect(
        await model
          .locator("[data-colour]")
          .evaluateAll((elements) => elements.map((el) => el.getAttribute("data-colour"))),
      ).toEqual(["Zulu White", "Aqua", "Absolute / Shadow Black", "Unassigned", "Fallback colour"]);
      await expect(model.locator(".film-family-labels > span")).toHaveText([
        "Light metallic",
        "Dark metallic",
        "Medium solid",
        "No family assigned",
      ]);
      const lowBox = model.locator("[data-film-box]").nth(2);
      await expect(lowBox).toHaveAttribute("data-status", "nominal");
      await expect(lowBox.locator("[data-film-point]")).toHaveCount(0);
      await expect(model.locator("[data-film-point][data-side='HIGH']")).toHaveCount(0);
      await expect(
        model.locator("[data-film-box]").first().locator("[data-film-point]"),
      ).toHaveCount(0);
      await expect(model.locator("[data-mean]").first()).toHaveText("9");
      await expect(model.locator("[data-mean]").nth(1)).toHaveText("25");
      await expect(model.locator("[data-film-box]").first()).toHaveAttribute(
        "data-status",
        "critical",
      );
      await expect(model.locator("[data-film-box]").nth(1)).toHaveAttribute("data-status", "over");
      await expect(model.locator("[data-film-box]").nth(3).locator("[data-spec]")).toHaveCount(0);
      const colours = await model
        .locator("[data-film-box]")
        .evaluateAll((elements) => elements.map((el) => getComputedStyle(el).stroke));
      expect(new Set(colours).size).toBeGreaterThanOrEqual(4);
      for (const panel of [model, vertical]) {
        const ticks = await panel
          .locator(".recharts-yAxis .recharts-cartesian-axis-tick-value")
          .allTextContents();
        expect(ticks.every((tick) => /^-?\d+$/.test(tick))).toBe(true);
        expect(new Set(ticks).size).toBe(ticks.length);
        expect(
          (await panel.locator(".recharts-wrapper").boundingBox())!.height,
        ).toBeGreaterThanOrEqual(320);
        await expect(panel.locator("[data-film-point]")).toHaveCount(0);
      }
      await lowBox.focus();
      await lowBox.press("Enter");
      const detail = page.getByRole("region", { name: "Box detail" });
      await detail.locator("summary").filter({ hasText: "Outside-limit readings" }).click();
      await detail.locator("summary").filter({ hasText: "Detailed measurements" }).click();
      await expect(detail).toContainText("18.12345678901234567");
      await expect(
        detail.getByRole("list", { name: "Outside-limit reading details" }).locator("li"),
      ).toHaveCount(3);
      for (const point of polishFixture.boxes[2].out_of_spec) {
        await expect(detail).toContainText(point.value);
        await expect(detail).toContainText(point.point_code);
        await expect(detail).not.toContainText(point.logical_vehicle_id);
        await expect(detail).toContainText(
          point.measured_date === null ? "Date unavailable" : "Aug 2026",
        );
      }
      await page.screenshot({
        path: `test-results/evidence/T71/fixture-polish-${width}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
      await lowBox.press("Escape");
      await expect(detail).toHaveCount(0);
      const before = reads;
      const ecoat = page.getByRole("tab", { name: "E-coat", exact: true });
      await ecoat.focus();
      await ecoat.press("End");
      await expect(page.getByRole("tab", { name: "Clear", exact: true })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await expect(page.locator(".film-selected-layer")).toHaveText("Clear");
      const clear = page.getByRole("region", { name: "U704 Horizontal", exact: true });
      await expect(clear.getByRole("list", { name: "Horizontal spec legend" })).toHaveText(
        "No point belowMinimum requirement",
      );
      await expect(clear.locator("[data-film-box]").first()).toHaveAttribute(
        "data-status",
        "neutral",
      );
      await expect(
        clear.locator("[data-film-box]").first().locator("[data-spec='lo']"),
      ).toHaveCount(1);
      await clear.locator("[data-film-box]").first().click();
      await expect(detail).toContainText("Not graded");
      await expect(clear.locator("[data-spec='target'][data-value='900']")).toHaveCount(1);
      expect(
        await clear.locator("[data-spec='target']").evaluate((el) => {
          const line = el.getBoundingClientRect(),
            svg = el.closest("svg")!.getBoundingClientRect();
          return line.top > svg.top && line.bottom < svg.bottom;
        }),
      ).toBe(true);
      await expect(page.getByText("No Vertical readings", { exact: true })).toBeVisible();
      await page.screenshot({
        path: `test-results/evidence/T71/fixture-partial-target-${width}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
      await page.getByRole("tab", { name: "Clear", exact: true }).press("Home");
      await expect(ecoat).toHaveAttribute("aria-selected", "true");
      expect(reads).toBe(before);
      expect(forbidden).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      const targets = await page
        .getByRole("tab")
        .evaluateAll((elements) => elements.map((el) => el.getBoundingClientRect().height));
      expect(targets.every((height) => height >= 44)).toBe(true);
      expect(await ecoat.evaluate((el) => getComputedStyle(el).transitionDuration)).toBe("0s");
    });
  }

test("T69 live GET-only authoritative status, order, labels and point counts on all plants", async ({
  page,
}) => {
  const forbidden: string[] = [];
  await page.route("**/api/v1/**", (route) => {
    const req = route.request();
    if (
      req.method() !== "GET" ||
      /\/filmthickness\/(standards|vehicles|points|catalogue)|\/wavescan\/overview/.test(req.url())
    ) {
      forbidden.push(req.url());
      return route.abort();
    }
    return route.continue();
  });
  for (const code of ["AAT", "FVL", "SAP", "FTM"]) {
    const latest = await (
      await page.request.get(`http://localhost:8012/api/v1/plants/${code}/filmthickness/overview`)
    ).json();
    const month = code === "FTM" ? "2026-05" : latest.month;
    const response = await page.request.get(
      `http://localhost:8012/api/v1/plants/${code}/filmthickness/overview?month=${month}`,
    );
    expect(response.status()).toBe(200);
    const data = await response.json();
    writeFileSync(
      `test-results/evidence/T71/live-${code}-payload.json`,
      JSON.stringify(data, null, 2),
    );
    await page.goto(`/plant/${code}?paint=film&filmMonth=${month}`);
    for (const layer of [
      { code: "ECOAT", name: "E-coat" },
      { code: "PRIMER", name: "Primer" },
      { code: "BASE", name: "Base" },
      { code: "CLEAR", name: "Clear" },
    ] as const) {
      await page.getByRole("tab", { name: layer.name, exact: true }).click();
      const actual = data.boxes.filter(
        (box: { layer_code: string }) => box.layer_code === layer.code,
      );
      await expect(page.locator("[data-film-box]")).toHaveCount(actual.length);
      const groups = groupFilmBoxes(data, layer.code);
      expect(
        await page
          .locator("[data-film-box]")
          .evaluateAll((elements) => elements.map((el) => el.getAttribute("data-film-box"))),
      ).toEqual(groups.flatMap((group) => [...group.horizontal, ...group.vertical].map(boxKey)));
      const rendered = await page.locator("[data-film-box]").evaluateAll((elements) =>
        elements.map((el) => ({
          status: el.getAttribute("data-status"),
          points: el.querySelectorAll("[data-film-point]").length,
          specs: Array.from(el.querySelectorAll("[data-spec]")).map((line) => [
            line.getAttribute("data-spec"),
            line.getAttribute("data-value"),
          ]),
        })),
      );
      groups
        .flatMap((group) => [...group.horizontal, ...group.vertical])
        .forEach((box, index) => {
          expect(rendered[index].status).toBe(statusPresentation(box).colour);
          expect(rendered[index].points).toBe(0);
        });
      if (!actual.length) await expect(page.getByText("No readings for this layer.")).toBeVisible();
      if (code === "AAT" && layer.code === "CLEAR") {
        await expect(page.locator("[data-spec='hi']")).toHaveCount(0);
        await expect(page.getByText("Minimum requirement", { exact: true }).first()).toBeVisible();
        expect(
          actual.every(
            (box: { lo: string; target: string }) =>
              Number(box.lo) === 30 && Number(box.target) === 35,
          ),
        ).toBe(true);
      }
      for (const theme of ["light", "dark"]) {
        await page.evaluate(
          (theme) => document.documentElement.classList.toggle("dark", theme === "dark"),
          theme,
        );
        await page.screenshot({
          path: `test-results/evidence/T71/live-${code}-${layer.code}-${theme}.png`,
          fullPage: true,
          animations: "disabled",
        });
      }
    }
  }
  expect(forbidden).toEqual([]);
});
