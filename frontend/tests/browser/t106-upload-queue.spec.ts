/**
 * T106 in a real browser: Upload Data takes several files, one request each.
 *
 * The owner asked to attach a whole folder of plant files at once. One
 * request for the lot was all-or-nothing: a single duplicate answered 409 and
 * nothing at all was stored (`services/ingest.py`). So the screen now sends
 * **one request per file, in order** (D-106-2) and keeps a queue under the
 * input with each file's own state and the server's own sentence (D-106-3).
 *
 * Nothing is answered or loaded here. The first file needing attention opens
 * its review (D-106-4); the rest wait behind *Next file needing attention*.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { cleanReview } from "../fixtures";
import { mockHistory } from "../history-fixtures";
import { workbookFixture } from "../workbook-fixtures";

type Workbook = components["schemas"]["WorkbookOut"];

const chosen = [
  { name: "one.xlsx", hash: "1".repeat(64), loadId: 2001 },
  { name: "two.xlsx", hash: "2".repeat(64), loadId: 2002 },
  { name: "three.xlsx", hash: "3".repeat(64), loadId: 2003 },
];
const mimeType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

const bookOf = (index: number, status: string): Workbook => ({
  ...workbookFixture,
  plant_code: "FTM",
  source_file: chosen[index].name,
  file_hash: chosen[index].hash,
  sheets: [
    {
      ...workbookFixture.sheets[0],
      batch: {
        ...workbookFixture.sheets[0].batch,
        load_id: chosen[index].loadId,
        file_hash: chosen[index].hash,
        plant_code: "FTM",
        source_file: chosen[index].name,
        source_sheet: "PasteData",
        status: status as Workbook["sheets"][number]["batch"]["status"],
      },
    },
  ],
});

const worksheetOf = (index: number): components["schemas"]["WorksheetOut"] => ({
  plant_code: "FTM",
  file_hash: chosen[index].hash,
  source_file: chosen[index].name,
  plant_question: null,
  extra_columns: [],
  missing_optional: [],
  missing_optional_message: null,
  ready_sheet_count: 1,
  rows_ready: 4,
  rows_held: 0,
  rows_already_in_history: 0,
  rows_need_confirmation: 0,
  summary_message: "4 readings ready to add.",
  checklist: [],
  load_button_label: "Yes, load these rows",
  sheets: [
    {
      load_id: chosen[index].loadId,
      sheet: "PasteData",
      status: "PENDING_REVIEW",
      state: "ready",
      commit_blockers: [],
      rows_ready: 4,
      rows_loaded: 0,
      rows_held: 0,
      rows_already_in_history: 0,
      rows_need_confirmation: 0,
      rows: [
        {
          source_sheet: "PasteData",
          film_tail: false,
          source_row: 2,
          panel_label: "12LCPILLAR",
          checkzone: "LCPILLAR",
          model_text: "Ranger",
          model: "P703 DBL RANGER",
          color_text: "Arctic White",
          color: "Arctic White",
          date_text: "8 September 2026",
          measured_date: "2026-09-08",
          outcome: "ready",
          operator_message: "Ready to add.",
        },
      ],
      extra_columns: [],
      missing_optional: [],
      hole_rows: [],
      plant_texts: [],
      held: [],
      vehicle_count: 1,
      short_vehicles: [],
      operator_message: "Four rows can load.",
    },
  ],
});

const duplicateMessage = `"${chosen[1].name}" has already been ingested: its SHA-256 matches load_id ${chosen[1].loadId} (${chosen[1].name} [PasteData], PENDING_REVIEW). Nothing was stored. A corrected re-send must be a different file; identical bytes are the same evidence.`;

/**
 * `statuses[i]` is what the server says about the i-th chosen file: a batch
 * status it accepts, or 409 for the duplicate that must not touch the others.
 */
async function setup(page: Page, statuses: (string | 409)[], inbox: Workbook[] = []) {
  const posts: { filename: string; files: number; plant: string | null }[] = [];
  const commits: string[] = [];
  await mockHistory(page, "admin");
  await page.route("**/api/v1/plants/FTM/workbooks?*", (route) =>
    route.fulfill({
      json: {
        plant_code: "FTM",
        plant_is_active: true,
        inbox: "all",
        uploaded_month: null,
        items: inbox,
        page: { offset: 0, limit: 200, total: inbox.length, returned: inbox.length },
      },
    }),
  );
  await page.route("**/api/v1/uploads", (route) => {
    const body = route.request().postDataBuffer()?.toString() ?? "";
    const names = [...body.matchAll(/filename="([^"]+)"/g)].map((match) => match[1]);
    const plant = body.match(/name="expected_plant"\r\n\r\n([A-Z]+)/);
    const index = chosen.findIndex((file) => file.name === names[0]);
    posts.push({
      filename: names[0] ?? "",
      files: [...body.matchAll(/name="files"/g)].length,
      plant: plant ? plant[1] : null,
    });
    const status = statuses[index];
    if (status === 409)
      return route.fulfill({
        status: 409,
        json: {
          statusCode: 409,
          error: "Conflict",
          message: duplicateMessage,
          correlationId: "t106-duplicate",
        },
      });
    return route.fulfill({
      status: 202,
      json: {
        batches: [
          {
            load_id: chosen[index].loadId,
            filename: chosen[index].name,
            sheet: "PasteData",
            status,
            detail: "Queued",
          },
        ],
      },
    });
  });
  for (const [index, file] of chosen.entries()) {
    const status = statuses[index];
    const book = bookOf(index, status === 409 ? "PENDING_REVIEW" : status);
    await page.route(`**/api/v1/batches/${file.loadId}`, (route) =>
      route.fulfill({ json: { ...cleanReview, batch: book.sheets[0].batch, held_labels: [] } }),
    );
    await page.route(`**/workbooks/${file.hash}`, (route) =>
      route.fulfill({
        json: { workbook: book, profiles: [], possible_replacements: [], acknowledgements: [] },
      }),
    );
    await page.route(`**/workbooks/${file.hash}/worksheet`, (route) =>
      route.fulfill({ json: worksheetOf(index) }),
    );
  }
  await page.route("**/batches/*/commit", (route) => {
    commits.push(route.request().url());
    return route.fulfill({ json: { load_id: 0, status: "COMMITTED", measurements_inserted: 0 } });
  });
  await page.goto("/plant/ftm?dataView=upload");
  return { posts, commits };
}

