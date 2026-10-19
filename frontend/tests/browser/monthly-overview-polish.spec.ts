import { expect, test, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { monthlyFilmFixture, monthlyWaveFixture } from "../monthly-overview-fixtures";
import { wavescanMeasuredDate } from "../../src/features/measurements/wavescan-inspection";

const evidence = "test-results/film-layer-polish/evidence/T74";
const card = (page: Page, model: string, orient: string) =>
  page.getByRole("region", { name: `${model} ${orient}`, exact: true });
async function fixture(page: Page) {
  await mockHistory(page, "viewer");
  let wave = monthlyWaveFixture,
    film = monthlyFilmFixture;
  const reads: string[] = [],
    forbidden: string[] = [];
  await page.route("**/api/v1/**", (route) => {
    if (route.request().method() !== "GET") {
      forbidden.push(route.request().url());
      return route.abort();
    }
    return route.fallback();
  });
  await page.route("**/wavescan/overview**", (route) => {
    reads.push(route.request().url());
    return route.fulfill({ json: wave });
  });
  await page.route("**/filmthickness/overview**", (route) => {
    reads.push(route.request().url());
    return route.fulfill({ json: film });
  });
  return {
    reads,
    forbidden,
    updateWave: (data: typeof wave) => {
      wave = data;
    },
    updateFilm: (data: typeof film) => {
      film = data;
    },
  };
}
async function rowsMatch(
  panel: ReturnType<typeof card>,
  box: components["schemas"]["OverviewBox"],
) {
  await panel
    .locator("summary")
    .filter({ hasText: /^Below Minimum$/ })
    .click();
  const rows = panel.locator(".wavescan-reading-list li");
  await expect(rows).toHaveCount(box.below_minimum.length);
  for (const [index, reading] of box.below_minimum.entries()) {
    await expect(rows.nth(index)).toHaveText(
      `Measurement date${wavescanMeasuredDate(reading.measured_date)}Point / zone${reading.checkzone ?? "Zone unavailable"}CF value${reading.cf} CF`,
    );
  }
  if (!box.below_minimum.length) await expect(panel).toContainText("No readings below Minimum");
}

for (const width of [390, 768, 1440])
  for (const theme of ["light", "dark"]) {
    test(`T74 ${width} ${theme} hierarchy, exact duplicate/null readings and shared gaps`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.emulateMedia({ reducedMotion: theme === "light" ? "reduce" : "no-preference" });
      const { reads, forbidden } = await fixture(page);
      await page.goto("/plant/FTM");
      await page.evaluate(
        (t) => document.documentElement.classList.toggle("dark", t === "dark"),
        theme,
      );
      const h = card(page, "P703 DBL RAPTOR", "Horizontal"),
        v = card(page, "P703 DBL RAPTOR", "Vertical");
      await expect(h.getByRole("heading", { name: "Horizontal · CF" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "WaveScan", exact: true })).toBeVisible();
      await expect(page.locator(".wavescan-overview")).toContainText("September 2026 · CF");
      const target = h.locator("[data-wavescan-box]").first();
      const before = reads.length;
      await target.focus();
      await target.hover();
      await expect(h.locator(".wavescan-summary")).toHaveCount(0);
      await target.press("Enter");
      const summary = h.locator(".wavescan-summary");
      await expect(summary.locator(".wavescan-summary-primary > div")).toHaveCount(3);
      await expect(summary.getByRole("region", { name: "Published standard" })).toContainText(
        "Standard62 CFMinimum55 CF",
      );
      // T112: owner 2026-10-11 — WARNING reads Acceptable
      await expect(summary.locator("[data-wavescan-status]")).toHaveText("Acceptable");
      await rowsMatch(summary, monthlyWaveFixture.boxes[0]);
      await expect(summary.locator(".wavescan-reading-list")).not.toContainText("999001");
      await expect(summary.locator(".wavescan-reading-list")).not.toContainText("70 CF");
      await expect(summary.locator(".wavescan-reading-list")).not.toContainText("55 CF");
      await expect(summary.locator(".wavescan-reading-list")).not.toContainText("60 CF");
      await v.locator("[data-wavescan-box]").first().click();
      await expect(v.locator("[data-wavescan-status]")).toHaveText("Pass");
      await rowsMatch(v.locator(".wavescan-summary"), monthlyWaveFixture.boxes[2]);
      await expect(h.locator(".wavescan-summary")).toBeVisible();
      expect(reads.length).toBe(before);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: `${evidence}/wave-${width}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
      await summary.getByRole("button", { name: "Close detail" }).click();
      await expect(target).toBeFocused();
      await h.locator("[data-wavescan-box]").nth(1).click();
      await rowsMatch(h.locator(".wavescan-summary"), monthlyWaveFixture.boxes[1]);
      await expect(h.locator(".wavescan-published-standard")).toContainText("Not set");
      await page.goto("/plant/AAT?paint=film&filmMonth=2026-09");
      await page.evaluate(
        (t) => document.documentElement.classList.toggle("dark", t === "dark"),
        theme,
      );
      const fh = card(page, "P703 DBL RANGER", "Horizontal");
      await expect(fh.locator("[data-colour]")).toHaveCount(4);
      await fh
        .getByRole("button", {
          name: `${monthlyFilmFixture.color_sequence[3].color_name}; Horizontal summary`,
          exact: true,
        })
        .click();
      const fs = fh.getByRole("region", { name: "Box detail" });
      await expect(fs.locator(".film-summary-primary > div")).toHaveCount(3);
      await expect(fs.getByRole("region", { name: "Published standard" })).toContainText(
        "Minimum0 µm",
      );
      await expect(fs).toContainText("No Base standard for ordering");
      await expect(fs.locator(".film-status-badge")).toHaveText("Pass");
      expect((await page.locator(".film-coating-stack").boundingBox())!.height).toBeLessThan(90);
      await expect(page.getByRole("button", { name: "All colours", exact: true })).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: `${evidence}/film-${width}-${theme}.png`,
        fullPage: true,
        animations: "disabled",
      });
      expect(forbidden).toEqual([]);
    });
  }

test("T74 all plants/layers/models/HV use full ranks, repeated family runs and unchanged filter order", async ({
  page,
}) => {
  const { reads } = await fixture(page);
  for (const plant of ["AAT", "FTM", "FVL", "SAP"]) {
    await page.goto(`/plant/${plant}?paint=film&filmMonth=2026-09`);
    await expect(page.locator("[data-film-box]")).not.toHaveCount(0);
    await page.getByRole("button", { name: "Color", exact: true }).click();
    const filterNames = await page.locator("button[aria-pressed]").allTextContents();
    const optionNames = monthlyFilmFixture.color_options.map((e) => e.color_name);
    expect(filterNames.filter((n) => optionNames.includes(n))).toEqual(optionNames);
    await page.getByRole("button", { name: "Color", exact: true }).click();
    const before = reads.length;
    for (const [code, layer] of [
      ["ECOAT", "E-coat"],
      ["PRIMER", "Primer"],
      ["BASE", "Base"],
      ["CLEAR", "Clear"],
    ]) {
      await page.getByRole("tab", { name: layer, exact: true }).click();
      for (const model of monthlyFilmFixture.model_options)
        for (const orient of ["Horizontal", "Vertical"]) {
          const c = card(page, model, orient);
          // Only colours with a box in this layer/model/orientation get a slot, in rank order.
          const shown = monthlyFilmFixture.color_sequence.filter((entry) =>
            monthlyFilmFixture.boxes.some(
              (b) =>
                b.color_name === entry.color_name &&
                b.model_code === model &&
                b.orient === orient[0] &&
                b.layer_code === code,
            ),
          );
          expect(
            await c
              .locator("[data-colour]")
              .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-colour"))),
          ).toEqual(shown.map((entry) => entry.color_name));
          await expect(c.locator(".film-family-labels > span")).toHaveText(
            shown
              .map((entry) => entry.family_name ?? "No family assigned")
              .filter((name, i, all) => name !== all[i - 1]),
          );
          await expect(c.getByText(/No (Horizontal|Vertical) readings/)).toHaveCount(0);
          await expect(c.getByRole("heading")).toHaveText(`${orient} · µm`);
        }
      await expect(page.locator(".film-point")).toHaveCount(0);
    }
    expect(reads.length).toBe(before);
  }
});

test("T74 current membership replaces rows without stale IDs or motion replay; new ranks reset Film details", async ({
  page,
}) => {
  const data = await fixture(page);
  await page.goto("/plant/FTM");
  const c = card(page, "P703 DBL RAPTOR", "Horizontal");
  await c.locator("[data-wavescan-box]").first().click();
  await rowsMatch(c.locator(".wavescan-summary"), monthlyWaveFixture.boxes[0]);
  data.updateWave({
    ...monthlyWaveFixture,
    boxes: monthlyWaveFixture.boxes.map((b, i) =>
      i ? b : { ...b, below_minimum: [b.below_minimum[2]] },
    ),
  });
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect(c.locator(".wavescan-reading-list li")).toHaveCount(1);
  await expect(c.locator(".wavescan-reading-list")).toContainText("Date unavailable");
  expect(await c.locator(".wavescan-summary").evaluate((el) => el.getAnimations().length)).toBe(0);
  await page.goto("/plant/AAT?paint=film&filmMonth=2026-09");
  const f = card(page, "P703 DBL RANGER", "Horizontal");
  await f.locator(".film-colour-select").first().click();
  const sequence = [
    monthlyFilmFixture.color_sequence[1],
    monthlyFilmFixture.color_sequence[0],
    ...monthlyFilmFixture.color_sequence.slice(2),
  ].map((e, i) => ({ ...e, rank: i + 1 }));
  data.updateFilm({
    ...monthlyFilmFixture,
    color_sequence: sequence,
    boxes: monthlyFilmFixture.boxes.map((b) => ({
      ...b,
      color_rank: sequence.find((e) => e.color_name === b.color_name)!.rank,
    })),
  });
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect(f.locator("[data-colour]").first()).toHaveAttribute("data-colour", "Alpha");
  await expect(f.getByRole("region", { name: "Box detail" })).toHaveCount(0);
});

test("T74 standing GET-only readings and Film ladder match actual payloads", async ({ page }) => {
  const forbidden: string[] = [];
  await page.route("**/api/v1/**", (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    if (req.method() !== "GET" || /standards|history|vehicles|points|batches/.test(path)) {
      forbidden.push(req.url());
      return route.abort();
    }
    return route.continue();
  });
  for (const plant of ["FVL", "AAT", "FTM", "SAP"]) {
    const month = { FVL: "2026-09", AAT: "2026-09", FTM: "2026-08", SAP: "2026-08" }[plant];
    const response = await page.request.get(
      `http://localhost:8012/api/v1/plants/${plant}/wavescan/overview?month=${month}`,
    );
    expect(response.status()).toBe(200);
    const wave: components["schemas"]["WavescanOverviewOut"] = await response.json();
    writeFileSync(`${evidence}/live-${plant}-wave.json`, JSON.stringify(wave, null, 2));
    await page.goto(`/plant/${plant}`);
    await expect(page.locator("[data-wavescan-box]")).toHaveCount(wave.boxes.length);
    const selected =
      plant === "FVL"
        ? wave.boxes.filter(
            (b) =>
              (b.color_name === "Iconic Silver" && b.orient === "Horizontal") ||
              (b.color_name === "Pace Red" && b.orient === "Vertical"),
          )
        : [wave.boxes.find((b) => b.below_minimum.length)!];
    expect(selected.length).toBeGreaterThan(0);
    for (const box of selected) {
      const c = card(page, box.model_code, box.orient);
      await c
        .locator("[data-wavescan-box]")
        .filter({ has: page.locator("title", { hasText: `${box.color_name}:` }) })
        .click();
      const detail = c.locator(".wavescan-summary");
      await rowsMatch(detail, box);
      await expect(detail.locator("[data-wavescan-status]")).toHaveAttribute(
        "data-wavescan-status",
        box.status ?? "NONE",
      );
    }
    await page.screenshot({
      path: `${evidence}/live-${plant}-wave.png`,
      fullPage: true,
      animations: "disabled",
    });
    const fr = await page.request.get(
      `http://localhost:8012/api/v1/plants/${plant}/filmthickness/overview`,
    );
    expect(fr.status()).toBe(200);
    const film: components["schemas"]["FilmOverviewOut"] = await fr.json();
    writeFileSync(`${evidence}/live-${plant}-film.json`, JSON.stringify(film, null, 2));
    await page.goto(`/plant/${plant}?paint=film&filmMonth=${film.month}`);
    await expect(page.locator(".film-overview")).toContainText(
      "Colours follow current Base standards",
    );
    for (const [code, label] of [
      ["ECOAT", "E-coat"],
      ["PRIMER", "Primer"],
      ["BASE", "Base"],
      ["CLEAR", "Clear"],
    ]) {
      await page.getByRole("tab", { name: label, exact: true }).click();
      const boxes = film.boxes.filter((b) => b.layer_code === code);
      if (!boxes.length) {
        await expect(page.getByText("No readings for this layer.")).toBeVisible();
        continue;
      }
      for (const model of [...new Set(boxes.map((b) => b.model_code))])
        for (const orient of ["H", "V"]) {
          const c = card(page, model, orient === "H" ? "Horizontal" : "Vertical");
          const actual = boxes.filter((b) => b.model_code === model && b.orient === orient);
          if (!actual.length) continue;
          expect(
            await c
              .locator("[data-colour]")
              .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-colour"))),
          ).toEqual(
            film.color_sequence
              .filter((e) => actual.some((b) => b.color_name === e.color_name))
              .map((e) => e.color_name),
          );
          await expect(c.locator("[data-film-box]")).toHaveCount(actual.length);
          for (const box of actual)
            expect(box.color_rank).toBe(
              film.color_sequence.find((e) => e.color_name === box.color_name)!.rank,
            );
          if (plant === "SAP") {
            await c.locator(".film-colour-select").first().click();
            await expect(c.getByRole("region", { name: "Box detail" })).toContainText(
              "No Base standard for ordering",
            );
          }
        }
      await page.screenshot({
        path: `${evidence}/live-${plant}-film-${code}.png`,
        fullPage: true,
        animations: "disabled",
      });
    }
  }
  expect(forbidden).toEqual([]);
  writeFileSync(
    `${evidence}/live-guard.json`,
    JSON.stringify({ forbidden, methods: ["GET"], plants: ["FVL", "AAT", "FTM", "SAP"] }, null, 2),
  );
});
