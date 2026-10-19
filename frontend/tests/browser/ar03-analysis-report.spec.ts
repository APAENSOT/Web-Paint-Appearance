/**
 * AR03 Analysis & Report tab, in a real browser, every API route mocked.
 * Pins: the workspace renders in the tab and its toggles work; Export
 * downloads a .pptx whose slides carry the planned titles; 390 px has no
 * horizontal page scroll. Screenshots go to test-results/screenshots.
 */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { filmData, report, wsData } from "../ar03-fixtures";

const SHOTS = "test-results/screenshots";
// jszip is pptxgenjs's own dependency; resolve it from there (pnpm keeps it private).
const JSZip = createRequire(createRequire(import.meta.url).resolve("pptxgenjs"))("jszip");

const pairing = {
  plant_code: "FTM",
  car_rule: null,
  wavescan_cars: 1,
  film_cars: 0,
  paired_cars: 0,
  by_model_colour: [],
  by_pair_group: [],
  pairs: [],
  quality: [],
};

async function open(page: Page) {
  await mockHistory(page, "viewer");
  await page.route("**/api/v1/plants/*/analysis/report**", (r) => r.fulfill({ json: report }));
  await page.route("**/api/v1/plants/*/analysis/pairing", (r) => r.fulfill({ json: pairing }));
  await page.route("**/api/v1/plants/*/wavescan/overview**", (r) => r.fulfill({ json: wsData }));
  await page.route("**/api/v1/plants/*/filmthickness/overview**", (r) =>
    r.fulfill({ json: filmData }),
  );
  await page.goto("/plant/FTM");
  // The shell moves the tabs behind "Views & filters" on a phone.
  const tab = page.getByRole("button", { name: "Analysis & Report" }).first();
  if ((page.viewportSize()?.width ?? 1440) < 768)
    await page.getByRole("button", { name: "Views & filters" }).click();
  await tab.click();
  await expect(page.getByTestId("analysis-workspace")).toBeVisible();
}

test("the page leads with the problems and opens the Monthly Overview chart", async ({ page }) => {
  await open(page);
  for (const id of [
    "glance",
    "issues",
    "summary",
    "comparison",
    "bands",
    "relationships",
    "slides",
  ])
    await expect(page.locator(`[data-section="${id}"]`)).toHaveCount(1);
  // The most serious group is open, showing the dashboard's own Film chart.
  await page.locator('[data-testid="full-data"] > summary').click();
  const first = page.locator("[data-problem]").first();
  await expect(first).toHaveAttribute("data-problem", "film|P703 DBL RANGER|PRIMER");
  await expect(first.locator(".film-orientation-panel svg.recharts-surface").first()).toBeVisible();
  // The Wave Scan group opens onto the Wave Scan Monthly Overview chart.
  const wsGroup = page.locator('[data-problem="wavescan|P703 DBL RANGER|"]');
  await wsGroup.locator("summary").first().click();
  await expect(wsGroup.locator(".wavescan-overview svg.recharts-surface").first()).toBeVisible();
  const text = await page.getByTestId("analysis-workspace").innerText();
  expect(text).not.toContain("%");
  expect(text).not.toMatch(/Warning/i);
  await page.screenshot({ path: `${SHOTS}/ar03-analysis-desktop.png`, fullPage: true });
});

test("Export downloads a .pptx with the planned slides", async ({ page }) => {
  await open(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("analysis-export").click(),
  ]);
  expect(download.suggestedFilename()).toBe("FTM-quality-report-2026-09.pptx");
  const zip = await JSZip.loadAsync(readFileSync(await download.path()));
  const slides = Object.keys(zip.files)
    .filter((f) => /^ppt\/slides\/slide\d+\.xml$/.test(f))
    .sort((a, b) => Number(a.match(/\d+/)![0]) - Number(b.match(/\d+/)![0]));
  const texts: string[] = await Promise.all(slides.map((f) => zip.file(f)!.async("string")));
  const titles = [
    "FTM Paint Quality Sep 2026",
    "FTM P703 DBL RANGER Wave Scan CF – Sep&apos;26",
    "FTM Wave Scan bands – Sep&apos;26",
    "FTM P703 DBL RANGER Primer FB – Sep&apos;26",
    "FTM P703 DBL RANGER Clear FB – Sep&apos;26",
    "FTM Relationships – Sep&apos;26",
    "Observation &amp; Summary :",
    "Observation &amp; Summary :",
  ];
  expect(slides).toHaveLength(titles.length);
  titles.forEach((t, i) => expect(texts[i]).toContain(t));
  expect(texts.join("")).not.toContain("%");
  // The reference template: Arial Nova, the Ford oval on every slide, the "Secret" label.
  expect(texts.every((t) => t.includes("Secret") && t.includes('typeface="Arial Nova"'))).toBe(
    true,
  );
  // Model slides carry the captured overview cards: logos plus at least one chart per slide.
  expect(Object.keys(zip.files).filter((f) => f.startsWith("ppt/media/")).length).toBeGreaterThan(
    5,
  );
});

test("slide choices change the deck", async ({ page }) => {
  await open(page);
  await page.locator('[data-toggle="bands"]').uncheck();
  await page.locator('[data-toggle="relationships"]').uncheck();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("analysis-export").click(),
  ]);
  const zip = await JSZip.loadAsync(readFileSync(await download.path()));
  expect(Object.keys(zip.files).filter((f) => /^ppt\/slides\/slide\d+\.xml$/.test(f))).toHaveLength(
    6,
  );
  await expect(page.locator('[data-section="bands"]')).toHaveCount(1);
});

test("390 px: no horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await open(page);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: `${SHOTS}/ar03-analysis-390.png`, fullPage: true });
});