const attach = (page: Page) =>
  page.getByLabel("Attach workbook", { exact: true }).setInputFiles(
    chosen.map((file) => ({
      name: file.name,
      mimeType,
      buffer: Buffer.from(`bytes of ${file.name}`),
    })),
  );

test("three chosen files are three requests, in order, one file each", async ({ page }) => {
  const { posts, commits } = await setup(page, ["COMMITTED", "COMMITTED", "COMMITTED"]);
  await attach(page);
  const queue = page.getByRole("region", { name: "Chosen files" });
  await expect(queue.getByRole("listitem")).toHaveCount(3);
  await expect.poll(() => posts.length).toBe(3);
  expect(posts.map((post) => post.filename)).toEqual(["one.xlsx", "two.xlsx", "three.xlsx"]);
  expect(posts.map((post) => post.files)).toEqual([1, 1, 1]);
  expect(posts.map((post) => post.plant)).toEqual(["FTM", "FTM", "FTM"]);
  for (const file of chosen)
    await expect(queue.getByRole("listitem").filter({ hasText: file.name })).toHaveCount(1);
  await expect(queue.getByText("Already current")).toHaveCount(3);
  expect(commits).toEqual([]);
});

test("a duplicate file answers 409 alone; the files around it still upload", async ({ page }) => {
  const { posts } = await setup(
    page,
    ["COMMITTED", 409, "COMMITTED"],
    [bookOf(1, "PENDING_REVIEW")],
  );
  await attach(page);
  const queue = page.getByRole("region", { name: "Chosen files" });
  const second = queue.getByRole("listitem").filter({ hasText: "two.xlsx" });
  await expect(second.getByText("Already uploaded")).toBeVisible();
  await expect(second.getByText(/SHA-256 matches load_id 2002/)).toBeVisible();
  await expect(second.getByText("Correlation id t106-duplicate")).toBeVisible();
  await expect(second.getByRole("button", { name: "Open the stored workbook" })).toBeVisible();
  await expect
    .poll(() => posts.map((post) => post.filename))
    .toEqual(["one.xlsx", "two.xlsx", "three.xlsx"]);
  for (const name of ["one.xlsx", "three.xlsx"])
    await expect(
      queue.getByRole("listitem").filter({ hasText: name }).getByText("Already current"),
    ).toBeVisible();
});

test("the first file needing attention opens; the next one waits for a click", async ({ page }) => {
  const { commits } = await setup(page, ["PENDING_REVIEW", "COMMITTED", "PENDING_REVIEW"]);
  await attach(page);
  const review = page.getByRole("dialog").first();
  await expect(review.getByRole("heading", { name: "one.xlsx" })).toBeVisible();
  await expect.poll(() => page.url()).toContain(chosen[0].hash);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const queue = page.getByRole("region", { name: "Chosen files" });
  await expect(
    queue.getByRole("listitem").filter({ hasText: "three.xlsx" }).getByText("Needs attention"),
  ).toBeVisible();
  await queue.getByRole("button", { name: "Next file needing attention" }).click();
  await expect(review.getByRole("heading", { name: "three.xlsx" })).toBeVisible();
  await expect.poll(() => page.url()).toContain(chosen[2].hash);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("region", { name: "Chosen files" }).getByRole("button", {
      name: "Next file needing attention",
    }),
  ).toHaveCount(0);
  expect(commits).toEqual([]);
});

test("the queue fits 390 width with no horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page, ["COMMITTED", 409, "COMMITTED"], [bookOf(1, "PENDING_REVIEW")]);
  await attach(page);
  const queue = page.getByRole("region", { name: "Chosen files" });
  await expect(queue.getByRole("listitem")).toHaveCount(3);
  await expect(queue.getByText("Already uploaded")).toBeVisible();
  await page.screenshot({
    path: "test-results/screenshots/T106-upload-queue-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
});
