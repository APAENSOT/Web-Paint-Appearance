import { expect, test } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { cleanReview } from "../fixtures";
import { workbookFixture, fileHash } from "../workbook-fixtures";

const book = {
  ...workbookFixture,
  plant_code: "FTM",
  source_file: "Colour tabs.xlsx",
  measured_date_min: "2026-06-07",
  measured_date_max: "2026-06-09",
  measured_dates_span_months: false,
  sheets: [
    {
      ...workbookFixture.sheets[0],
      batch: {
        ...workbookFixture.sheets[0].batch,
        plant_code: "FTM",
        source_sheet: "Absolute / Shadow Black",
        film_tail: false,
      },
    },
  ],
};
const held: components["schemas"]["HeldLabelGroup"][] = [
  {
    reason: "COLOR_NOT_OFFERED",
    column: "color",
    raw_value: "Black",
    count: 2,
    teachable_kind: "ALIAS_COLOR",
    candidates: ["Absolute / Shadow Black", "Agate Black"],
    display_group: "plant_offer",
    operator_message: "This colour is not on this plant's list. Pick its official catalogue name.",
  },
  {
    reason: "UNKNOWN_MODEL",
    column: "model",
    raw_value: "(None)",
    count: 1,
    teachable_kind: null,
    candidates: [],
    display_group: "empty_identity",
    operator_message: "This row has no model. It will not load.",
  },
];
const worksheet: components["schemas"]["WorksheetOut"] = {
  plant_code: "FTM",
  file_hash: fileHash,
  source_file: book.source_file,
  plant_question: null,
  extra_columns: ["Panel2"],
  missing_optional: ["doi"],
  missing_optional_message: "This file has no DOI column. Rows can still load with DOI empty.",
  ready_sheet_count: 1,
  rows_ready: 10,
  rows_held: 3,
  rows_already_in_history: 1,
  rows_need_confirmation: 0,
  summary_message: "10 readings ready to add, 3 held out, 1 already in History.",
  checklist: [],
  load_button_label: "Yes, load these rows",
  sheets: [
    {
      load_id: book.sheets[0].batch.load_id,
      sheet: "Absolute / Shadow Black",
      status: "PENDING_REVIEW",
      state: "ready",
      commit_blockers: [],
      rows_ready: 10,
      rows_loaded: 0,
      rows_held: 3,
      rows_already_in_history: 1,
      rows_need_confirmation: 0,
      rows: [
        {
          source_sheet: "Absolute / Shadow Black",
          film_tail: false,
          source_row: 2,
          panel_label: "01HOOD",
          checkzone: null,
          model_text: "Ranger",
          model: "P703",
          color_text: "Black",
          color: null,
          date_text: "7 June 2026",
          measured_date: "2026-06-07",
          outcome: "held_out",
          operator_message: "Pick the panel from this model list.",
        },
        {
          source_sheet: "Absolute / Shadow Black",
          film_tail: false,
          source_row: 3,
          panel_label: "06 LFFender",
          checkzone: "LFFENDER",
          model_text: "Ranger",
          model: "P703",
          color_text: "Black",
          color: "Absolute / Shadow Black",
          date_text: "7 June 2026",
          measured_date: "2026-06-07",
          outcome: "ready",
          operator_message: "Ready to add.",
        },
      ],
      extra_columns: ["Panel2"],
      missing_optional: ["doi"],
      hole_rows: [7],
      plant_texts: [],
      held,
      vehicle_count: 1,
      short_vehicles: [
        {
          measured_date: "2026-06-07",
          model: "P703",
          color: "Absolute / Shadow Black",
          point_count: 31,
          expected_point_count: 32,
          operator_message: "This vehicle has 31 of 32 panels. Load the ones we have?",
        },
      ],
      operator_message: "Ten rows can load. Three remain held.",
    },
  ],
};

