/**
 * AR05 question catalog on the Analysis & Report tab, in a real browser, every API route
 * mocked. Pins: the menu lists 6 groups and 32 questions; "Compare models" asks for two models
 * and a layer with chips and ends in a box-plot pair; typed Thai fills the compare details;
 * the colour report shows status words; a follow-up opens a targeted answer; Slides + Export
 * puts the headline in the .pptx; 390 px has no horizontal page scroll.
 */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { filmData, report, wsData } from "../ar03-fixtures";
import { QUESTIONS } from "../ar05-fixtures";
import type { AssistantAnswer } from "../../src/features/analysis/report-types";

const JSZip = createRequire(createRequire(import.meta.url).resolve("pptxgenjs"))("jszip");
const RAPTOR = "P703 DBL RAPTOR";
const RANGER = "P703 DBL RANGER";
const WHY = "film|PRIMER|P703 DBL RANGER|Desert Island Blue|V";
const REPORT_HEAD = "3 of 4 colours need action; start with Desert Island Blue (Primer)";

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

const empty = {
  kind: null,
  columns: [] as string[],
  rows: [] as (string | number | null)[][],
  series: [],
  limits: null,
  cells: [],
  groups: [],
  points: [],
  card: [],
};

const base = (topic: string, headline: string, status_code: string | null = "FAIL") => ({
  topic: topic as AssistantAnswer["topic"],
  month: "2026-09",
  previous_month: "2026-08",
  domain: "both" as const,
  models: [],
  colors: [],
  status: "answer" as const,
  decision: { status_code, headline },
  proof: "",
  explanation: "",
  next_step: null,
  risk: null,
  confidence: "solid",
  evidence: empty,
  followups: [],
  method: { rule: "Fixed rule", n: 8, caveats: [] },
});

const chips = (topic: string, name: string, prompt: string, values: string[]): AssistantAnswer => ({
  ...base(topic, prompt, null),
  status: "needs_slot",
  slot: { name, prompt, choices: values.map((value) => ({ value, label: value })) },
});

const cell = (status_code: string, word: string, note = "") => ({
  status_code,
  word,
  note,
  arrow: "",
});

const colourReport = (): AssistantAnswer => ({
  ...base("colour_report", REPORT_HEAD),
  proof: "Desert Island Blue Primer: Fail on RANGER V",
  evidence: {
    ...empty,
    kind: "heatmap",
    columns: ["Colour", "E-coat", "Primer", "Base", "Clear", "CF"],
    rows: [
      ["Desert Island Blue", "Pass", "Fail · RANGER V", "Over · RANGER V", "For Improvement", "—"],
      ["Arctic White", "Pass", "Pass", "Pass", "Pass", "—"],
    ],
    cells: [
      [
        cell("PASS", "Pass"),
        cell("FAIL", "Fail", "RANGER V"),
        cell("OVER", "Over", "RANGER V"),
        cell("WARNING", "For Improvement", "RANGER H"),
        cell("", "—"),
      ],
      [
        cell("PASS", "Pass"),
        cell("PASS", "Pass"),
        cell("PASS", "Pass"),
        cell("PASS", "Pass"),
        cell("", "—"),
      ],
    ],
  },
  followups: [
    { label: "Why is it failing?", topic: "why_failing", target: WHY },
    { label: "Model report", topic: "model_report", target: RANGER },
  ],
});

const group = (label: string, median: number) => ({
  label,
  n: 40,
  q1: median - 2,
  median,
  q3: median + 2,
  low: median - 5,
  high: median + 5,
  mean: median + 0.4,
});

const comparePair = (): AssistantAnswer => ({
  ...base("compare_models", "Raptor is 4.1 µm thinner on Clear than Ranger: a real difference"),
  proof: "Medians 36.0 and 40.1 µm, 40 readings each",
  evidence: {
    ...empty,
    kind: "boxplot_pair",
    columns: ["Model", "n", "Median"],
    rows: [
      ["RAPTOR", 40, 36.0],
      ["RANGER", 40, 40.1],
    ],
    limits: { lo: 40, hi: null },
    groups: [group("RAPTOR", 36), group("RANGER", 40.1)],
  },
});

