/**
 * AR04 guided assistant on the Analysis & Report tab, in a real browser, every
 * API route mocked (AR05 labels: the menu comes from /analysis/questions). Pins: each
 * question gives a card with a headline; a
 * follow-up opens a targeted answer below (AR06: oldest first) and keeps the previous answer readable; a
 * month change keeps old cards as they are without asking again; typed Thai text asks
 * "colours"; "Slides" + Export puts the headline in the .pptx; 390 px has no
 * horizontal page scroll.
 */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { filmData, report, wsData } from "../ar03-fixtures";
import { QUESTIONS } from "../ar05-fixtures";
import type { AssistantAnswer } from "../../src/features/analysis/report-types";

const JSZip = createRequire(createRequire(import.meta.url).resolve("pptxgenjs"))("jszip");
const TOPICS = [
  ["Summarize this month", "summary"],
  ["Which colours to improve?", "colours"],
  ["Which points to improve?", "points"],
  ["What changed since last month?", "changes"],
  ["Is it trending?", "trend"],
  ["Which layer to check?", "bands"],
] as const;
const BOX = "film|PRIMER|P703 DBL RANGER|Arctic White|H";

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

// Vite dev runs StrictMode, which aborts and repeats each first fetch: count distinct asks.
const topicsAsked = (asked: URL[]) => [...new Set(asked.map((u) => u.searchParams.get("topic")))];

const headline = (topic: string, target: string | null) =>
  target ? `Trend answer for ${target}` : `Answer about ${topic}`;

const answer = (topic: string, target: string | null): AssistantAnswer => ({
  topic: topic as AssistantAnswer["topic"],
  month: "2026-09",
  previous_month: "2026-08",
  domain: "both",
  models: [],
  colors: [],
  status: "answer",
  decision: { status_code: "FAIL", headline: headline(topic, target) },
  proof: "9 of 34 readings out",
  explanation: "",
  next_step: "Check the Clear film build",
  risk: null,
  confidence: "solid",
  evidence: {
    kind: "bar",
    columns: ["Box", "Out"],
    rows: [["Box 1", 9]],
    series: [],
    limits: null,
    cells: [],
    groups: [],
    points: [],
    card: [],
  },
  followups: target ? [] : [{ label: "Trend for the worst box", topic: "trend", target: BOX }],
  method: { rule: "Rank boxes by severity", n: 12, caveats: [] },
});

async function open(page: Page) {
  const asked: URL[] = [];
  await mockHistory(page, "viewer");
  await page.route("**/api/v1/plants/*/analysis/report**", (r) => r.fulfill({ json: report }));
  await page.route("**/api/v1/plants/*/analysis/pairing", (r) => r.fulfill({ json: pairing }));
  await page.route("**/api/v1/plants/*/wavescan/overview**", (r) => r.fulfill({ json: wsData }));
  await page.route("**/api/v1/plants/*/filmthickness/overview**", (r) =>
    r.fulfill({ json: filmData }),
  );
  await page.route("**/api/v1/plants/*/analysis/questions", (r) => {
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 204 });
    return r.fulfill({ json: QUESTIONS });
  });
  await page.route("**/api/v1/plants/*/analysis/ask**", (r) => {
    // Cross-origin runs (live API base) also show the CORS preflight here.
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 204 });
    const u = new URL(r.request().url());
    asked.push(u);
    return r.fulfill({
      json: answer(u.searchParams.get("topic")!, u.searchParams.get("target")),
    });
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

test("each of the six buttons shows a card with a headline", async ({ page }) => {
  const asked = await open(page);
  for (const [label, topic] of TOPICS) {
    await page.getByTestId("assistant").getByRole("button", { name: "Explore topics" }).click();
    await page.getByTestId("assistant").getByRole("button", { name: label, exact: true }).click();
    await expect(page.locator(`[data-answer="${topic}"] [data-headline]`)).toHaveText(
      headline(topic, null),
    );
  }
  expect(topicsAsked(asked).sort()).toEqual(TOPICS.map((t) => t[1]).sort());
  expect(await page.getByTestId("assistant").innerText()).not.toContain("%");
});

