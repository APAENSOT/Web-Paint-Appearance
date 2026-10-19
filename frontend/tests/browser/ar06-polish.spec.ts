/**
 * AR06 answer polish on the Analysis & Report tab, in a real browser, every API route mocked.
 * Pins: an answer shows its paragraph and an open graph with "Numbers and method" folded; the
 * chat runs oldest first with "You asked" bubbles; older turns fold and open on tap; a slot chip
 * answers its own turn; a typed month gives one "Showing:" divider; Clear chat empties the chat
 * but keeps added slides; the newest headline scrolls in and takes focus; a filter change asks
 * nothing again; a shift with no points shows its table; 390 px has no horizontal page scroll.
 * Set AR06_SHOTS=1 to also write test-results/screenshots/ar06-{desktop,390}.png.
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
const SUMMARY_HEAD = "Fix first: Ranger Desert Island Blue · Primer · V";
const CHANGES_HEAD = "2 boxes got worse since last month (1 real shift)";
const REPORT_HEAD = "1 of 2 colours needs action: Desert Island Blue (Primer)";
const MODEL_HEAD = "Raptor: Clear is the only failing layer (2 of 4 boxes)";
const PARAGRAPH =
  "Desert Island Blue Primer on the Ranger is the box to fix first: 9 of 34 readings fell under the low limit. The film is running thin, so the next cars will fail the same way.";

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

const base = (topic: string, headline: string, month = "2026-10"): AssistantAnswer => ({
  topic: topic as AssistantAnswer["topic"],
  month,
  previous_month: "2026-09",
  domain: "both",
  models: [],
  colors: [],
  status: "answer",
  decision: { status_code: "FAIL", headline },
  proof: "9 of 34 readings under the low limit",
  explanation: "",
  next_step: null,
  risk: null,
  confidence: "solid",
  evidence: empty,
  followups: [],
  method: { rule: "Rank boxes by readings out", n: 34, caveats: [] },
});

const summary = (): AssistantAnswer => ({
  ...base("summary", SUMMARY_HEAD),
  explanation: PARAGRAPH,
  next_step: "Check the Primer film build on Ranger Desert Island Blue",
  evidence: {
    ...empty,
    kind: "bar",
    columns: ["Box", "Status", "Out", "n"],
    rows: [
      ["Ranger Desert Island Blue · Primer · V", "Fail", 9, 34],
      ["Raptor Arctic White · Clear · H", "Fail", 5, 30],
      ["Ranger Arctic White · Base · V", "For Improvement", 2, 28],
    ],
  },
});

// A shift answer whose boxes were not measured in both months: no points to plot.
const changes = (): AssistantAnswer => ({
  ...base("changes", CHANGES_HEAD),
  explanation:
    "Two boxes got worse since September. One is a real shift, not day-to-day noise, so it needs a look first.",
  evidence: {
    ...empty,
    kind: "shift",
    columns: ["Box", "Before", "Now", "Change", "Verdict"],
    rows: [
      ["Ranger Desert Island Blue · Primer · V", "—", "Fail", "—", "New"],
      ["Raptor Arctic White · Clear · H", "—", "For Improvement", "—", "New"],
    ],
    points: [],
  },
});

const colourReport = (month: string): AssistantAnswer => ({
  ...base("colour_report", REPORT_HEAD, month),
  explanation:
    "Desert Island Blue is the one colour that needs action, on the Primer. Arctic White passes on every layer.",
  evidence: {
    ...empty,
    kind: "table",
    columns: ["Colour", "E-coat", "Primer"],
    rows: [
      ["Desert Island Blue", "Pass", "Fail"],
      ["Arctic White", "Pass", "Pass"],
    ],
  },
});

const modelSlot = (): AssistantAnswer => ({
  ...base("model_report", "Which model?"),
  decision: { status_code: null, headline: "Which model?" },
  status: "needs_slot",
  explanation: "",
  slot: {
    name: "model",
    prompt: "Which model?",
    choices: [RAPTOR, RANGER].map((value) => ({ value, label: value })),
  },
});

const modelReport = (): AssistantAnswer => ({
  ...base("model_report", MODEL_HEAD),
  explanation: "On the Raptor only the Clear fails: 2 of 4 boxes. The other layers hold.",
});

async function open(page: Page) {
  const asked: URL[] = [];
  await mockHistory(page, "viewer");
  // The filters default to October; September and August are older months.
  await page.route("**/api/v1/plants/*/analysis/report**", (r) =>
    r.fulfill({
      json: {
        ...report,
        month: new URL(r.request().url()).searchParams.get("month") ?? "2026-10",
        previous_month:
          new URL(r.request().url()).searchParams.get("month") === "2026-09"
            ? "2026-08"
            : "2026-09",
        options: {
          ...report.options,
          months: ["2026-10", "2026-09", "2026-08"],
          models: [RAPTOR, RANGER],
        },
      },
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
    const json =
      topic === "changes"
        ? changes()
        : topic === "colour_report"
          ? colourReport(p.get("month") ?? "2026-10")
          : topic === "model_report"
            ? p.get("model")
              ? modelReport()
              : modelSlot()
            : summary();
    return r.fulfill({ json: { ...json, month: p.get("month") ?? "2026-10" } });
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
const turns = (page: Page) => panel(page).locator("[data-turn]");
// Vite dev runs StrictMode, which aborts and repeats each first fetch: count distinct asks.
const distinct = (asked: URL[]) => new Set(asked.map((u) => u.search)).size;

async function pick(page: Page, name: string) {
  await panel(page).getByRole("button", { name: "Explore topics" }).click();
  await panel(page)
    .getByRole("navigation", { name: "What can I ask?" })
    .getByRole("button", { name, exact: true })
    .click();
}

async function typeAsk(page: Page, text: string) {
  await panel(page).getByLabel("Ask your report guide").fill(text);
  await panel(page).getByRole("button", { name: "Ask", exact: true }).click();
}

/** Three turns: the summary chart, the shift table, the colour report (newest, open). */
async function threeTurns(page: Page) {
  await pick(page, "Summarize this month");
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(SUMMARY_HEAD);
  await pick(page, "What changed since last month?");
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(CHANGES_HEAD);
  await pick(page, "Colour report");
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(REPORT_HEAD);
}

