/**
 * T100 in a real browser: the Film sheet's question, and the read-only tick.
 *
 * Every assertion is about what the screen does with `film_question` and
 * `counted` -- fields the server fills (D-100-1). The API is mocked with
 * `page.route`, the way `t94-rough-panels.spec.ts` does it: no upload here,
 * because the real FTM files are T101.
 *
 * What this pins:
 *
 * * D-100-2 -- a known point's tick is read-only;
 * * D-100-4 -- a FTWISH row reads "Not stored", not "Held out";
 * * D-100-5 -- one question per sheet, asked once above the table; Confirm
 *   waits for an H or a V on every new name and posts exactly those points;
 *   a walk that cannot be confirmed gets no button; the model question posts
 *   the model that was clicked; Load as written posts once.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { cleanReview } from "../fixtures";
import { fileHash, workbookFixture } from "../workbook-fixtures";

const SHOTS = "test-results/screenshots";

type Row = components["schemas"]["WorksheetRowOut"];
type Question = components["schemas"]["FilmSheetQuestion"];
type Sheet = components["schemas"]["WorksheetSheetOut"];

const LOAD_ID = 777;

function row(overrides: Partial<Row> = {}): Row {
  return {
    source_sheet: "Quick Summary",
    film_tail: false,
    source_row: 15,
    panel_label: "001HOOD",
    checkzone: "001HOOD",
    model_text: null,
    model: "P703 SGL",
    color_text: "Arctic White",
    color: "Arctic White",
    date_text: "2026-09-14",
    measured_date: "2026-09-14",
    outcome: "ready",
    operator_message: "Ready to add.",
    counted: true,
    ...overrides,
  };
}

const HELD_ROWS: Row[] = [
  row({ source_row: 15, outcome: "held_out", counted: null, checkzone: null }),
  row({
    source_row: 16,
    panel_label: "002HOOD",
    checkzone: null,
    outcome: "held_out",
    counted: null,
  }),
  row({
    source_row: 21,
    panel_label: "001FTWISH",
    checkzone: null,
    outcome: "held_out",
    counted: null,
    film_tail: true,
    operator_message: '"001FTWISH" is the known tail of FTM\'s P703 SGL walk.',
  }),
];

const READY_ROWS: Row[] = [
  row({ source_row: 15 }),
  row({ source_row: 16, panel_label: "002HOOD", checkzone: "002HOOD", counted: false }),
  row({
    source_row: 21,
    panel_label: "001FTWISH",
    checkzone: null,
    outcome: "held_out",
    counted: null,
    film_tail: true,
    operator_message: '"001FTWISH" is the known tail of FTM\'s P703 SGL walk.',
  }),
];

const WALK: Question = {
  kind: "walk",
  operator_message:
    "This sheet writes 2 name(s) past the last point of FTM's P703 SGL walk it names, " +
    'starting with "099TGATEIN".',
  model_code: "P703 SGL",
  confirmable: true,
  appended: [
    { point_code: "099TGATEIN", proposed_orientation: "V", counted: true },
    { point_code: "100NEWWORD", proposed_orientation: null, counted: true },
  ],
  models: [],
  job_no: "AW_SGL_1961607",
};

const HELD_WALK: Question = {
  ...WALK,
  confirmable: false,
  appended: [],
  operator_message:
    'This sheet writes "035LBPILLAR", which is not a point of FTM\'s P703 SGL walk, and ' +
    "it writes names that are on the walk after it.",
};

const MODEL: Question = {
  kind: "model",
  operator_message:
    'This sheet names two models: the Job Number "AW_RB_1961607" says P703 DBL RAPTOR ' +
    'and the file name "AW_DBL_1961607.xlsx" says P703 DBL RANGER.',
  model_code: "P703 DBL RANGER",
  confirmable: false,
  appended: [],
  models: ["P703 DBL RAPTOR", "P703 DBL RANGER"],
  job_no: "AW_RB_1961607",
};

const JOB: Question = {
  kind: "job",
  operator_message:
    'The Job Number on this sheet is "BL_RAP_6218", which is not the shape this plant writes.',
  model_code: "P703 RAPCAP",
  confirmable: false,
  appended: [],
  models: [],
  job_no: "BL_RAP_6218",
};

function sheetWith(question: Question | null, rows: Row[]): Sheet {
  return {
    load_id: LOAD_ID,
    sheet: "Quick Summary",
    status: "PENDING_REVIEW",
    state: question ? "needs_answer" : "ready",
    commit_blockers: [],
    rows_ready: question ? 0 : 2,
    rows_loaded: 0,
    rows_held: question ? rows.length - 1 : 1,
    rows_already_in_history: 0,
    rows_need_confirmation: 0,
    rows,
    held: [],
    extra_columns: [],
    missing_optional: [],
    hole_rows: [],
    plant_texts: [],
    panel_rename: [],
    rough_panels: [],
    film_question: question,
    vehicle_count: 1,
    short_vehicles: [],
    operator_message: question
      ? "Answer the question for this tab first."
      : "2 readings ready to add, 1 held out.",
  };
}

function worksheetWith(question: Question | null, rows: Row[]) {
  const sheet = sheetWith(question, rows);
  return {
    plant_code: "FTM",
    file_hash: fileHash,
    source_file: "AW_SGL_1961607.xlsx",
    sheets: [sheet],
    plant_question: null,
    extra_columns: [],
    missing_optional: [],
    missing_optional_message: null,
    ready_sheet_count: question ? 0 : 1,
    rows_ready: sheet.rows_ready,
    rows_held: sheet.rows_held,
    rows_already_in_history: 0,
    rows_need_confirmation: 0,
    summary_message: sheet.operator_message,
    checklist: [],
    load_button_label: "Yes, load these rows",
  } as components["schemas"]["WorksheetOut"];
}

const book = {
  ...workbookFixture,
  plant_code: "FTM",
  source_file: "AW_SGL_1961607.xlsx",
  measured_date_min: "2026-09-14",
  measured_date_max: "2026-09-14",
  measured_dates_span_months: false,
};

async function setup(page: Page, question: Question | null, rows: Row[] = HELD_ROWS) {
  await mockHistory(page, "engineer");
  let data = worksheetWith(question, rows);
  const posts: { path: string; body: unknown }[] = [];
  await page.route("**/api/v1/plants/FTM/workbooks?*", (route) =>
    route.fulfill({
      json: {
        plant_code: "FTM",
        plant_is_active: true,
        inbox: "all",
        uploaded_month: null,
        items: [book],
        page: { offset: 0, limit: 200, total: 1, returned: 1 },
      },
    }),
  );
  await page.route(`**/workbooks/${fileHash}`, (route) =>
    route.fulfill({
      json: { workbook: book, profiles: [], possible_replacements: [], acknowledgements: [] },
    }),
  );
  await page.route(`**/workbooks/${fileHash}/worksheet`, (route) => route.fulfill({ json: data }));
  await page.route(`**/api/v1/batches/${LOAD_ID}`, (route) =>
    route.fulfill({ json: { ...cleanReview, held_labels: [] } }),
  );
  // The three answers. Each one makes the server stop asking and the rows
  // ready, which is what the replay does for real.
  for (const path of ["film-walk-confirm", "film-model-answer", "film-job-answer"]) {
    await page.route(`**/workbooks/${fileHash}/${path}`, (route) => {
      posts.push({ path, body: route.request().postDataJSON() });
      data = worksheetWith(null, READY_ROWS);
      return route.fulfill({
        json: {
          decisions_written: 1,
          replayed_load_ids: [LOAD_ID],
          operator_message: "The tab is being read again.",
        },
      });
    });
  }
  await page.goto(`/plant/ftm?file=${fileHash}`);
  return { posts };
}