test("a follow-up opens a targeted answer below and keeps the previous answer readable", async ({
  page,
}) => {
  const asked = await open(page);
  const panel = page.getByTestId("assistant");
  if (
    (await panel.getByRole("button", { name: "Explore topics" }).getAttribute("aria-expanded")) ===
    "false"
  )
    await panel.getByRole("button", { name: "Explore topics" }).click();
  await panel.getByRole("button", { name: "Summarize this month", exact: true }).click();
  await panel.getByRole("button", { name: "Trend for the worst box" }).click();
  await expect(asked.at(-1)!.searchParams.get("target")).toBe(BOX);
  const cards = panel.locator("[data-answer]");
  // AR06: the chat runs oldest first, so the follow-up is the last card.
  await expect(cards.last()).toHaveAttribute("data-answer", "trend");
  await expect(cards.last().locator("[data-headline]")).toHaveText(headline("trend", BOX));
  await expect(cards.first().locator("[data-headline]")).toHaveText(headline("summary", null));
});

test("changing Month clears the older conversation and asks nothing new", async ({ page }) => {
  const asked = await open(page);
  await page.getByTestId("assistant").getByRole("button", { name: "Explore topics" }).click();
  await page
    .getByTestId("assistant")
    .getByRole("button", { name: "Which colours to improve?", exact: true })
    .click();
  await expect(page.locator('[data-answer="colours"] [data-headline]')).toBeVisible();
  const before = asked.length;
  await page.locator("select").filter({ hasText: "August" }).first().selectOption("2026-08");
  await expect(page.getByTestId("assistant").locator("[data-turn]")).toHaveCount(0);
  await expect(page.locator("[data-stale]")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  expect(asked.length).toBe(before);
});

test("typed Thai text asks colours", async ({ page }) => {
  const asked = await open(page);
  const panel = page.getByTestId("assistant");
  await panel.getByLabel("Ask your report guide").fill("สี");
  await panel.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.locator('[data-answer="colours"] [data-headline]')).toBeVisible();
  expect(topicsAsked(asked)).toEqual(["colours"]);
});

test("Slides then Export puts the answer headline in the .pptx", async ({ page }) => {
  await open(page);
  await page.getByTestId("assistant").getByRole("button", { name: "Explore topics" }).click();
  await page
    .getByTestId("assistant")
    .getByRole("button", { name: "Summarize this month", exact: true })
    .click();
  await page.getByRole("button", { name: "Slides", exact: true }).click();
  await expect(page.getByRole("button", { name: "Added to slides" })).toBeDisabled();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("analysis-export").click(),
  ]);
  const zip = await JSZip.loadAsync(readFileSync(await download.path()));
  const slides = Object.keys(zip.files).filter((f) => /^ppt\/slides\/slide\d+\.xml$/.test(f));
  const texts: string[] = await Promise.all(slides.map((f) => zip.file(f)!.async("string")));
  // The slide title is its own text run: "<headline> — <Month YYYY> :" (the notes layout's title).
  const title = `${headline("summary", null)} — September 2026 :`;
  expect(texts.filter((t) => t.includes(`<a:t>${title}</a:t>`))).toHaveLength(1);
});

test("390 px: no horizontal page scroll with cards open", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await open(page);
  const panel = page.getByTestId("assistant");
  // Below 1024 px the menu is a sheet behind "What can I ask?".
  await panel.getByRole("button", { name: "Explore topics" }).click();
  if (
    (await panel.getByRole("button", { name: "Explore topics" }).getAttribute("aria-expanded")) ===
    "false"
  )
    await panel.getByRole("button", { name: "Explore topics" }).click();
  await panel.getByRole("button", { name: "Summarize this month", exact: true }).click();
  await panel.getByRole("button", { name: "Trend for the worst box" }).click();
  await expect(panel.locator("[data-answer]").last()).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