test("an answer shows its paragraph and an open graph; Numbers and method is folded", async ({
  page,
}) => {
  await open(page);
  await pick(page, "Summarize this month");
  const card = panel(page).locator('[data-answer="summary"]');
  await expect(card.locator("[data-headline]")).toHaveText(SUMMARY_HEAD);
  await expect(card.locator("[data-explanation]")).toHaveText(PARAGRAPH);
  await expect(card.locator(".guide-ranked-chart")).toBeVisible();
  await expect(card.locator(".guide-ranked-row")).toHaveCount(3);
  await expect(card.getByRole("heading", { name: "Where to focus" })).toBeVisible();
  await expect(card.locator(".guide-takeaway")).toContainText(
    "9 of 34 readings under the low limit",
  );
  await expect(card.locator(".guide-ranked-row").first()).toContainText("9 of 34 readings");
  const fold = card.locator("details", { hasText: "Numbers and method" });
  await expect(fold).not.toHaveAttribute("open");
  await expect(card.locator("[data-evidence-row]").first()).toBeHidden();
  await fold.locator("summary").click();
  await expect(card.locator("[data-evidence-row]")).toHaveCount(3);
  expect(await panel(page).innerText()).not.toContain("%");
});

test("typed choices complete their own question and avatar reflects real activity", async ({
  page,
}) => {
  await open(page);
  await pick(page, "Model report");
  await expect(turns(page).last().locator("[data-headline]")).toHaveText("Which model?");
  const input = panel(page).getByLabel("Ask your report guide");
  await input.fill("Raptor");
  await expect(page.locator(".report-companion")).toHaveAttribute("data-activity", "composing");
  await page.route("**/api/v1/plants/*/analysis/ask**", async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204 });
    await new Promise((resolve) => setTimeout(resolve, 700));
    return route.fulfill({ json: modelReport() });
  });
  await input.press("Enter");
  await expect(page.locator(".report-companion")).toHaveAttribute("data-activity", "checking");
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(MODEL_HEAD);
  await expect(page.locator(".report-companion")).toHaveAttribute("data-activity", "ready");
  await expect(turns(page)).toHaveCount(1);
});

