/**
 * T109 in a real browser, part 2: the review row question and the two tags
 * in History. `t109-point-check.spec.ts` is Point Check itself.
 *
 * Mocked with `page.route`. What this file pins:
 *
 * * D-109-6 -- a Film label the plant's live list does not hold is asked
 *   about **in its own row**, the picker offers only the live points the
 *   server sent (with their H/V and extra tag), nothing is pre-selected, and
 *   the answer posts the label and the point;
 * * D-109-3 -- the extra tag on a review row and in History's point grid;
 * * D-109-4 -- a retired point is in the grid **because this car has a
 *   reading on it**, tagged, with every layer still shown, and the car is
 *   not incomplete.
 *
 * Screenshots: desktop and 390, written to test-results/screenshots. 390 is
 * asserted free of horizontal scroll.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { cleanReview } from "../fixtures";
import { fileHash, workbookFixture } from "../workbook-fixtures";

type Row = components["schemas"]["WorksheetRowOut"];
type Sheet = components["schemas"]["WorksheetSheetOut"];
type Vehicle = components["schemas"]["FilmVehicleOut"];
type GridPoint = components["schemas"]["FilmPointOut"];
type Choice = components["schemas"]["FilmPointChoice"];

const SHOTS = "test-results/screenshots";
const PLANT = "FTM";
const MODEL = "P703 DBL RANGER";
const LOAD_ID = 109_001;
const CAR_ID = "7".repeat(64);
const UNKNOWN = "029LTFTDOOR";

const CHOICES: Choice[] = [
  { point_no: 1, point_code: "001HOOD", orientation: "H", is_extra: false },
  { point_no: 22, point_code: "022LTFTDOOR", orientation: "V", is_extra: false },
  { point_no: 95, point_code: "095RBXFLOOR", orientation: "H", is_extra: true },
];

function row(overrides: Partial<Row> = {}): Row {
  return {
    source_sheet: "Quick Summary",
    film_tail: false,
    source_row: 15,
    panel_label: "001HOOD",
    checkzone: "001HOOD",
    model_text: null,
    model: MODEL,
    color_text: "Absolute Black",
    color: "Absolute / Shadow Black",
    date_text: "2026-08-12",
    measured_date: "2026-08-12",
    outcome: "ready",
    operator_message: "Ready to add.",
    counted: true,
    film_extra: false,
    ...overrides,
  };
}

// T109-FIX (D-109F-1): the sentence every row of a questioning tab carries.
const WAITING =
  "1 label(s) on this sheet are not points of FTM's P703 DBL RANGER walk, starting with " +
  `"${UNKNOWN}". Each one is asked about in its own row: say which live point it is and ` +
  "we remember it for every later upload, or add it as a new point on Point Check first. " +
  "Nothing on this sheet loads until every label is answered. If the walk was renumbered - " +
  "a point was taken out and the rest shifted down - do not map these labels: fix the file " +
  "and upload it again.";

/**
 * `asking`: the tab as the server sends it while a label is unanswered --
 * T109-FIX CHANGE (D-109F-1): no row is ready, the two that resolved are
 * held with the waiting sentence, and a held row carries no point, so no
 * tick and no extra tag. `asking: false` is the same tab with every label
 * answered, which is where the review's `is_extra` tag lives now.
 */
function filmSheet(asking = true): Sheet {
  const resolved = [
    row({}),
    // D-109-3: a row that resolved to an extra point says so.
    row({
      source_row: 16,
      panel_label: "095RBXFLOOR",
      checkzone: "095RBXFLOOR",
      film_extra: true,
    }),
  ];
  const waiting = resolved.map((item) =>
    row({
      ...item,
      checkzone: null,
      counted: null,
      film_extra: null,
      outcome: "held_out",
      operator_message: WAITING,
    }),
  );
  return {
    load_id: LOAD_ID,
    sheet: "Quick Summary",
    status: "PENDING_REVIEW",
    state: asking ? "needs_answer" : "ready",
    commit_blockers: [],
    rows_ready: asking ? 0 : 2,
    rows_loaded: 0,
    rows_held: asking ? 2 : 0,
    rows_already_in_history: 0,
    rows_need_confirmation: asking ? 1 : 0,
    rows: asking
      ? [
          ...waiting,
          // D-109-6: the label the live list does not hold, asked in its row.
          row({
            source_row: 17,
            panel_label: UNKNOWN,
            checkzone: null,
            counted: null,
            film_extra: null,
            outcome: "needs_confirmation",
            operator_message:
              `"${UNKNOWN}" is not a point of FTM's ${MODEL} list. Say which live point it is ` +
              "and we remember it for every later upload, or add it as a new point on Point " +
              "Check and then re-check this file. Nothing on this sheet loads until every " +
              "label is answered. If the walk was renumbered - a point was taken out and the " +
              "rest shifted down - do not map these labels: fix the file and upload it again.",
          }),
        ]
      : resolved,
    held: [],
    extra_columns: [],
    missing_optional: [],
    hole_rows: [],
    plant_texts: [],
    panel_rename: [],
    rough_panels: [],
    film_question: null,
    film_box: "box",
    film_unknown_labels: asking ? [{ raw_location: UNKNOWN, rows: 1 }] : [],
    film_point_choices: asking ? CHOICES : [],
    vehicle_count: 1,
    short_vehicles: [],
    operator_message: asking
      ? "Answer the questions for this tab first."
      : "2 readings ready to add.",
  };
}

