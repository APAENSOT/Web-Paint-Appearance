/**
 * T97 (D-97-5) in a real browser: the review screen refreshes itself.
 *
 * What the owner saw: after uploading, the confirm screen said *"0 readings
 * ready to add"*, *"We are still reading this tab"* and kept Approve greyed
 * until the page was left and reopened -- *"it always happen when upload
 * something."* The worksheet read had no poll of its own and was not on the
 * invalidation list the workbook poll already fires when a sheet leaves
 * `RUNNING`, so the screen held the answer it got while the batch was still
 * parsing.
 *
 * So the whole spec is one navigation. The sheet starts `RUNNING`, the clock
 * advances, and the rows appear with no `goto`, no reload and no second
 * screen.
 */
import { expect, test } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { cleanReview } from "../fixtures";
import { fileHash, workbookFixture } from "../workbook-fixtures";

const book: components["schemas"]["WorkbookOut"] = {
  ...workbookFixture,
  plant_code: "FTM",
  source_file: "09 Sep2026 CF data FTM.xlsx",
  sheets: [
    {
      ...workbookFixture.sheets[0],
      batch: { ...workbookFixture.sheets[0].batch, plant_code: "FTM", source_sheet: "PasteData" },
    },
  ],
};
const loadId = book.sheets[0].batch.load_id;

const sheetOf = (ready: boolean): components["schemas"]["WorksheetSheetOut"] => ({
  load_id: loadId,
  sheet: "PasteData",
  status: ready ? "PENDING_REVIEW" : "RUNNING",
  state: ready ? "ready" : "processing",
  commit_blockers: ready ? [] : ["NOT_PENDING_REVIEW"],
  rows_ready: ready ? 12 : 0,
  rows_loaded: 0,
  rows_held: 0,
  rows_already_in_history: 0,
  rows_need_confirmation: 0,
  rows: ready
    ? [
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
      ]
    : [],
  extra_columns: [],
  missing_optional: [],
  hole_rows: [],
  plant_texts: [],
  held: [],
  vehicle_count: ready ? 1 : 0,
  short_vehicles: [],
  operator_message: ready ? "Twelve rows can load." : "We are still reading this tab.",
});

const worksheetOf = (ready: boolean): components["schemas"]["WorksheetOut"] => ({
  plant_code: "FTM",
  file_hash: fileHash,
  source_file: book.source_file,
  plant_question: null,
  extra_columns: [],
  missing_optional: [],
  missing_optional_message: null,
  ready_sheet_count: ready ? 1 : 0,
  rows_ready: ready ? 12 : 0,
  rows_held: 0,
  rows_already_in_history: 0,
  rows_need_confirmation: 0,
  summary_message: ready ? "12 readings ready to add." : "0 readings ready to add.",
  checklist: [],
  load_button_label: "Yes, load these rows",
  sheets: [sheetOf(ready)],
});

test("the worksheet read refetches when the sheet leaves RUNNING, with no navigation", async ({
  page,
}) => {
  await page.clock.install();
  await mockHistory(page, "admin");
  let parsed = false;
  let worksheetReads = 0;
  await page.route("**/api/v1/plants/FTM/workbooks?*", (route) =>
    route.fulfill({
      json: {
        plant_code: "FTM",
        plant_is_active: true,
        inbox: "all",
        uploaded_month: null,
        items: [
          {
            ...book,
            sheets: book.sheets.map((item) => ({
              ...item,
              committable: parsed,
              commit_blockers: parsed ? [] : ["NOT_PENDING_REVIEW"],
              batch: {
                ...item.batch,
                status: parsed ? "PENDING_REVIEW" : "RUNNING",
                job: { ...item.batch.job, status: parsed ? "DONE" : "RUNNING" },
              },
            })),
          },
        ],
        page: { offset: 0, limit: 200, total: 1, returned: 1 },
      },
    }),
  );
  await page.route(`**/workbooks/${fileHash}`, (route) =>
    route.fulfill({
      json: {
        workbook: {
          ...book,
          sheets: book.sheets.map((item) => ({
            ...item,
            committable: parsed,
            commit_blockers: parsed ? [] : ["NOT_PENDING_REVIEW"],
            batch: {
              ...item.batch,
              status: parsed ? "PENDING_REVIEW" : "RUNNING",
              job: { ...item.batch.job, status: parsed ? "DONE" : "RUNNING" },
            },
          })),
        },
        profiles: [],
        possible_replacements: [],
        acknowledgements: [],
      },
    }),
  );
  await page.route(`**/workbooks/${fileHash}/worksheet`, (route) => {
    worksheetReads++;
    return route.fulfill({ json: worksheetOf(parsed) });
  });
  await page.route(`**/api/v1/batches/${loadId}`, (route) =>
    route.fulfill({
      json: { ...cleanReview, batch: book.sheets[0].batch, held_labels: [] },
    }),
  );

  await page.goto(`/plant/ftm?file=${fileHash}`);
  const dialog = page.getByRole("dialog").first();
  await expect(dialog.getByText("0 readings ready to add.")).toBeVisible();
  await expect.poll(() => worksheetReads).toBeGreaterThan(0);
  const whileParsing = worksheetReads;

  // The batch finishes. Nothing is clicked and nothing is navigated: the
  // workbook poll sees the sheet leave RUNNING and invalidates the
  // worksheet read with it (D-97-5).
  parsed = true;
  await page.clock.runFor(10000);
  await expect(dialog.getByText("12 readings ready to add.")).toBeVisible();
  await expect(dialog.getByText("12LCPILLAR")).toBeVisible();
  expect(worksheetReads).toBeGreaterThan(whileParsing);
  expect(page.url()).toContain(`file=${fileHash}`);
});
