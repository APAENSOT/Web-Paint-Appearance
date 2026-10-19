/**
 * T94 in a real browser: the rough-panel question is IN the table's row.
 *
 * This is the spec the task asks for by name: *"A browser spec must assert
 * the confirmation is IN THE TABLE, not in a dialog."* That is D-94-3, and
 * it is the decision the previous seven tasks got wrong -- T90's inline
 * control was built in `PanelMatchDialog`, a separate dialog reached from a
 * list *below* the table, so the screen the owner actually reviews never got
 * it.
 *
 * So every assertion below is scoped to the confirm table's own `<tr>`: the
 * select, the proposed long name already chosen, and the one click. The
 * review drawer itself is a dialog (that is the existing shell, T59), so
 * "not in a dialog" is asserted the way it means something -- the control is
 * a descendant of the row that carries the panel name, and opening it needs
 * no second screen.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { cleanReview } from "../fixtures";
import { fileHash, workbookFixture } from "../workbook-fixtures";

type Row = components["schemas"]["WorksheetRowOut"];
type Rough = components["schemas"]["RoughPanelOut"];

const HOOD: Rough = {
  raw_zone_text: "01HOOD",
  model_code: "P703 DBL RANGER",
  rows: 1,
  proposed_zone_code: "RRHOOD",
  prefilled_zone_code: null,
  confirmed_zone_code: null,
  fits_canonical: ["CFHOOD", "LFHOOD", "LRHOOD", "RFHOOD", "RRHOOD"],
  shares_name_with: ["02HOOD"],
  rule: "group_ordinal",
  attention: "red",
  reason: "this is the first time this walk has been seen",
  choosable: ["RRHOOD", "RFHOOD", "CFHOOD", "LFHOOD", "LRHOOD"],
  operator_message:
    "01HOOD does not say which panel this is: with its leading number dropped the name " +
    "fits 5 positions on this model's list (CFHOOD, LFHOOD, LRHOOD, RFHOOD, RRHOOD). " +
    "We think it is RRHOOD -- confirm it in this row and the reading loads as RRHOOD.",
};
const TGATE: Rough = {
  ...HOOD,
  raw_zone_text: "25TGATE",
  proposed_zone_code: null,
  fits_canonical: [],
  shares_name_with: ["26TGATE"],
  rule: "none",
  choosable: ["LTTAILGATE", "LBTAILGATE"],
  operator_message:
    "25TGATE does not say which panel this is, and no rule on this sheet can say which " +
    "one it is either. Pick the panel from this model's list in this row.",
};

function row(source_row: number, panel_label: string, rough: boolean): Row {
  return {
    source_sheet: "PasteData",
    film_tail: false,
    source_row,
    panel_label,
    checkzone: rough ? null : "LCPILLAR",
    model_text: "P703 DBL",
    model: "P703 DBL RANGER",
    color_text: "Ignite Orange",
    color: "Ignite Orange",
    date_text: "2026-09-14",
    measured_date: "2026-09-14",
    outcome: rough ? "needs_confirmation" : "ready",
    operator_message: rough ? `${panel_label} does not say which panel this is.` : "Ready to add.",
  };
}

const sheet: components["schemas"]["WorksheetSheetOut"] = {
  load_id: 123,
  sheet: "PasteData",
  status: "PENDING_REVIEW",
  state: "ready",
  commit_blockers: [],
  rows_ready: 1,
  rows_loaded: 0,
  rows_held: 0,
  rows_already_in_history: 0,
  rows_need_confirmation: 2,
  rows: [row(2, "01HOOD", true), row(3, "25TGATE", true), row(4, "12LCPILLAR", false)],
  held: [],
  extra_columns: [],
  missing_optional: [],
  hole_rows: [],
  plant_texts: [],
  panel_rename: [],
  rough_panels: [HOOD, TGATE],
  vehicle_count: 1,
  short_vehicles: [],
  operator_message: "1 readings ready to add.",
};
const worksheet: components["schemas"]["WorksheetOut"] = {
  plant_code: "FTM",
  file_hash: fileHash,
  source_file: "09 Sep'26 CF data FTM.xlsx",
  sheets: [sheet],
  plant_question: null,
  extra_columns: [],
  missing_optional: [],
  missing_optional_message: null,
  ready_sheet_count: 1,
  rows_ready: 1,
  rows_held: 0,
  rows_already_in_history: 0,
  rows_need_confirmation: 2,
  summary_message:
    "1 readings ready to add. 2 reading(s) name a panel that does not say which panel " +
    "it is. Confirm the panel in the row and they load under its long name (T94).",
  checklist: [],
  load_button_label: "Yes, load these rows",
};
const book = {
  ...workbookFixture,
  plant_code: "FTM",
  source_file: worksheet.source_file,
  measured_date_min: "2026-09-14",
  measured_date_max: "2026-09-14",
  measured_dates_span_months: false,
};

async function setup(page: Page) {
  await mockHistory(page, "engineer");
  let data = structuredClone(worksheet);
  const confirms: unknown[] = [];
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
  await page.route("**/api/v1/batches/123", (route) =>
    route.fulfill({ json: { ...cleanReview, held_labels: [] } }),
  );
  // The server answers the confirm by resolving those rows, which is what
  // the replay does for real (D-94-4).
  await page.route(`**/workbooks/${fileHash}/panel-confirm`, (route) => {
    const body = route.request().postDataJSON();
    confirms.push(body);
    const answered = new Map<string, string>(
      body.pairs.map((p: { raw_zone_text: string; zone_code: string }) => [
        p.raw_zone_text,
        p.zone_code,
      ]),
    );
    data = {
      ...data,
      rows_need_confirmation: data.rows_need_confirmation - answered.size,
      sheets: data.sheets.map((item) => ({
        ...item,
        rows_need_confirmation: item.rows_need_confirmation - answered.size,
        rows: item.rows.map((r) =>
          r.panel_label && answered.has(r.panel_label)
            ? {
                ...r,
                outcome: "ready" as const,
                checkzone: answered.get(r.panel_label) as string,
                operator_message: "Ready to add.",
              }
            : r,
        ),
        rough_panels: (item.rough_panels ?? []).map((p) =>
          answered.has(p.raw_zone_text)
            ? {
                ...p,
                confirmed_zone_code: answered.get(p.raw_zone_text) as string,
                attention: "yellow" as const,
                operator_message: `Confirmed as ${answered.get(p.raw_zone_text)} for this upload.`,
              }
            : p,
        ),
      })),
    };
    return route.fulfill({
      json: {
        decisions_written: answered.size,
        replayed_load_ids: [123],
        operator_message: "The tab is being read again.",
      },
    });
  });
  await page.goto(`/plant/ftm?file=${fileHash}`);
  return { confirms };
}