async function openReview(page: Page, item: Sheet = filmSheet()) {
  await mockHistory(page, "engineer");
  const batch = {
    ...cleanReview.batch,
    load_id: LOAD_ID,
    plant_code: PLANT,
    file_hash: fileHash,
    source_sheet: item.sheet,
    source_file: "AW_DBL_1958197.xlsx",
    status: item.status,
    sheet_class: "FILMTHICKNESS",
    domain: "FILMTHICKNESS",
  };
  const book = {
    ...workbookFixture,
    plant_code: PLANT,
    source_file: "AW_DBL_1958197.xlsx",
    measured_date_min: "2026-08-12",
    measured_date_max: "2026-08-12",
    measured_dates_span_months: false,
    sheets: [
      {
        ...workbookFixture.sheets[0],
        batch,
        committable: false,
        commit_blockers: item.commit_blockers,
      },
    ],
  };
  await page.route(`**/api/v1/plants/${PLANT}/workbooks?*`, (route) =>
    route.fulfill({
      json: {
        plant_code: PLANT,
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
        plant_code: PLANT,
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
        rows_need_confirmation: item.rows_need_confirmation,
        summary_message: item.operator_message,
        checklist: [`${item.sheet}: ${item.operator_message}`],
      },
    }),
  );
  const answers: unknown[] = [];
  await page.route(`**/workbooks/${fileHash}/film-point-answer`, (route) => {
    answers.push(route.request().postDataJSON());
    return route.fulfill({
      json: {
        decisions_written: 1,
        replayed_load_ids: [LOAD_ID],
        operator_message: `${UNKNOWN} is 022LTFTDOOR from now on. The tab is being read again.`,
      },
    });
  });
  await page.route(`**/api/v1/batches/${LOAD_ID}`, (route) =>
    route.fulfill({ json: { ...cleanReview, batch, held_labels: [] } }),
  );
  await page.goto(`/plant/ftm?file=${fileHash}`);
  return { answers };
}