test("whole-file confirm shows decisions and loads ready rows; mobile checklist stacks", async ({
  page,
}) => {
  await mockHistory(page, "admin");
  let loaded = false;
  await page.route("**/api/v1/plants/FTM/workbooks?*", (route) =>
    route.fulfill({
      json: {
        plant_code: "FTM",
        plant_is_active: true,
        inbox: "all",
        uploaded_month: null,
        items: [
          loaded
            ? {
                ...book,
                operational_summary: "PARTIALLY_COMMITTED",
                sheets: book.sheets.map((item) => ({
                  ...item,
                  committable: false,
                  batch: { ...item.batch, status: "COMMITTED" },
                })),
              }
            : book,
        ],
        page: { offset: 0, limit: 200, total: 1, returned: 1 },
      },
    }),
  );
  await page.route(`**/workbooks/${fileHash}`, (route) =>
    route.fulfill({
      json: {
        workbook: book,
        profiles: [],
        possible_replacements: [],
        acknowledgements: [],
      },
    }),
  );
  let extraColumns = ["Panel2"];
  await page.route(`**/workbooks/${fileHash}/worksheet`, (route) =>
    route.fulfill({
      json: {
        ...worksheet,
        extra_columns: extraColumns,
        sheets: loaded
          ? [{ ...worksheet.sheets[0], state: "loaded", rows_loaded: 10, rows_ready: 1 }]
          : worksheet.sheets,
      },
    }),
  );
  await page.route(`**/api/v1/batches/${book.sheets[0].batch.load_id}`, (route) =>
    route.fulfill({
      json: {
        ...cleanReview,
        batch: book.sheets[0].batch,
        held_labels: held,
      },
    }),
  );
  let aliasBody: Record<string, unknown> | null = null;
  await page.route("**/api/v1/mappings/proposals", (route) => {
    aliasBody = route.request().postDataJSON();
    return route.fulfill({ status: 201, json: { id: "plant-offer-alias", ...aliasBody } });
  });
  const decisions: { path: string; body: unknown }[] = [];
  await page.route(`**/workbooks/${fileHash}/ignore-columns`, (route) => {
    decisions.push({ path: "ignore-columns", body: route.request().postDataJSON() });
    extraColumns = [];
    return route.fulfill({ json: { decisions_written: 1, replayed_load_ids: [] } });
  });
  await page.route(`**/workbooks/${fileHash}/hole-approval`, (route) => {
    decisions.push({ path: "hole-approval", body: route.request().postDataJSON() });
    return route.fulfill({ json: { decisions_written: 1, replayed_load_ids: [] } });
  });
  await page.route(`**/workbooks/${fileHash}/load-ready`, (route) => {
    expect(route.request().postData()).toBeNull();
    loaded = true;
    return route.fulfill({
      json: {
        sheets: [],
        measurements_inserted: 10,
        rows_held: 3,
        rows_already_in_history: 1,
        rows_need_confirmation: 0,
        months: ["2026-06"],
        operator_message: "10 readings added to June 2026, 3 held out, 1 already in History.",
      },
    });
  });
  let remainingLoaded = false;
  await page.route(`**/workbooks/${fileHash}/load-remaining`, (route) => {
    expect(route.request().postData()).toBeNull();
    remainingLoaded = true;
    return route.fulfill({
      json: {
        sheets: [],
        measurements_inserted: 1,
        rows_held: 2,
        rows_already_in_history: 1,
        rows_need_confirmation: 0,
        months: ["2026-06"],
        operator_message: "1 more readings added to June 2026, 2 held out.",
      },
    });
  });
  await page.goto(`/plant/ftm?file=${fileHash}`);
  const dialog = page.getByRole("dialog").first();
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(dialog.getByRole("heading", { name: "Confirm this worksheet" })).toBeVisible();
  await expect(dialog.getByText(worksheet.missing_optional_message!)).toBeVisible();
  await expect(
    dialog.getByText("We do not use this column. Ignore it and keep the rest?"),
  ).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "2. Check missing columns" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "1. Absolute / Shadow Black" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Plant list" })).toBeVisible();
  await expect(
    dialog.getByLabel("Official catalogue colour name").locator('option[value=""]'),
  ).toHaveText("Pick catalogue colour");
  await expect(
    dialog.getByLabel("Official catalogue colour name").locator('option[value="Agate Black"]'),
  ).toHaveCount(1);
  await expect(dialog.getByLabel("Official catalogue colour name")).toHaveValue("");
  await expect(
    dialog.getByText("This vehicle has 31 of 32 panels. Load the ones we have?"),
  ).toBeVisible();
  await expect(dialog.getByText("These rows have no model.", { exact: false })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(dialog.getByRole("button", { name: "Approve loading without LW/SW" })).toBeVisible();
  await dialog.getByLabel("Official catalogue colour name").selectOption("Absolute / Shadow Black");
  await page
    .getByRole("dialog", { name: "Confirm alias" })
    .getByRole("button", { name: "Confirm alias Black as Absolute / Shadow Black" })
    .click();
  await expect.poll(() => aliasBody).not.toBeNull();
  expect(aliasBody).toMatchObject({
    kind: "ALIAS_COLOR",
    load_id: book.sheets[0].batch.load_id,
    payload: { raw_value: "Black", color_name: "Absolute / Shadow Black", plant_code: "FTM" },
  });
  await dialog.getByRole("button", { name: "Review ignored columns" }).click();
  await page
    .getByRole("dialog", { name: "Confirm worksheet decision" })
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect.poll(() => decisions.length).toBe(1);
  await expect(dialog.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "Approve loading without LW/SW" }).click();
  await page
    .getByRole("dialog", { name: "Confirm worksheet decision" })
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect.poll(() => decisions.length).toBe(2);
  expect(decisions).toEqual([
    { path: "ignore-columns", body: { headers: ["Panel2"] } },
    { path: "hole-approval", body: { load_id: book.sheets[0].batch.load_id, source_rows: [7] } },
  ]);
  await dialog.getByRole("button", { name: "Approve", exact: true }).click();
  await expect.poll(() => loaded).toBe(true);
  await expect(dialog).toHaveCount(0);
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "10 readings added to June 2026, 3 held out, 1 already in History." }),
  ).toBeVisible();
  await expect(page.getByRole("article").filter({ hasText: book.source_file })).toHaveCount(1);
  await expect(page.getByRole("article").filter({ hasText: book.source_file })).toContainText(
    "Partially approved",
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("heading", { name: "Upload Data", exact: true }).scrollIntoViewIfNeeded();
  await page.getByRole("button", { name: `Review ${book.source_file}` }).click();
  await dialog.getByRole("button", { name: "Load remaining matched rows" }).click();
  await expect.poll(() => remainingLoaded).toBe(true);
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("status").filter({ hasText: "1 more readings added to June 2026, 2 held out." }),
  ).toBeVisible();
});