test("topics start tucked away and Escape returns focus to the trigger", async ({ page }) => {
  await open(page);
  const trigger = panel(page).getByRole("button", { name: "Explore topics" });
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(trigger).toBeFocused();
});

test("turns stay readable oldest to newest with You asked bubbles", async ({ page }) => {
  await open(page);
  await threeTurns(page);
  await expect(turns(page)).toHaveCount(3);
  const said = await turns(page).locator("p", { hasText: "You asked" }).allInnerTexts();
  expect(said.map((s) => s.replace("You asked", "").trim())).toEqual([
    "Summarize this month",
    "What changed since last month?",
    "Colour report",
  ]);
  await expect(turns(page).nth(0).locator("[data-answer]")).toHaveAttribute(
    "data-answer",
    "summary",
  );
  await expect(turns(page).nth(2).locator("[data-answer]")).toHaveAttribute(
    "data-answer",
    "colour_report",
  );
  await expect(turns(page).nth(0).locator("[data-explanation]")).toHaveText(PARAGRAPH);
  await expect(turns(page).nth(1).locator("[data-headline]")).toHaveText(CHANGES_HEAD);
  await expect(turns(page).nth(2).locator("[data-headline]")).toHaveText(REPORT_HEAD);
  await expect(panel(page).getByRole("button", { name: /^Show answer:/ })).toHaveCount(0);
});

test("a slot chip answers its own turn: no orphan prompt is left", async ({ page }) => {
  const asked = await open(page);
  await pick(page, "Model report");
  await expect(turns(page).last().locator("[data-headline]")).toHaveText("Which model?");
  await panel(page).locator(`[data-choice="${RAPTOR}"]`).click();
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(MODEL_HEAD);
  await expect(turns(page)).toHaveCount(1);
  await expect(panel(page).getByText("Which model?")).toHaveCount(0);
  await expect(panel(page).locator("[data-choice]")).toHaveCount(0);
  await expect(turns(page).locator("p", { hasText: "You asked" })).toContainText(
    `Model report · ${RAPTOR}`,
  );
  expect(Object.fromEntries(asked.at(-1)!.searchParams)).toMatchObject({
    topic: "model_report",
    model: RAPTOR,
  });
});

test("a typed month gives exactly one Showing divider", async ({ page }) => {
  const asked = await open(page);
  await pick(page, "Summarize this month");
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(SUMMARY_HEAD);
  await typeAsk(page, "colour report for September");
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(REPORT_HEAD);
  expect(asked.at(-1)!.searchParams.get("month")).toBe("2026-09");
  const dividers = panel(page).getByText(/^Showing: /);
  await expect(dividers).toHaveCount(1);
  await expect(dividers).toHaveText("Showing: September 2026 · Wave Scan and Film");
  // It sits in the September turn, before its bubble.
  await expect(
    turns(page)
      .last()
      .getByText(/^Showing: /),
  ).toHaveCount(1);
});

test("Clear chat empties the turns, keeps the added slide, and the next question works", async ({
  page,
}) => {
  await open(page);
  await threeTurns(page);
  await turns(page).last().getByRole("button", { name: "Slides", exact: true }).click();
  await expect(panel(page).getByRole("button", { name: "Added to slides" })).toBeDisabled();
  await panel(page).getByRole("button", { name: "Clear chat" }).click();
  await expect(turns(page)).toHaveCount(0);
  await expect(panel(page).getByRole("button", { name: "Clear chat" })).toHaveCount(0);
  await expect(panel(page).getByLabel("Ask your report guide")).toBeFocused();
  await typeAsk(page, "what changed since last month");
  await expect(turns(page)).toHaveCount(1);
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(CHANGES_HEAD);
  // The slide added before the clear is still in the deck, once.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("analysis-export").click(),
  ]);
  const zip = await JSZip.loadAsync(readFileSync(await download.path()));
  const slides = Object.keys(zip.files).filter((f) => /^ppt\/slides\/slide\d+\.xml$/.test(f));
  const texts: string[] = await Promise.all(slides.map((f) => zip.file(f)!.async("string")));
  const title = `${REPORT_HEAD} — October 2026 :`;
  expect(texts.filter((t) => t.includes(`<a:t>${title}</a:t>`))).toHaveLength(1);
});