function panel(page: Page) {
  return page.locator('[data-testid="film-question"]');
}

test("T100 asks the walk question once above the table, and Confirm waits for every H/V", async ({
  page,
}) => {
  const { posts } = await setup(page, WALK);
  await expect(panel(page)).toHaveCount(1, { timeout: 15000 });
  await expect(panel(page)).toHaveAttribute("data-film-question", "walk");
  await expect(panel(page)).toHaveAttribute("data-film-confirmable", "yes");
  // The server's own sentence, not one the client built.
  await expect(panel(page)).toContainText("past the last point");

  await page.screenshot({ path: `${SHOTS}/T100-review-question-desktop.png`, fullPage: true });

  const confirm = page.getByTestId("film-confirm-walk");
  // One name has no proposal, so Confirm is not available yet (D-100-5).
  await expect(confirm).toBeDisabled();
  await expect(page.getByTestId("film-appended-orientation-099TGATEIN")).toHaveValue("V");
  await expect(page.getByTestId("film-appended-orientation-100NEWWORD")).toHaveValue("");

  await page.getByTestId("film-appended-orientation-100NEWWORD").selectOption("H");
  await page.getByTestId("film-appended-counted-100NEWWORD").uncheck();
  await expect(confirm).toBeEnabled();
  await confirm.click();

  // Exactly the two appended points, with what the row said.
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toEqual({
    path: "film-walk-confirm",
    body: {
      load_id: LOAD_ID,
      points: [
        { point_code: "099TGATEIN", counted: true, orientation: "V" },
        { point_code: "100NEWWORD", counted: false, orientation: "H" },
      ],
    },
  });
  // The table was read again and the question is gone (T97 refresh).
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByTestId("row-counted-15")).toBeVisible();
});