test("identical upload opens the stored workbook from the inbox", async ({ page }) => {
  await mockHistory(page, "admin");
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
  await page.route("**/api/v1/uploads", (route) =>
    route.fulfill({
      status: 409,
      json: {
        statusCode: 409,
        error: "Conflict",
        message: `"again.xlsx" has already been ingested: its SHA-256 matches load_id ${book.sheets[0].batch.load_id} (${book.source_file} [Absolute / Shadow Black], PENDING_REVIEW). Nothing was stored.`,
        correlationId: "stored-workbook",
      },
    }),
  );
  await page.route(`**/workbooks/${fileHash}`, (route) =>
    route.fulfill({
      json: { workbook: book, profiles: [], possible_replacements: [], acknowledgements: [] },
    }),
  );
  await page.route(`**/workbooks/${fileHash}/worksheet`, (route) =>
    route.fulfill({ json: worksheet }),
  );
  await page.goto("/plant/ftm?dataView=upload");
  await expect(page.getByRole("article").filter({ hasText: book.source_file })).toHaveCount(1);
  await page.getByLabel("Attach workbook", { exact: true }).setInputFiles({
    name: "again.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("same workbook"),
  });
  await page.getByRole("button", { name: "Open the stored workbook" }).click();
  await expect(
    page.getByRole("dialog").first().getByRole("heading", { name: "Confirm this worksheet" }),
  ).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(0);
});

