import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { cleanReview } from "../fixtures";
import { fileHash, workbookFixture } from "../workbook-fixtures";

type Row = components["schemas"]["WorksheetRowOut"];
type Held = components["schemas"]["HeldLabelGroup"];
const row: Row = {
  source_sheet: "Review1",
  film_tail: false,
  source_row: 2,
  panel_label: "01HOOD",
  checkzone: null,
  model_text: "Ranger",
  model: "P703",
  color_text: "Absolute / Shadow Black",
  color: "Absolute / Shadow Black",
  date_text: "7 June 2026",
  measured_date: "2026-06-07",
  outcome: "held_out",
  operator_message: "Pick this panel from the model's catalogue.",
};
const held: Held[] = [
  {
    reason: "UNKNOWN_CHECKZONE",
    column: "checkzone",
    raw_value: "01HOOD",
    count: 1,
    display_group: "zone",
    teachable_kind: "ALIAS_CHECKZONE",
    model_code: "P703",
    candidates: ["RRHOOD", "LFFENDER"],
    operator_message: "Pick this panel from the model's catalogue.",
  },
  {
    reason: "UNKNOWN_MODEL",
    column: "model",
    raw_value: "Ranjer",
    count: 1,
    display_group: "model",
    teachable_kind: "ALIAS_MODEL",
    candidates: ["P703", "U704"],
    operator_message: "Pick the existing model.",
  },
  {
    reason: "UNKNOWN_COLOR",
    column: "color",
    raw_value: "Black",
    count: 2,
    display_group: "colour",
    teachable_kind: "ALIAS_COLOR",
    candidates: ["Absolute / Shadow Black", "Agate Black"],
    operator_message: "Pick the official catalogue colour.",
  },
  {
    reason: "BAD_DATE",
    column: "date",
    raw_value: "",
    count: 1,
    display_group: "date",
    teachable_kind: null,
    candidates: [],
    operator_message: "This row has no date. Fix the file and upload again.",
  },
  {
    reason: "UNKNOWN_FILM_POINT",
    column: "point",
    raw_value: "Extra Film point",
    count: 1,
    display_group: "film_point",
    teachable_kind: null,
    candidates: [],
    operator_message: "This Film point is not on this plant's gold list.",
  },
  {
    reason: "UNKNOWN_FILM_MODEL",
    column: "model",
    raw_value: "Filename program",
    count: 1,
    display_group: "film_model",
    teachable_kind: null,
    candidates: [],
    operator_message: "Ask an Admin to add this Film model first.",
  },
  {
    reason: "MODEL_NOT_OFFERED",
    column: "model",
    raw_value: "Unlisted",
    count: 1,
    display_group: "model",
    teachable_kind: null,
    candidates: ["P703"],
    operator_message: "Ask an Admin to add this model first.",
  },
];
const rows: Row[] = [
  row,
  {
    ...row,
    source_row: 3,
    panel_label: "06 LFFender",
    checkzone: "LFFENDER",
    model_text: "Ranjer",
    model: null,
    operator_message: held[1].operator_message,
  },
  {
    ...row,
    source_row: 4,
    panel_label: "09 Ready panel",
    checkzone: "RRHOOD",
    outcome: "ready",
    operator_message: "Ready to add.",
  },
  {
    ...row,
    source_row: 5,
    panel_label: "07 RFFender",
    checkzone: "RFFENDER",
    color_text: "Black",
    color: null,
    operator_message: held[2].operator_message,
  },
  {
    ...row,
    source_row: 6,
    panel_label: "08 Left door",
    checkzone: "LFDOOR",
    color_text: "Black",
    color: null,
    operator_message: held[2].operator_message,
  },
  {
    ...row,
    source_row: 7,
    panel_label: "10 History panel",
    checkzone: "RRHOOD",
    outcome: "already_in_history",
    operator_message: "This reading is in History.",
  },
  {
    ...row,
    source_row: 8,
    panel_label: "11 Missing date",
    date_text: null,
    measured_date: null,
    operator_message: held[3].operator_message,
  },
  {
    ...row,
    source_row: 9,
    panel_label: "Extra Film point",
    operator_message: held[4].operator_message,
  },
  {
    ...row,
    source_row: 10,
    panel_label: "Film model row",
    model_text: "Filename program",
    model: null,
    operator_message: held[5].operator_message,
  },
  {
    ...row,
    source_row: 11,
    panel_label: "Unlisted model row",
    model_text: "Unlisted",
    model: null,
    operator_message: held[6].operator_message,
  },
];
const sheet: components["schemas"]["WorksheetSheetOut"] = {
  load_id: 123,
  sheet: "Review1",
  status: "PENDING_REVIEW",
  state: "ready",
  commit_blockers: [],
  rows_ready: 1,
  rows_loaded: 0,
  rows_held: 8,
  rows_already_in_history: 1,
  rows_need_confirmation: 0,
  rows,
  held,
  extra_columns: [],
  missing_optional: [],
  hole_rows: [],
  plant_texts: [],
  vehicle_count: 1,
  short_vehicles: [],
  operator_message: "1 readings ready to add, 8 held out, 1 already in History.",
};
const worksheet: components["schemas"]["WorksheetOut"] = {
  plant_code: "FTM",
  file_hash: fileHash,
  source_file: "Attention review.xlsx",
  sheets: [
    {
      ...sheet,
      load_id: 999,
      sheet: "Methods",
      state: "not_wavescan",
      rows_ready: 0,
      rows_held: 0,
      rows_already_in_history: 0,
      rows_need_confirmation: 0,
      rows: [],
      held: [],
      operator_message: "Extra tab kept. Not loaded.",
    },
    sheet,
  ],
  plant_question: null,
  extra_columns: [],
  missing_optional: [],
  missing_optional_message: null,
  ready_sheet_count: 1,
  rows_ready: 1,
  rows_held: 8,
  rows_already_in_history: 1,
  rows_need_confirmation: 0,
  summary_message: sheet.operator_message,
  checklist: [],
  load_button_label: "Yes, load these rows",
};
const book = {
  ...workbookFixture,
  plant_code: "FTM",
  source_file: worksheet.source_file,
  measured_date_min: "2026-06-07",
  measured_date_max: "2026-06-07",
  measured_dates_span_months: false,
};