test("T100 shows a walk it cannot confirm with no button", async ({ page }) => {
  const { posts } = await setup(page, HELD_WALK);
  await expect(panel(page)).toHaveAttribute("data-film-confirmable", "no", { timeout: 15000 });
  await expect(panel(page)).toContainText("035LBPILLAR");
  await expect(panel(page)).toContainText("owner decision");
  await expect(page.getByTestId("film-confirm-walk")).toHaveCount(0);
  expect(posts).toEqual([]);
});

test("T100 posts the model that was clicked, and Load as written posts once", async ({ page }) => {
  const model = await setup(page, MODEL);
  await expect(panel(page)).toHaveAttribute("data-film-question", "model", { timeout: 15000 });
  await page.getByTestId("film-choose-model-P703 DBL RAPTOR").click();
  await expect.poll(() => model.posts.length).toBe(1);
  expect(model.posts[0]).toEqual({
    path: "film-model-answer",
    body: { load_id: LOAD_ID, model_code: "P703 DBL RAPTOR" },
  });

  const job = await setup(page, JOB);
  await expect(panel(page)).toHaveAttribute("data-film-question", "job", { timeout: 15000 });
  await expect(panel(page)).toContainText("BL_RAP_6218");
  await page.getByTestId("film-load-as-written").click();
  await expect.poll(() => job.posts.length).toBe(1);
  expect(job.posts[0]).toEqual({ path: "film-job-answer", body: { load_id: LOAD_ID } });
});

test("T100 ticks known points read-only and calls the FTWISH row Not stored", async ({ page }) => {
  await setup(page, null, READY_ROWS);
  const table = page.getByRole("table").filter({ hasText: "Panel as written" }).first();
  await expect(table).toBeVisible({ timeout: 15000 });
  await expect(table).toContainText("Counted");

  const ticked = page.getByTestId("row-counted-15");
  await expect(ticked).toBeChecked();
  await expect(ticked).toBeDisabled();
  await expect(page.getByTestId("row-counted-16")).not.toBeChecked();
  await expect(page.getByTestId("row-counted-16")).toBeDisabled();

  // D-100-4: the tail row is "Not stored", has no tick, and is not a row
  // that needs attention.
  const tail = table.locator("tr").filter({ hasText: "001FTWISH" });
  await expect(tail).toContainText("Not stored");
  await expect(tail).not.toContainText("Held out");
  await expect(page.getByTestId("row-counted-21")).toHaveCount(0);
  await page.getByRole("button", { name: "Need attention" }).click();
  await expect(table.locator("tr").filter({ hasText: "001FTWISH" })).toHaveCount(0);
});

test("T100 the review panel fits a 390px screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page, WALK);
  await expect(panel(page)).toHaveCount(1, { timeout: 15000 });
  await page.screenshot({ path: `${SHOTS}/T100-review-question-390.png`, fullPage: true });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