test("T53 mixed table keeps panel text and extra tabs; desktop and mobile Approve", async ({
  page,
}) => {
  await mockHistory(page, "engineer");
  const row = worksheet.sheets[0].rows[0];
  const data: components["schemas"]["WorksheetOut"] = {
    ...worksheet,
    extra_columns: [],
    missing_optional: [],
    missing_optional_message: null,
    rows_ready: 1,
    rows_held: 2,
    rows_already_in_history: 1,
    rows_need_confirmation: 0,
    summary_message: "1 readings ready to add, 2 held out, 1 already in History.",
    sheets: [
      {
        ...worksheet.sheets[0],
        load_id: 999,
        sheet: "Methods",
        state: "not_wavescan",
        held: [],
        hole_rows: [],
        short_vehicles: [],
        rows: [],
        rows_ready: 0,
        rows_held: 0,
        rows_already_in_history: 0,
        rows_need_confirmation: 0,
        operator_message: "Extra tab kept. Not loaded.",
      },
      {
        ...worksheet.sheets[0],
        held: [],
        hole_rows: [],
        short_vehicles: [],
        extra_columns: [],
        rows_ready: 1,
        rows_held: 2,
        rows_already_in_history: 1,
        rows_need_confirmation: 0,
        operator_message: "1 readings ready to add, 2 held out, 1 already in History.",
        rows: [
          row,
          worksheet.sheets[0].rows[1],
          {
            ...worksheet.sheets[0].rows[1],
            source_row: 4,
            outcome: "held_out",
            operator_message:
              "The same panel and readings appear twice in this file. The other copy is added; this one is kept as a record.",
          },
          {
            ...worksheet.sheets[0].rows[1],
            source_row: 5,
            outcome: "already_in_history",
            operator_message: "This reading is in History.",
          },
        ],
      },
    ],
  };
  await page.route(`**/workbooks/${fileHash}`, (r) =>
    r.fulfill({
      json: { workbook: book, profiles: [], possible_replacements: [], acknowledgements: [] },
    }),
  );
  await page.route(`**/workbooks/${fileHash}/worksheet`, (r) => r.fulfill({ json: data }));
  await page.goto(`/plant/ftm?file=${fileHash}`);
  const dialog = page.getByRole("dialog").first();
  await expect(dialog.getByText("Extra tab kept. Not loaded.", { exact: true })).toBeVisible();
  const table = dialog.getByRole("table");
  await expect(table.locator("tbody tr")).toHaveCount(4);
  const compact = table.getByRole("row").filter({ hasText: "01HOOD" });
  await expect(compact).toHaveAttribute("data-outcome", "held_out");
  await expect(compact).toContainText("Not resolved");
  await expect(compact).not.toContainText("RRHOOD");
  await expect(table).not.toContainText(/LOAD|DUPLICATE|QUARANTINE|REJECT/);
  await expect(table.locator("input")).toHaveCount(0);
  const approve = dialog.getByRole("button", { name: "Approve", exact: true });
  await expect(approve).toBeEnabled();
  await page.screenshot({
    path: "test-results/screenshots/T53-confirm-table-desktop.png",
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await approve.scrollIntoViewIfNeeded();
  await compact.evaluate((element) => element.scrollIntoView({ block: "center" }));
  await expect(approve).toBeVisible();
  await expect(approve).toBeEnabled();
  await page.screenshot({
    path: "test-results/screenshots/T53-confirm-table-mobile.png",
    animations: "disabled",
  });
});
