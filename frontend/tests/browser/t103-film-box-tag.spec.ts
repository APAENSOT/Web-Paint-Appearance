/**
 * T103 in a real browser: the Box / No box tag, and two honest sentences.
 *
 * Mocked with `page.route` -- the live tag counts are a GET-only check in the
 * backend's own report, and nothing here uploads. What this pins:
 *
 * * D-103-3 -- the tag is in all three places: the History vehicle list, the
 *   History point-grid header, and the review's Film sheet header;
 * * D-103-1 -- the client decides nothing. A car whose `box` is null (a
 *   plant whose list names no complete stop) shows no tag at all, and a
 *   held Film tab with no `film_box` shows none either;
 * * D-103-6 -- `identity_note` is rendered where a person will find it;
 * * D-103-4 -- the refused no-name sheet shows the server's own sentence,
 *   with no Admin / mapping wording and no mapping action.
 *
 * Screenshots: desktop and 390, written to test-results/screenshots. 390 is
 * asserted free of horizontal scroll.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { cleanReview } from "../fixtures";
import { fileHash, workbookFixture } from "../workbook-fixtures";

const SHOTS = "test-results/screenshots";

type Vehicle = components["schemas"]["FilmVehicleOut"];
type Point = components["schemas"]["FilmPointOut"];
type Row = components["schemas"]["WorksheetRowOut"];
type Sheet = components["schemas"]["WorksheetSheetOut"];

const BOX_ID = "1".repeat(64);
const NO_BOX_ID = "2".repeat(64);
const NO_TAG_ID = "3".repeat(64);
const LOAD_ID = 103_001;

const NOTE =
  'The Job Number\'s colour code "AM" and the file name\'s "AW" are different. ' +
  'The colour loaded is the one Layer 2 names: "Arctic White".';

function vehicle(overrides: Partial<Vehicle>): Vehicle {
  return {
    logical_vehicle_id: BOX_ID,
    plant_code: "FTM",
    measured_date: "2026-08-12",
    date_is_month_only: false,
    model: "P703 DBL RANGER",
    model_display_name: null,
    color: "Absolute / Shadow Black",
    serial_no: null,
    job_nos: ["AW_DBL_1958197"],
    identity_complete: true,
    load_ids: [41],
    source_files: ["AW_DBL_1958197.xlsx"],
    mapped_point_count: 98,
    expected_point_count: 98,
    incomplete: false,
    box: "box",
    identity_note: null,
    ...overrides,
  };
}

const VEHICLES: Vehicle[] = [
  vehicle({}),
  vehicle({
    logical_vehicle_id: NO_BOX_ID,
    job_nos: ["AM_SGL_1961607"],
    model: "P703 SGL",
    model_display_name: "Single CAP",
    color: "Arctic White",
    mapped_point_count: 58,
    expected_point_count: 58,
    box: "no_box",
    identity_note: NOTE,
  }),
  vehicle({
    logical_vehicle_id: NO_TAG_ID,
    plant_code: "FTM",
    job_nos: ["AAT-NO-LIST"],
    mapped_point_count: 3,
    expected_point_count: 94,
    incomplete: true,
    // A plant x model whose list names no complete stop: there is no box
    // section, so the server says nothing and the screen shows nothing.
    box: null,
  }),
];

type FilmCard = components["schemas"]["FilmCardOut"];

function card(overrides: Partial<FilmCard>): FilmCard {
  return {
    model: "P703 DBL RANGER",
    model_display_name: null,
    color: "Absolute / Shadow Black",
    vehicle_count: 2,
    point_count: 404,
    box_count: 1,
    no_box_count: 0,
    incomplete_count: 1,
    measured_date_min: "2026-08-12",
    measured_date_max: "2026-08-12",
    ...overrides,
  };
}

const POINTS: Point[] = [
  {
    point_no: 1,
    point_code: "001HOOD",
    orientation: "H",
    src_location_text: "001HOOD",
    load_id: 41,
    source_row: 15,
    layers: { ecoat: "21.4", primer: "30.3", base: "18.2", clear: "40.1" },
    counted: true,
    is_complete_stop: false,
    // T109: a live point of the plant's standard list.
    is_extra: false,
    retired: false,
  },
  {
    point_no: 65,
    point_code: "065LBOXSIDE",
    orientation: "V",
    src_location_text: "065LBOXSIDE",
    load_id: 41,
    source_row: 79,
    layers: { ecoat: "22.0", primer: "31.0", base: "19.0", clear: "41.0" },
    counted: true,
    is_complete_stop: false,
    // T109: a live point of the plant's standard list.
    is_extra: false,
    retired: false,
  },
];

async function mockFilmHistory(page: Page) {
  await page.route("**/api/v1/plants/*/filmthickness/**", (route) => {
    const url = new URL(route.request().url());
    const common = {
      plant_code: "FTM",
      plant_is_active: true,
      active_data_source: "filmthickness_active",
    };
    if (url.pathname.endsWith("facets"))
      return route.fulfill({
        json: {
          ...common,
          default_month: "2026-08",
          months: ["2026-08"],
          month: url.searchParams.get("month"),
          model: url.searchParams.get("model"),
          color: url.searchParams.get("color"),
          models: url.searchParams.has("month") ? ["P703 DBL RANGER", "P703 SGL"] : [],
          colors: url.searchParams.has("month") ? ["Arctic White"] : [],
        },
      });
    // T108: the flat grid became week cards. One card per (week, model,
    // colour), so the three cars sit under two cards -- and the card read is
    // where their Box / No box counts come from.
    if (url.pathname.endsWith("summaries"))
      return route.fulfill({
        json: {
          ...common,
          month: url.searchParams.get("month"),
          model: url.searchParams.get("model"),
          color: url.searchParams.get("color"),
          weeks: [
            {
              week: 2,
              measured_date_min: "2026-08-12",
              measured_date_max: "2026-08-12",
              cards: [
                card({}),
                card({
                  model: "P703 SGL",
                  model_display_name: "Single CAP",
                  color: "Arctic White",
                  vehicle_count: 1,
                  box_count: 0,
                  no_box_count: 1,
                  incomplete_count: 0,
                }),
              ],
            },
          ],
        },
      });
    if (url.pathname.endsWith("vehicles")) {
      // The cars of the card that was clicked: this mock answers with the
      // cars of the asked-for model, as the server's `model` filter does.
      const asked = url.searchParams.get("model");
      const items = asked ? VEHICLES.filter((item) => item.model === asked) : VEHICLES;
      return route.fulfill({
        json: {
          ...common,
          month: "2026-08",
          week: Number(url.searchParams.get("week")) || null,
          model: asked,
          color: url.searchParams.get("color"),
          items,
          page: { offset: 0, limit: 50, returned: items.length, total: items.length },
        },
      });
    }
    const id = url.pathname.split("/").at(-2);
    return route.fulfill({
      json: {
        ...common,
        vehicle: VEHICLES.find((item) => item.logical_vehicle_id === id) ?? VEHICLES[0],
        items: POINTS,
      },
    });
  });
}

// =====================================================================
// History: the list and the point-grid header
// =====================================================================
test("T103 History shows the Box / No box tag, the note, and nothing when null", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  await mockFilmHistory(page);
  await page.goto("/plant/FTM?dataView=history&dataDomain=film&month=2026-08");
  await expect(page.getByRole("heading", { name: "Film Thickness" })).toBeVisible();
  // T108: the cars live behind their week card, and the card carries the
  // server's counts of the same tags. The Ranger card holds the Box car and
  // the car with no tag; the Single CAP card holds the No box one.
  const ranger = page.getByRole("button", { name: /P703 DBL RANGER/ });
  await expect(ranger).toContainText("Box 1");
  await expect(ranger).toContainText("No box 0");
  await expect(ranger).toContainText("Incomplete 1");
  await ranger.click();

  const boxCar = page.getByRole("button", { name: /AW_DBL_1958197/ });
  const noTagCar = page.getByRole("button", { name: /AAT-NO-LIST/ });
  await expect(boxCar.getByTestId("film-box-box")).toHaveText("Box");
  await expect(noTagCar.getByTestId("film-box-box")).toHaveCount(0);
  await expect(noTagCar.getByTestId("film-box-no_box")).toHaveCount(0);
  await expect(boxCar).not.toContainText("colour code");

  await page.getByRole("button", { name: "Back to week cards" }).click();
  const single = page.getByRole("button", { name: /Single CAP/ });
  await expect(single).toContainText("No box 1");
  await single.click();
  const noBoxCar = page.getByRole("button", { name: /AM_SGL_1961607/ });
  await expect(noBoxCar.getByTestId("film-box-no_box")).toHaveText("No box");

  // D-103-6: the warning the rows carried when they loaded, on the car.
  await expect(noBoxCar).toContainText('colour code "AM"');

  // The point-grid header for one car says the same thing.
  await noBoxCar.click();
  await expect(page).toHaveURL(new RegExp(NO_BOX_ID));
  const grid = page.getByRole("heading", { name: /Catalogue points/ });
  await expect(grid.getByTestId("film-box-no_box")).toHaveText("No box");
  await expect(page.getByText('colour code "AM"').first()).toBeVisible();

  await page.screenshot({ path: `${SHOTS}/T103-history-film-tags-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(grid.getByTestId("film-box-no_box")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: `${SHOTS}/T103-history-film-tags-390.png`, fullPage: true });
});

test("T103 the point grid of a Box car carries the Box tag", async ({ page }) => {
  await mockHistory(page, "viewer");
  await mockFilmHistory(page);
  await page.goto("/plant/FTM?dataView=history&dataDomain=film&month=2026-08");
  // T108: through the week card, then the car.
  await page.getByRole("button", { name: /P703 DBL RANGER/ }).click();
  await page.getByRole("button", { name: /AW_DBL_1958197/ }).click();
  await expect(page).toHaveURL(new RegExp(BOX_ID));
  const grid = page.getByRole("heading", { name: /Catalogue points/ });
  await expect(grid.getByTestId("film-box-box")).toHaveText("Box");
  await page.screenshot({ path: `${SHOTS}/T103-film-point-grid-box-desktop.png`, fullPage: true });
});

// =====================================================================
// The review: the sheet header, and the refusal that names itself
// =====================================================================
function row(overrides: Partial<Row> = {}): Row {
  return {
    source_sheet: "Quick Summary",
    film_tail: false,
    source_row: 15,
    panel_label: "001HOOD",
    checkzone: "001HOOD",
    model_text: null,
    model: "P703 DBL RANGER",
    color_text: "Absolute Black",
    color: "Absolute / Shadow Black",
    date_text: "2026-08-12",
    measured_date: "2026-08-12",
    outcome: "ready",
    operator_message: "Ready to add.",
    counted: true,
    ...overrides,
  };
}

function sheet(overrides: Partial<Sheet> = {}): Sheet {
  return {
    load_id: LOAD_ID,
    sheet: "Quick Summary",
    status: "PENDING_REVIEW",
    state: "ready",
    commit_blockers: [],
    rows_ready: 2,
    rows_loaded: 0,
    rows_held: 0,
    rows_already_in_history: 0,
    rows_need_confirmation: 0,
    rows: [
      row({}),
      row({ source_row: 16, panel_label: "065LBOXSIDE", checkzone: "065LBOXSIDE" }),
      row({
        source_row: 21,
        panel_label: "001FTWISH",
        checkzone: null,
        counted: null,
        outcome: "held_out",
        film_tail: true,
        operator_message: '"001FTWISH" is the known tail of FTM\'s P703 DBL RANGER walk.',
      }),
    ],
    held: [],
    extra_columns: [],
    missing_optional: [],
    hole_rows: [],
    plant_texts: [],
    panel_rename: [],
    rough_panels: [],
    film_question: null,
    film_box: "box",
    vehicle_count: 1,
    short_vehicles: [],
    operator_message: "2 readings ready to add, 1 not stored (walk tail).",
    ...overrides,
  };
}

const REFUSAL =
  "Sheet [Quick Summary] names no points: every Location on it is a placeholder " +
  'like "Point 001". We cannot tell which point of FTM each reading is, and we ' +
  "never guess one from walk order. Nothing was loaded from this file. Upload " +
  "the report that writes the point names.";

async function openReview(page: Page, item: Sheet) {
  await mockHistory(page, "engineer");
  const batch = {
    ...cleanReview.batch,
    load_id: LOAD_ID,
    plant_code: "FTM",
    file_hash: fileHash,
    source_sheet: item.sheet,
    source_file: "AW_DBL_1958197.xlsx",
    status: item.status,
    sheet_class: "FILMTHICKNESS",
    domain: "FILMTHICKNESS",
  };
  const book = {
    ...workbookFixture,
    plant_code: "FTM",
    source_file: "AW_DBL_1958197.xlsx",
    measured_date_min: "2026-08-12",
    measured_date_max: "2026-08-12",
    measured_dates_span_months: false,
    sheets: [
      {
        ...workbookFixture.sheets[0],
        batch,
        committable: item.state === "ready",
        commit_blockers: item.commit_blockers,
      },
    ],
  };
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
  await page.route(`**/workbooks/${fileHash}/worksheet`, (route) =>
    route.fulfill({
      json: {
        plant_code: "FTM",
        file_hash: fileHash,
        source_file: "AW_DBL_1958197.xlsx",
        sheets: [item],
        plant_question: null,
        extra_columns: [],
        missing_optional: [],
        missing_optional_message: null,
        ready_sheet_count: item.state === "ready" ? 1 : 0,
        rows_ready: item.rows_ready,
        rows_held: item.rows_held,
        rows_already_in_history: item.rows_already_in_history,
        rows_need_confirmation: 0,
        summary_message: item.operator_message,
        checklist: [`${item.sheet}: ${item.operator_message}`],
      },
    }),
  );
  await page.route(`**/api/v1/batches/${LOAD_ID}`, (route) =>
    route.fulfill({ json: { ...cleanReview, batch, held_labels: [] } }),
  );
  await page.goto(`/plant/ftm?file=${fileHash}`);
}

test("T103 the review's Film sheet header carries the tag, and the tail is not held out", async ({
  page,
}) => {
  await openReview(page, sheet());
  const header = page.getByRole("heading", { name: /Quick Summary/, level: 4 });
  await expect(header).toBeVisible({ timeout: 15000 });
  await expect(header.getByTestId("film-box-box")).toHaveText("Box");
  await expect(page.getByText("1 not stored (walk tail)").first()).toBeVisible();
  // The sheet's own sentence never calls the tail "held out" (D-103-5). The
  // header's "0 held out" counter is a different thing and still correct.
  await expect(
    page.getByText("2 readings ready to add, 1 not stored (walk tail).").first(),
  ).toBeVisible();
  await expect(page.getByText(/\d+ held out[,.]/)).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/T103-review-film-box-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(header.getByTestId("film-box-box")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: `${SHOTS}/T103-review-film-box-390.png`, fullPage: true });
});

test("T103 a held Film tab carries no tag", async ({ page }) => {
  await openReview(
    page,
    sheet({
      state: "needs_answer",
      rows_ready: 0,
      rows_held: 3,
      film_box: null,
      operator_message: "Answer the questions for this tab first.",
    }),
  );
  const header = page.getByRole("heading", { name: /Quick Summary/, level: 4 });
  await expect(header).toBeVisible({ timeout: 15000 });
  await expect(header.getByTestId("film-box-box")).toHaveCount(0);
  await expect(header.getByTestId("film-box-no_box")).toHaveCount(0);
});

test("T103 the refused no-name sheet says why, and offers no mapping", async ({ page }) => {
  await openReview(
    page,
    sheet({
      status: "REJECTED_TEMPLATE",
      state: "blocked",
      commit_blockers: ["NOT_PENDING_REVIEW", "UNKNOWN_TEMPLATE"],
      rows_ready: 0,
      rows: [],
      film_box: null,
      operator_message: REFUSAL,
    }),
  );
  await expect(page.getByText("names no points").first()).toBeVisible({ timeout: 15000 });
  await expect(
    page.getByText("Upload the report that writes the point names").first(),
  ).toBeVisible();
  // D-103-4: nothing on this screen tells the operator to wait for an Admin,
  // and nothing offers a mapping -- no approval can ever load this file.
  await expect(page.getByText("waiting for an Admin")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /mapping/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Publish/i })).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/T103-review-refusal-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: `${SHOTS}/T103-review-refusal-390.png`, fullPage: true });
});
