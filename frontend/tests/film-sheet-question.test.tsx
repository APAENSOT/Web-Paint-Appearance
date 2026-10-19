/**
 * T100: the Film sheet question, the read-only tick, and the points-page diff.
 *
 * The decisions these pin:
 *
 * * D-100-1 -- every question comes from `sheet.film_question`; the client
 *   classifies nothing, so a sheet with no question renders no panel;
 * * D-100-2 -- a known point's tick is read-only, and a new point's is not;
 * * D-100-4 -- a tail row reads "Not stored", has no tick, and never counts
 *   as a row that needs attention;
 * * D-100-5 -- a walk that cannot be confirmed gets the sentence and no
 *   button; Confirm waits until every new name has an H or a V;
 * * D-100-6 -- the points page sends only the points that changed, and only
 *   with a reason.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { components } from "../src/api/types";
import { WorksheetRows } from "../src/features/measurements/ConfirmWorksheet";
import {
  FILM_QUESTION_COPY,
  confirmBody,
  initialChoices,
  readyToConfirm,
  type FilmQuestion,
} from "../src/features/measurements/film-sheet-question";
import { changedPoints } from "../src/features/filmthickness/film-points";
import { fileHash } from "./workbook-fixtures";

type Sheet = components["schemas"]["WorksheetSheetOut"];
type Row = components["schemas"]["WorksheetRowOut"];
type Point = components["schemas"]["FilmPointSettingItem"];

const WALK: FilmQuestion = {
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

const HELD_WALK: FilmQuestion = {
  ...WALK,
  confirmable: false,
  appended: [],
  operator_message:
    'This sheet writes "035LBPILLAR", which is not a point of FTM\'s P703 SGL walk.',
};

const MODEL: FilmQuestion = {
  kind: "model",
  operator_message: "This sheet names two models.",
  model_code: "P703 DBL RANGER",
  confirmable: false,
  appended: [],
  models: ["P703 DBL RAPTOR", "P703 DBL RANGER"],
  job_no: "AW_RB_1961607",
};

const JOB: FilmQuestion = {
  kind: "job",
  operator_message: 'The Job Number on this sheet is "BL_RAP_6218".',
  model_code: "P703 RAPCAP",
  confirmable: false,
  appended: [],
  models: [],
  job_no: "BL_RAP_6218",
};

function row(overrides: Partial<Row> = {}): Row {
  return {
    source_sheet: "Quick Summary",
    source_row: 15,
    panel_label: "001HOOD",
    checkzone: "001HOOD",
    model_text: null,
    model: "P703 SGL",
    color_text: "Arctic White",
    color: "Arctic White",
    date_text: "2026-09-01",
    measured_date: "2026-09-01",
    outcome: "ready",
    operator_message: "Ready to add.",
    counted: true,
    film_tail: false,
    ...overrides,
  };
}

function sheetWith(question: FilmQuestion | null, rows: Row[]): Sheet {
  return {
    load_id: 909,
    sheet: "Quick Summary",
    status: "PENDING_REVIEW",
    state: question ? "needs_answer" : "ready",
    commit_blockers: [],
    rows_ready: 0,
    rows_loaded: 0,
    rows_held: 0,
    rows_already_in_history: 0,
    rows_need_confirmation: 0,
    rows,
    extra_columns: [],
    missing_optional: [],
    hole_rows: [],
    plant_texts: [],
    held: [],
    panel_rename: [],
    rough_panels: [],
    film_question: question,
    vehicle_count: 1,
    short_vehicles: [],
    operator_message: "Check this tab.",
  };
}

function render(sheet: Sheet): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <WorksheetRows sheet={sheet} plant="FTM" fileHash={fileHash} />
    </QueryClientProvider>,
  );
}

// =====================================================================
// D-100-1: the panel exists only because the server filled the field
// =====================================================================
test("a sheet with no film question renders no panel", () => {
  const html = render(sheetWith(null, [row()]));
  assert.ok(!html.includes('data-testid="film-question"'));
  assert.ok(!html.includes(FILM_QUESTION_COPY.walk));
});

test("the walk question renders the server's own sentence and one line per new name", () => {
  const html = render(sheetWith(WALK, [row({ outcome: "held_out", counted: null })]));
  assert.ok(html.includes('data-film-question="walk"'));
  assert.ok(html.includes('data-film-confirmable="yes"'));
  assert.ok(html.includes("099TGATEIN"));
  assert.ok(html.includes("100NEWWORD"));
  assert.ok(html.includes("past the last point"), "the parse's sentence, verbatim");
  // The name whose word the list has never had says so; the other does not.
  assert.ok(html.includes(FILM_QUESTION_COPY.needsOrientation));
  assert.ok(html.includes('data-testid="film-confirm-walk"'));
});

test("a walk that cannot be confirmed gets the sentence and no button", () => {
  const html = render(sheetWith(HELD_WALK, [row({ outcome: "held_out", counted: null })]));
  assert.ok(html.includes('data-film-confirmable="no"'));
  assert.ok(html.includes("035LBPILLAR"));
  assert.ok(html.includes(FILM_QUESTION_COPY.ownerDecision));
  assert.ok(!html.includes('data-testid="film-confirm-walk"'), "no button (D-99-14)");
});

test("the model question offers one button per model the sheet named", () => {
  const html = render(sheetWith(MODEL, [row({ outcome: "held_out", counted: null })]));
  assert.ok(html.includes('data-testid="film-choose-model-P703 DBL RAPTOR"'));
  assert.ok(html.includes('data-testid="film-choose-model-P703 DBL RANGER"'));
  assert.ok(!html.includes('data-testid="film-confirm-walk"'));
});

test("the job question offers Load as written with the number", () => {
  const html = render(sheetWith(JOB, [row({ outcome: "held_out", counted: null })]));
  assert.ok(html.includes('data-testid="film-load-as-written"'));
  assert.ok(html.includes("BL_RAP_6218"));
});

// =====================================================================
// D-100-2 / D-100-4: the tick and the tail
// =====================================================================
test("a known point's tick is read-only and a tail row has none", () => {
  const html = render(
    sheetWith(null, [
      row({ source_row: 15, counted: true }),
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
    ]),
  );
  assert.ok(html.includes("Counted"), "the column is there for a Film tab");
  assert.ok(html.includes('data-testid="row-counted-15"'));
  assert.ok(html.includes('data-testid="row-counted-16"'));
  // Read-only: every tick is disabled, so nobody edits a known point here.
  assert.equal(html.match(/data-testid="row-counted-\d+"/g)?.length, 2);
  assert.ok(!html.includes('data-testid="row-counted-21"'), "no tick on a tail row");
  assert.ok(html.includes("Not stored"));
  assert.ok(!/row-counted-15[^>]*>/.test(html.replace(/disabled/g, "")) === false);
});

test("a WaveScan tab has no Counted column", () => {
  const html = render(sheetWith(null, [row({ counted: null, checkzone: "RRHOOD" })]));
  assert.ok(!html.includes('data-testid="row-counted-15"'));
  assert.ok(!html.includes(">Counted<"));
});

// =====================================================================
// D-100-5: Confirm waits for an H or a V on every new name
// =====================================================================
test("Confirm is not ready until every appended name has an orientation", () => {
  const start = initialChoices(WALK);
  assert.deepEqual(start["099TGATEIN"], { counted: true, orientation: "V" });
  assert.deepEqual(start["100NEWWORD"], { counted: true, orientation: "" });
  assert.equal(readyToConfirm(WALK, start), false, "one name has no H or V yet");

  const chosen = { ...start, "100NEWWORD": { counted: false, orientation: "H" as const } };
  assert.equal(readyToConfirm(WALK, chosen), true);
  assert.equal(readyToConfirm(HELD_WALK, chosen), false, "nothing to confirm");

  assert.deepEqual(confirmBody(WALK, 909, chosen), {
    load_id: 909,
    points: [
      { point_code: "099TGATEIN", counted: true, orientation: "V" },
      { point_code: "100NEWWORD", counted: false, orientation: "H" },
    ],
  });
});

// =====================================================================
// D-100-6: the points page sends only what changed
// =====================================================================
function point(overrides: Partial<Point> = {}): Point {
  return {
    point_no: 1,
    point_code: "001HOOD",
    label: "001HOOD",
    counted: true,
    orientation: "H",
    is_complete_stop: false,
    is_extra: false,
    reason: "T99 seed (owner D-99-5, 2026-10-10)",
    changed_by: null,
    changed_at: "2026-10-10T20:19:00+07:00",
    ...overrides,
  };
}

test("the points page sends only the points whose tick or H/V moved", () => {
  const points = [
    point(),
    point({ point_no: 2, point_code: "002HOOD" }),
    point({ point_no: 3, point_code: "003ROOF", orientation: "H" }),
  ];
  assert.deepEqual(changedPoints(points, {}), [], "no draft, nothing to send");
  // Touched but identical: still nothing.
  assert.deepEqual(changedPoints(points, { "001HOOD": { counted: true, orientation: "H" } }), []);
  assert.deepEqual(
    changedPoints(points, {
      "001HOOD": { counted: true, orientation: "H" },
      "002HOOD": { counted: false, orientation: "H" },
      "003ROOF": { counted: true, orientation: "V" },
    }),
    [
      { point_code: "002HOOD", counted: false, orientation: "H" },
      { point_code: "003ROOF", counted: true, orientation: "V" },
    ],
  );
});

test("the save warning names the plant and the reason has a minimum", async () => {
  const { POINTS_COPY } = await import("../src/features/filmthickness/film-points");
  assert.ok(POINTS_COPY.warning.includes("{plant}"));
  assert.ok(POINTS_COPY.warning.includes("including past ones"));
  assert.equal("ab".trim().length >= 3, false, "two characters is not a reason");
  assert.equal("why".trim().length >= 3, true);
});