const whyAnswer = (): AssistantAnswer => ({
  ...base("why_failing", "Desert Island Blue Primer V fails on thin film"),
  proof: "9 of 34 readings under Lo",
});

const summary = (): AssistantAnswer => ({
  ...base("summary", "Fix first: Ranger Desert Island Blue · Primer · V"),
  proof: "9 of 34 readings out",
});

async function open(page: Page) {
  const asked: URL[] = [];
  await mockHistory(page, "viewer");
  await page.route("**/api/v1/plants/*/analysis/report**", (r) =>
    r.fulfill({
      json: { ...report, options: { ...report.options, models: [RAPTOR, RANGER] } },
    }),
  );
  await page.route("**/api/v1/plants/*/analysis/pairing", (r) => r.fulfill({ json: pairing }));
  await page.route("**/api/v1/plants/*/wavescan/overview**", (r) => r.fulfill({ json: wsData }));
  await page.route("**/api/v1/plants/*/filmthickness/overview**", (r) =>
    r.fulfill({ json: filmData }),
  );
  await page.route("**/api/v1/plants/*/analysis/questions", (r) => {
    // Cross-origin runs (live API base) also show the CORS preflight here.
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 204 });
    return r.fulfill({ json: QUESTIONS });
  });
  await page.route("**/api/v1/plants/*/analysis/ask**", (r) => {
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 204 });
    const u = new URL(r.request().url());
    asked.push(u);
    const p = u.searchParams;
    const topic = p.get("topic");
    if (topic === "compare_models") {
      if (!p.get("a"))
        return r.fulfill({ json: chips(topic, "a", "Which two models?", [RAPTOR, RANGER]) });
      if (!p.get("b"))
        return r.fulfill({
          json: chips(
            topic,
            "b",
            "Which model to compare with?",
            [RAPTOR, RANGER].filter((m) => m !== p.get("a")),
          ),
        });
      if (!p.get("metric"))
        return r.fulfill({
          json: chips(topic, "metric", "Which layer or Wave Scan metric?", [
            "PRIMER",
            "CLEAR",
            "cf",
          ]),
        });
      return r.fulfill({ json: comparePair() });
    }
    const make = { colour_report: colourReport, why_failing: whyAnswer, summary }[topic ?? ""];
    return r.fulfill({ json: (make ?? summary)() });
  });
  await page.goto("/plant/FTM");
  // The shell moves the tabs behind "Views & filters" on a phone.
  const tab = page.getByRole("button", { name: "Analysis & Report" }).first();
  if ((page.viewportSize()?.width ?? 1440) < 768)
    await page.getByRole("button", { name: "Views & filters" }).click();
  await tab.click();
  await expect(page.getByTestId("analysis-workspace")).toBeVisible();
  await page.locator('[data-testid="full-data"] > summary').click();
  return asked;
}

const panel = (page: Page) => page.getByTestId("assistant");
const lastAsk = (asked: URL[]) => Object.fromEntries(asked.at(-1)!.searchParams);

test("the menu lists 6 groups and 32 questions", async ({ page }) => {
  await open(page);
  await panel(page).getByRole("button", { name: "Explore topics" }).click();
  const menu = panel(page).getByRole("navigation", { name: "What can I ask?" });
  await expect(menu.getByRole("region")).toHaveCount(6);
  await expect(menu.locator("[data-question]")).toHaveCount(32);
});

test("Compare models: chips for two models and a layer end in a box-plot pair", async ({
  page,
}) => {
  const asked = await open(page);
  await panel(page).getByRole("button", { name: "Explore topics" }).click();
  await panel(page).getByRole("button", { name: "Compare models", exact: true }).click();
  await expect(page.locator("[data-answer] [data-headline]").first()).toHaveText(
    "Which two models?",
  );
  await panel(page).locator(`[data-choice="${RAPTOR}"]`).click();
  await panel(page).locator(`[data-choice="${RANGER}"]`).click();
  await panel(page).locator('[data-choice="CLEAR"]').click();
  const card = panel(page).locator('[data-answer="compare_models"]').first();
  await expect(card.locator("[data-headline]")).toContainText("Raptor is 4.1 µm thinner");
  expect(lastAsk(asked)).toMatchObject({
    topic: "compare_models",
    a: RAPTOR,
    b: RANGER,
    metric: "CLEAR",
  });
  // AR06: the graph is open, no fold.
  await expect(card.locator("[data-box]")).toHaveCount(2);
  expect(await panel(page).innerText()).not.toContain("%");
});