test("the newest headline scrolls into view and takes focus", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 700 });
  await open(page);
  await threeTurns(page);
  const head = turns(page).last().locator("[data-headline]");
  await expect(head).toBeFocused();
  await expect(head).toBeInViewport();
  await expect(panel(page).locator('p[aria-live="polite"]')).toHaveText(REPORT_HEAD);
});

test("390 px: the newest answer is scrolled in once it has loaded, not just its skeleton", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await threeTurns(page);
  const newest = turns(page).last();
  await expect(newest.locator("[data-headline]")).toBeInViewport();
  await expect(newest.locator("[data-explanation]")).toBeVisible();
});

test("typing the next question while an answer loads keeps every key in the input", async ({
  page,
}) => {
  await open(page);
  await page.route("**/api/v1/plants/*/analysis/ask**", async (r) => {
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 204 });
    await new Promise((done) => setTimeout(done, 1500));
    return r.fulfill({ json: changes() });
  });
  await typeAsk(page, "what changed since last month");
  const input = panel(page).getByLabel("Ask your report guide");
  await input.click();
  await page.keyboard.type("colour rep", { delay: 100 });
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(CHANGES_HEAD);
  await page.keyboard.type("ort");
  await expect(input).toHaveValue("colour report");
  await expect(input).toBeFocused();
});

test("changing month clears the conversation and draft without refetching old questions", async ({
  page,
}) => {
  const asked = await open(page);
  await threeTurns(page);
  await panel(page).getByLabel("Ask your report guide").fill("unfinished question");
  await page.waitForLoadState("networkidle");
  const total = asked.length;
  await page.getByLabel("Month", { exact: true }).selectOption("2026-09");
  await expect(turns(page)).toHaveCount(0);
  await expect(panel(page).getByLabel("Ask your report guide")).toHaveValue("");
  await page.waitForLoadState("networkidle");
  expect(asked.length).toBe(total);
  await typeAsk(page, "How are we doing?");
  await expect(turns(page)).toHaveCount(1);
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(SUMMARY_HEAD);
  expect(
    asked
      .filter((u) => u.searchParams.get("topic") === "summary")
      .at(-1)!
      .searchParams.get("month"),
  ).toBe("2026-09");
  await expect(panel(page).getByText(/^Showing: /)).toHaveCount(0);
});

test("a summary loads comparison evidence automatically without an extra user turn", async ({
  page,
}) => {
  const asked = await open(page);
  await typeAsk(page, "How are we doing?");
  const comparison = panel(page).getByTestId("supporting-comparison");
  await expect(comparison.getByRole("heading", { name: "Here’s what changed" })).toBeVisible();
  await expect(comparison).toContainText("Two boxes got worse");
  await expect(turns(page)).toHaveCount(1);
  expect(asked.some((u) => u.searchParams.get("topic") === "changes")).toBe(true);
});

test("a failed supporting comparison keeps the finding and retries locally", async ({ page }) => {
  await open(page);
  let failing = true;
  await page.route("**/api/v1/plants/*/analysis/ask**", (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204 });
    if (new URL(route.request().url()).searchParams.get("topic") !== "changes")
      return route.fulfill({ json: summary() });
    return failing
      ? route.fulfill({ status: 500, json: { detail: "Comparison unavailable" } })
      : route.fulfill({ json: changes() });
  });
  await typeAsk(page, "How are we doing?");
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(SUMMARY_HEAD);
  const retry = panel(page).getByRole("button", { name: "Retry month comparison" });
  await expect(retry).toBeVisible();
  failing = false;
  await retry.click();
  await expect(panel(page).getByTestId("supporting-comparison")).toContainText(
    "Two boxes got worse",
  );
  await expect(turns(page)).toHaveCount(1);
});