async function setup(page: Page, role = "engineer") {
  await mockHistory(page, role);
  let data = structuredClone(worksheet);
  let worksheetReads = 0,
    batchReads = 0;
  const proposals: unknown[] = [];
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
  await page.route(`**/workbooks/${fileHash}/worksheet`, (route) => {
    worksheetReads++;
    return route.fulfill({ json: data });
  });
  await page.route("**/api/v1/batches/123", (route) => {
    batchReads++;
    return route.fulfill({ json: { ...cleanReview, held_labels: data.sheets[1].held } });
  });
  await page.route("**/api/v1/mappings/proposals", (route) => {
    const body = route.request().postDataJSON();
    proposals.push(body);
    const field: keyof Row =
      body.kind === "ALIAS_COLOR"
        ? "color_text"
        : body.kind === "ALIAS_MODEL"
          ? "model_text"
          : "panel_label";
    data = {
      ...data,
      sheets: data.sheets.map((item) => ({
        ...item,
        rows: item.rows.map((item) =>
          item[field] === body.payload.raw_value
            ? { ...item, outcome: "ready", operator_message: "Ready to add." }
            : item,
        ),
        held: item.held.filter(
          (item) => item.raw_value !== body.payload.raw_value || item.teachable_kind !== body.kind,
        ),
      })),
    };
    return route.fulfill({ status: 201, json: { id: "chosen-spelling", ...body } });
  });
  await page.goto(`/plant/ftm?file=${fileHash}`);
  return { proposals, reads: () => ({ worksheetReads, batchReads }) };
}