test("typed Thai compare fills the models and the layer", async ({ page }) => {
  const asked = await open(page);
  await panel(page).getByLabel("Ask your report guide").fill("เทียบรุ่น Raptor กับ Ranger Clear");
  await expect(panel(page).locator("#assistant-guess")).toContainText("Compare models");
  await panel(page).getByRole("button", { name: "Ask", exact: true }).click();
  await expect(panel(page).locator('[data-answer="compare_models"] [data-headline]')).toContainText(
    "Raptor is 4.1 µm thinner",
  );
  expect(lastAsk(asked)).toMatchObject({
    topic: "compare_models",
    a: RAPTOR,
    b: RANGER,
    metric: "CLEAR",
  });
});

test("colour report: heat-map cells show status words; a follow-up opens a targeted answer", async ({
  page,
}) => {
  const asked = await open(page);
  await panel(page).getByRole("button", { name: "Explore topics" }).click();
  await panel(page).getByRole("button", { name: "Colour report", exact: true }).click();
  const card = panel(page).locator('[data-answer="colour_report"]').first();
  await expect(card.locator("[data-headline]")).toHaveText(REPORT_HEAD);
  const grid = card.getByRole("table").first();
  for (const word of ["Pass", "Fail", "Over", "For Improvement"])
    await expect(grid.getByText(word, { exact: true }).first()).toBeVisible();
  await card.getByRole("button", { name: "Why is it failing?" }).click();
  expect(lastAsk(asked)).toMatchObject({ topic: "why_failing", target: WHY });
  await expect(panel(page).locator('[data-answer="why_failing"] [data-headline]')).toHaveText(
    "Desert Island Blue Primer V fails on thin film",
  );
  await expect(card.locator("[data-headline]")).toHaveText(REPORT_HEAD);
});

test("Slides then Export puts the colour report headline in the .pptx", async ({ page }) => {
  await open(page);
  await panel(page).getByRole("button", { name: "Explore topics" }).click();
  await panel(page).getByRole("button", { name: "Colour report", exact: true }).click();
  await page.getByRole("button", { name: "Slides", exact: true }).click();
  await expect(page.getByRole("button", { name: "Added to slides" })).toBeDisabled();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("analysis-export").click(),
  ]);
  const zip = await JSZip.loadAsync(readFileSync(await download.path()));
  const slides = Object.keys(zip.files).filter((f) => /^ppt\/slides\/slide\d+\.xml$/.test(f));
  const texts: string[] = await Promise.all(slides.map((f) => zip.file(f)!.async("string")));
  const title = `${REPORT_HEAD} — September 2026 :`;
  expect(texts.filter((t) => t.includes(`<a:t>${title}</a:t>`))).toHaveLength(1);
});

test("390 px: no horizontal page scroll with a heat map and a box-plot pair open", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await open(page);
  const p = panel(page);
  const pick = async (name: string) => {
    await p.getByRole("button", { name: "Explore topics" }).click();
    await p.getByRole("button", { name, exact: true }).click();
  };
  await pick("Colour report");
  const heat = p.locator('[data-answer="colour_report"]').first();
  await expect(heat.locator("[data-headline]")).toBeVisible();
  await pick("Compare models");
  await p.locator(`[data-choice="${RAPTOR}"]`).click();
  await p.locator(`[data-choice="${RANGER}"]`).click();
  await p.locator('[data-choice="CLEAR"]').click();
  const pair = p.locator('[data-answer="compare_models"]').first();
  await expect(pair.locator("[data-headline]")).toContainText("Raptor is 4.1");
  await expect(pair.locator("[data-box]")).toHaveCount(2);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