test("T109 an unknown Film label is asked in its row, with the server's live points", async ({
  page,
}) => {
  const { answers } = await openReview(page);
  await expect(page.getByRole("heading", { name: /Quick Summary/, level: 4 })).toBeVisible({
    timeout: 20000,
  });
  // The banner says what it is and what to do, in the Film words.
  const banner = page.getByTestId("film-point-summary");
  await expect(banner).toContainText("not points of this plant's list");
  await expect(banner).toContainText("remember it for every later upload");
  await expect(banner).toContainText(UNKNOWN);
  // T109-FIX (D-109F-1, D-109F-3): nothing loads until every label is
  // answered, and a renumbered walk is told not to map its labels at all.
  await expect(banner).toContainText("Nothing on this sheet loads until every label is answered");
  await expect(banner).toContainText("do not map these labels");

  // D-109F-1: the rows whose own label resolved are waiting, not ready, and
  // they say what the tab is waiting for.
  const held = page.locator('tr[data-outcome="held_out"]');
  await expect(held).toHaveCount(2);
  await expect(held.first()).toContainText("Held out");
  await expect(held.first()).toContainText("Nothing on this sheet loads");
  await expect(page.locator('tr[data-outcome="ready"]')).toHaveCount(0);

  // The question is in the row that carries the label, not below the table.
  const cell = page.getByTestId(`film-point-row-${UNKNOWN}`);
  await expect(cell).toBeVisible();
  await expect(cell).toContainText(`Which point is ${UNKNOWN}?`);
  await expect(cell).toContainText("1 row carry this label");

  // Only the server's live points, each with its H/V and its extra tag.
  const select = page.getByTestId(`film-point-select-${UNKNOWN}`);
  const options = await select.locator("option").allInnerTexts();
  expect(options[0]).toBe("Choose point");
  expect(options.some((text) => text.includes("022LTFTDOOR") && text.includes("V"))).toBe(true);
  expect(options.some((text) => text.includes("095RBXFLOOR") && text.includes("(extra)"))).toBe(
    true,
  );
  expect(options.some((text) => text.includes(UNKNOWN))).toBe(false);

  // Nothing is pre-selected, so the button cannot go until a person picks.
  const answer = page.getByTestId(`film-point-answer-${UNKNOWN}`);
  await expect(answer).toBeDisabled();
  await select.selectOption("022LTFTDOOR");
  await expect(answer).toContainText("This is 022LTFTDOOR");
  await page.screenshot({ path: `${SHOTS}/T109-review-row-question-desktop.png`, fullPage: true });
  await answer.click();
  await expect.poll(() => answers.length).toBe(1);
  expect(answers[0]).toEqual({
    load_id: LOAD_ID,
    raw_location: UNKNOWN,
    point_code: "022LTFTDOOR",
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("film-point-summary")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/T109-review-row-question-390.png`, fullPage: true });
});

test("T109 the extra tag is on the review row of a tab with every label answered", async ({
  page,
}) => {
  // D-109-3. T109-FIX CHANGE (D-109F-1): a questioning tab holds every row,
  // and a held row carries no point, so this is asserted on the same tab
  // with nothing left to answer -- which is also the only state it loads in.
  await openReview(page, filmSheet(false));
  await expect(page.getByRole("heading", { name: /Quick Summary/, level: 4 })).toBeVisible({
    timeout: 20000,
  });
  await expect(page.getByTestId("film-point-summary")).toHaveCount(0);
  await expect(page.getByTestId("row-extra-16")).toContainText("Extra");
  await expect(page.getByTestId("row-extra-15")).toHaveCount(0);
});

test("T109 History's point grid tags the extra point and the retired one", async ({ page }) => {
  await mockHistory(page, "viewer");
  const car: Vehicle = {
    logical_vehicle_id: CAR_ID,
    plant_code: PLANT,
    measured_date: "2026-08-12",
    date_is_month_only: false,
    model: MODEL,
    model_display_name: null,
    color: "Absolute / Shadow Black",
    serial_no: null,
    job_nos: ["AW_DBL_1958197"],
    identity_complete: true,
    load_ids: [41],
    source_files: ["AW_DBL_1958197.xlsx"],
    // D-109-4, section 3.3: the retired point counts on neither side, so a
    // car measured before the retirement is still complete.
    mapped_point_count: 2,
    expected_point_count: 2,
    incomplete: false,
    box: "box",
    identity_note: null,
  };
  const grid: GridPoint[] = [
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
      is_extra: false,
      retired: false,
    },
    {
      point_no: 95,
      point_code: "095RBXFLOOR",
      orientation: "H",
      src_location_text: "095RBXFLOOR",
      load_id: 41,
      source_row: 16,
      layers: { ecoat: "22.0", primer: "31.0", base: "19.0", clear: "41.0" },
      counted: true,
      is_complete_stop: false,
      is_extra: true,
      retired: false,
    },
    {
      point_no: 33,
      point_code: "033LBPILLAR",
      orientation: "V",
      src_location_text: "033LBPILLAR",
      load_id: 41,
      source_row: 17,
      layers: { ecoat: "23.0", primer: "32.0", base: "20.0", clear: "42.0" },
      counted: true,
      is_complete_stop: false,
      is_extra: false,
      // D-109-4: off the walk, kept here because this car was measured at it.
      retired: true,
    },
  ];
  await page.route("**/api/v1/plants/*/filmthickness/**", (route) => {
    const url = new URL(route.request().url());
    const common = {
      plant_code: PLANT,
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
          models: url.searchParams.has("month") ? [MODEL] : [],
          colors: url.searchParams.has("month") ? ["Absolute / Shadow Black"] : [],
        },
      });
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
                {
                  model: MODEL,
                  model_display_name: null,
                  color: "Absolute / Shadow Black",
                  vehicle_count: 1,
                  point_count: 12,
                  box_count: 1,
                  no_box_count: 0,
                  incomplete_count: 0,
                  measured_date_min: "2026-08-12",
                  measured_date_max: "2026-08-12",
                },
              ],
            },
          ],
        },
      });
    if (url.pathname.endsWith("vehicles"))
      return route.fulfill({
        json: {
          ...common,
          month: "2026-08",
          week: Number(url.searchParams.get("week")) || null,
          model: url.searchParams.get("model"),
          color: url.searchParams.get("color"),
          items: [car],
          page: { offset: 0, limit: 50, returned: 1, total: 1 },
        },
      });
    return route.fulfill({ json: { ...common, vehicle: car, items: grid } });
  });
  await page.goto(`/plant/${PLANT}?dataView=history&dataDomain=film&month=2026-08`);
  await page.getByRole("button", { name: new RegExp(MODEL) }).click();
  await page.getByRole("button", { name: /AW_DBL_1958197/ }).click();
  await expect(page).toHaveURL(new RegExp(CAR_ID));

  await expect(page.getByTestId("point-extra-095RBXFLOOR")).toContainText("Extra");
  await expect(page.getByTestId("point-retired-033LBPILLAR")).toContainText("Retired point");
  await expect(page.getByTestId("point-extra-001HOOD")).toHaveCount(0);
  await expect(page.getByTestId("point-retired-001HOOD")).toHaveCount(0);
  // The retired point's readings are still there, every layer of them.
  const retiredRow = page.locator('tr[data-point-retired="true"]');
  await expect(retiredRow).toContainText("23.0");
  await expect(retiredRow).toContainText("42.0");

  await page.screenshot({ path: `${SHOTS}/T109-history-point-tags-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("point-retired-033LBPILLAR")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: `${SHOTS}/T109-history-point-tags-390.png`, fullPage: true });
});