test("T94 asks which panel a rough label is INSIDE the table row, never in a dialog", async ({
  page,
}) => {
  await setup(page);
  const table = page.getByRole("table").filter({ hasText: "Panel as written" }).first();
  await expect(table).toBeVisible();

  const hoodRow = table.locator('tr[data-rough-panel="01HOOD"]');
  // The row that carries the name is the rough one, and only that row.
  await expect(hoodRow).toHaveCount(1);
  await expect(hoodRow).toHaveAttribute("data-outcome", "needs_confirmation");

  // D-94-2: never "Ready".
  await expect(hoodRow).not.toContainText("Ready");
  await expect(hoodRow).toContainText("Confirm the panel");

  // D-94-3: the control is a descendant of THIS ROW of THIS TABLE. If it
  // were below the table or in a second dialog, this locator finds nothing.
  const select = hoodRow.getByLabel("Which panel is 01HOOD?", { exact: true });
  await expect(select).toBeVisible();
  await expect(select).toHaveValue("RRHOOD");
  await expect(hoodRow.getByRole("option", { name: "RRHOOD (we think this one)" })).toHaveCount(1);
  for (const zone of HOOD.choosable)
    await expect(hoodRow.getByRole("option", { name: new RegExp(`^${zone}`) })).toHaveCount(1);

  // One click, in the row, naming what it will do.
  const confirm = hoodRow.getByRole("button", { name: "Confirm RRHOOD" });
  await expect(confirm).toBeVisible();

  // Highlighted, and the specific row beside it is not.
  await expect(hoodRow).toHaveClass(/primary-soft/);
  const pillar = table.getByRole("row").filter({ hasText: "12LCPILLAR" });
  await expect(pillar).toHaveAttribute("data-outcome", "ready");
  await expect(pillar).not.toHaveClass(/primary-soft/);
  await expect(pillar.locator("select")).toHaveCount(0);
});

test("T94 one click in the row stores the long name and the row says so", async ({ page }) => {
  const { confirms } = await setup(page);
  const table = page.getByRole("table").filter({ hasText: "Panel as written" }).first();
  const hoodRow = table.locator('tr[data-rough-panel="01HOOD"]');

  await hoodRow.getByRole("button", { name: "Confirm RRHOOD" }).click();

  // D-94-4: the row's resolved column now reads the long name.
  const hoodReady = table.locator('tr[data-outcome="ready"]').filter({ hasText: "01HOOD" });
  await expect(hoodReady).toHaveCount(1);
  await expect(hoodReady).toContainText("RRHOOD");
  expect(confirms).toEqual([
    { load_id: 123, pairs: [{ raw_zone_text: "01HOOD", zone_code: "RRHOOD" }] },
  ]);
});

test("T94 accepts the whole pre-filled set in one click, and only the pre-filled", async ({
  page,
}) => {
  const { confirms } = await setup(page);
  const table = page.getByRole("table").filter({ hasText: "Panel as written" }).first();

  // D-94-6: `25TGATE` has no proposal, so it is not in the one click.
  const acceptAll = page.getByTestId("rough-panel-accept-all");
  await expect(acceptAll).toHaveText("Confirm all 1 pre-filled panels");
  await acceptAll.click();

  expect(confirms).toEqual([
    { load_id: 123, pairs: [{ raw_zone_text: "01HOOD", zone_code: "RRHOOD" }] },
  ]);
  await expect(
    table.locator('tr[data-outcome="ready"]').filter({ hasText: "01HOOD" }),
  ).toContainText("RRHOOD");

  // And the one with nothing proposed still asks, in its own row, with the
  // whole list and no suggestion.
  const tgate = table.locator('tr[data-rough-panel="25TGATE"]');
  await expect(tgate).toHaveAttribute("data-outcome", "needs_confirmation");
  const select = tgate.getByLabel("Which panel is 25TGATE?", { exact: true });
  await expect(select).toHaveValue("");
  await expect(tgate.getByRole("button", { name: /^Confirm/ })).toBeDisabled();
  await select.selectOption("LTTAILGATE");
  await expect(tgate.getByRole("button", { name: "Confirm LTTAILGATE" })).toBeEnabled();
});