test("missing comparison data is explained without an empty graph", async ({ page }) => {
  await open(page);
  await page.route("**/api/v1/plants/*/analysis/ask**", (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204 });
    return route.fulfill({
      json:
        new URL(route.request().url()).searchParams.get("topic") === "changes"
          ? {
              ...base("changes", "No previous measurements"),
              status: "not_enough_data",
              explanation: "There are no measurements in the reference month for this selection.",
            }
          : summary(),
    });
  });
  await typeAsk(page, "How are we doing?");
  const comparison = panel(page).getByTestId("supporting-comparison");
  await expect(comparison).toContainText("no measurements in the reference month");
  await expect(comparison.locator('[role="img"]')).toHaveCount(0);
  await expect(turns(page).last().locator("[data-headline]")).toHaveText(SUMMARY_HEAD);
});

test("a late response cannot restore the previous month's cleared chat", async ({ page }) => {
  await open(page);
  let requested = false;
  await page.route("**/api/v1/plants/*/analysis/ask**", async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204 });
    requested = true;
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.fulfill({ json: summary() }).catch(() => {});
  });
  await typeAsk(page, "What should I check first?");
  await expect.poll(() => requested).toBe(true);
  await page.getByLabel("Month", { exact: true }).selectOption("2026-09");
  await expect(turns(page)).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  await expect(turns(page)).toHaveCount(0);
});

test("a shift with no plottable points shows its table, not an empty frame", async ({ page }) => {
  await open(page);
  await pick(page, "What changed since last month?");
  const card = panel(page).locator('[data-answer="changes"]');
  await expect(card.locator("[data-headline]")).toHaveText(CHANGES_HEAD);
  await expect(card.locator("[data-shift]")).toHaveCount(0);
  await expect(card.locator('[role="img"]')).toHaveCount(0);
  await expect(card.locator("[data-evidence-row]")).toHaveCount(2);
  await expect(card.locator("[data-evidence-row]").first()).toBeVisible();
});

test("390 px: no horizontal page scroll with three turns open and folded", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await threeTurns(page);
  await expect(turns(page).first().locator(".guide-ranked-chart")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("390 px: the question box stays on screen under the newest answer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await threeTurns(page);
  const input = panel(page).getByLabel("Ask your report guide");
  await expect(turns(page).last().locator("[data-headline]")).toBeInViewport();
  await expect(input).toBeInViewport();
  const [box, newest] = await Promise.all([input.boundingBox(), turns(page).last().boundingBox()]);
  expect(box!.y).toBeGreaterThan(newest!.y); // under the chat, not above it
});

test("screenshots: three turns, one a chart answer", async ({ page }) => {
  test.skip(!process.env.AR06_SHOTS, "set AR06_SHOTS=1 to write the AR06 screenshots");
  for (const [width, height, name] of [
    [1440, 1000, "desktop"],
    [390, 844, "390"],
  ] as const) {
    await page.setViewportSize({ width, height });
    await open(page);
    await pick(page, "What changed since last month?");
    await expect(turns(page).last().locator("[data-headline]")).toHaveText(CHANGES_HEAD);
    await pick(page, "Colour report");
    await expect(turns(page).last().locator("[data-headline]")).toHaveText(REPORT_HEAD);
    await pick(page, "Summarize this month");
    await expect(turns(page).last().locator(".guide-ranked-chart")).toBeVisible();
    await expect(turns(page).last().locator("[data-headline]")).toBeInViewport(); // smooth scroll done
    const shot = {
      path: `test-results/screenshots/AR07-chat-${name}.png`,
      animations: "disabled" as const,
    };
    // 390: what the phone screen shows (a stitched panel shot smears the sticky header and question box)
    await (name === "390" ? page.screenshot(shot) : panel(page).screenshot(shot));
  }
});