test("T59 highlights held rows, filters in file order and shows picks in their cells", async ({
  page,
}) => {
  await setup(page);
  const dialog = page.getByRole("dialog").first(),
    table = dialog.getByRole("table");
  await expect(table.locator("tbody tr")).toHaveCount(10);
  const compact = table.getByRole("row").filter({ hasText: "01HOOD" });
  await expect(compact).toHaveAttribute("data-outcome", "held_out");
  await expect(compact).toHaveClass(/primary-soft/);
  await expect(table.locator('[data-outcome="ready"]')).not.toHaveClass(/primary-soft/);
  await expect(
    compact.getByRole("rowheader").getByLabel("Choose panel", { exact: true }),
  ).toBeVisible();
  await expect(
    table
      .getByRole("row")
      .filter({ hasText: "Ranjer" })
      .getByRole("cell")
      .filter({ hasText: "Ranjer" })
      .getByLabel("Choose model", { exact: true }),
  ).toBeVisible();
  await expect(table.getByLabel("Choose colour", { exact: true })).toHaveCount(2);
  for (const panel of [
    "11 Missing date",
    "Extra Film point",
    "Film model row",
    "Unlisted model row",
  ])
    await expect(table.getByRole("row").filter({ hasText: panel }).locator("select")).toHaveCount(
      0,
    );
  await expect(table.locator("input")).toHaveCount(0);
  const approve = dialog.getByRole("button", { name: "Approve", exact: true });
  await expect(approve).toBeEnabled();
  await expect(dialog.getByText("Extra tab kept. Not loaded.", { exact: true })).toBeVisible();
  await compact.evaluate((element) => element.scrollIntoView({ block: "center" }));
  await page.screenshot({
    path: "test-results/screenshots/T59-row-attention-desktop.png",
    animations: "disabled",
  });
  await dialog.getByRole("button", { name: "Need attention", exact: true }).click();
  await expect(table.locator("tbody tr")).toHaveCount(8);
  await expect(
    table.locator('[data-outcome="ready"], [data-outcome="already_in_history"]'),
  ).toHaveCount(0);
  await expect(table.locator("tbody tr td:first-child")).toHaveText([
    "2",
    "3",
    "5",
    "6",
    "8",
    "9",
    "10",
    "11",
  ]);
  await expect(dialog.getByRole("button", { name: "Need attention", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.screenshot({
    path: "test-results/screenshots/T59-need-attention-filter-desktop.png",
    animations: "disabled",
  });
  await dialog.getByRole("button", { name: "All rows", exact: true }).click();
  await expect(table.locator("tbody tr")).toHaveCount(10);
  await page.setViewportSize({ width: 390, height: 844 });
  const select = compact.getByLabel("Choose panel", { exact: true });
  await select.evaluate((element) =>
    element.scrollIntoView({ block: "center", inline: "nearest" }),
  );
  await expect(select).toBeVisible();
  await expect(approve).toBeVisible();
  await page.screenshot({
    path: "test-results/screenshots/T59-row-attention-mobile.png",
    animations: "disabled",
  });
});

for (const [kind, label, value, payload] of [
  [
    "ALIAS_COLOR",
    "Choose colour",
    "Absolute / Shadow Black",
    { raw_value: "Black", color_name: "Absolute / Shadow Black", plant_code: "FTM" },
  ],
  ["ALIAS_MODEL", "Choose model", "P703", { raw_value: "Ranjer", model_code: "P703" }],
  [
    "ALIAS_CHECKZONE",
    "Choose panel",
    "RRHOOD",
    { raw_value: "01HOOD", zone_code: "RRHOOD", plant_code: "FTM", model_code: "P703" },
  ],
] as const)
  test(`T59 ${kind} on-row pick posts once and refetches worksheet and batch`, async ({ page }) => {
    const state = await setup(page);
    const table = page.getByRole("table");
    const picker = table.getByLabel(label, { exact: true }).first();
    await expect(picker).toHaveValue("");
    await expect(picker.locator("option")).toHaveText([
      label,
      ...(kind === "ALIAS_COLOR"
        ? ["Absolute / Shadow Black", "Agate Black"]
        : kind === "ALIAS_MODEL"
          ? ["P703", "U704"]
          : ["RRHOOD", "LFFENDER"]),
    ]);
    const before = state.reads();
    await picker.selectOption(value);
    expect(state.proposals).toHaveLength(0);
    await page
      .getByRole("dialog", { name: "Confirm alias" })
      .getByRole("button", { name: `Confirm alias ${payload.raw_value} as ${value}` })
      .click();
    await expect.poll(() => state.proposals).toEqual([{ kind, load_id: 123, payload }]);
    await expect.poll(() => state.reads().worksheetReads).toBeGreaterThan(before.worksheetReads);
    await expect.poll(() => state.reads().batchReads).toBeGreaterThan(before.batchReads);
    await expect(table.getByLabel(label, { exact: true })).toHaveCount(0);
    expect(state.proposals).toHaveLength(1);
  });

test("T59 Viewer cannot pick or Approve even with ready rows", async ({ page }) => {
  const state = await setup(page, "viewer");
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  await expect(page.getByLabel(/Choose colour|Choose model|Choose panel/)).toHaveCount(0);
  expect(state.proposals).toHaveLength(0);
});

test("T59 failed on-row proposal retains message and correlationId without retry", async ({
  page,
}) => {
  await setup(page);
  let posts = 0;
  await page.route("**/api/v1/mappings/proposals", (route) => {
    posts++;
    return route.fulfill({
      status: 403,
      json: {
        statusCode: 403,
        error: "Forbidden",
        message: "Catalogue choice refused",
        correlationId: "t59-forbidden",
      },
    });
  });
  await page.getByRole("table").getByLabel("Choose panel", { exact: true }).selectOption("RRHOOD");
  await page
    .getByRole("dialog", { name: "Confirm alias" })
    .getByRole("button", { name: "Confirm alias 01HOOD as RRHOOD" })
    .click();
  const row = page.getByRole("table").getByRole("row").filter({ hasText: "01HOOD" });
  await expect(row).toContainText("Catalogue choice refused");
  await expect(row).toContainText("t59-forbidden");
  await expect(row.getByLabel("Choose panel", { exact: true })).toHaveValue("");
  expect(posts).toBe(1);
});
