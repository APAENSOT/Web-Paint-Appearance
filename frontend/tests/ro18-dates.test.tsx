/**
 * RO18: the date question (B3 / B4), "Not a point of this list" (B5) and
 * "Day not recorded" (B4).
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { components } from "../src/api/types";
import { dayRange, dayText, weekText } from "../src/features/measurements/day-text";
import { byWeek, type Car } from "../src/features/measurements/comparison-bench";
import { SheetDateQuestion } from "../src/features/measurements/SheetDateQuestion";
import { WorksheetRows } from "../src/features/measurements/ConfirmWorksheet";
import { notAPointBody } from "../src/features/measurements/film-point-questions";
import { ALIAS_KIND } from "../src/features/filmthickness/point-edit";
import { identity } from "./fixtures";
import { fileHash } from "./workbook-fixtures";

type Sheet = components["schemas"]["WorksheetSheetOut"];
type Question = components["schemas"]["SheetDateQuestion"];

function sheetWith(overrides: Partial<Sheet>): Sheet {
  return {
    load_id: 1801,
    sheet: "Quick Summary",
    status: "PENDING_REVIEW",
    state: "needs_answer",
    commit_blockers: [],
    rows_ready: 0,
    rows_loaded: 0,
    rows_held: 0,
    rows_already_in_history: 0,
    rows_need_confirmation: 0,
    rows: [],
    extra_columns: [],
    missing_optional: [],
    hole_rows: [],
    plant_texts: [],
    held: [],
    panel_rename: [],
    rough_panels: [],
    vehicle_count: 1,
    short_vehicles: [],
    operator_message: "Check this tab.",
    ...overrides,
  };
}

function client(roles?: string[]) {
  const out = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  if (roles)
    out.setQueryData(["identity"], { ...identity, principal: { ...identity.principal, roles } });
  return out;
}

function renderQuestion(question: Question, roles?: string[]) {
  return renderToStaticMarkup(
    <QueryClientProvider client={client(roles)}>
      <SheetDateQuestion
        sheet={sheetWith({ date_question: question })}
        plant="FTM"
        fileHash={fileHash}
      />
    </QueryClientProvider>,
  );
}

const MONTH: Question = {
  kind: "month",
  operator_message: "This sheet has no date anywhere.",
  suggested_month: "2026-07",
};
const DATE: Question = {
  kind: "date",
  operator_message: "The sheet says 2026-07-02 and the file name says 2026-07-20.",
  sheet_date: "2026-07-02",
  file_name_date: "2026-07-20",
};

test("dayText: a month-only date never shows the 1st", () => {
  assert.equal(dayText("2026-07-14"), "2026-07-14");
  assert.equal(dayText("2026-07-14", false), "2026-07-14");
  assert.equal(dayText("2026-07-01", true), "July 2026 — day not recorded");
  assert.equal(dayRange("2026-07-01", "2026-07-01", true), "July 2026 — day not recorded");
  assert.equal(dayRange("2026-07-01", "2026-07-09"), "2026-07-01 to 2026-07-09");
});

test("week 0 is 'Day not recorded' and sorts after the real weeks", () => {
  assert.equal(weekText(0), "Day not recorded");
  assert.equal(weekText(3), "Week 3");
  const cars = [0, 2, 1].map((week) => ({ week }) as Car);
  assert.deepEqual(
    byWeek(cars).map((group) => group.week),
    [1, 2, 0],
  );
});

test("the month question is pre-filled and enabled for an Engineer", () => {
  const html = renderQuestion(MONTH, ["engineer"]);
  assert.ok(html.includes('data-date-question="month"'));
  assert.ok(html.includes("This sheet has no date anywhere."), "the server's sentence");
  assert.match(html, /type="month"[^>]*value="2026-07"/);
  assert.doesNotMatch(html, /data-testid="date-question-month-answer"[^>]*disabled/);
});

test("the date question offers both dates", () => {
  const html = renderQuestion(DATE, ["admin"]);
  assert.ok(html.includes('data-date-question="date"'));
  assert.ok(html.includes("The sheet&#x27;s date (2026-07-02)"));
  assert.ok(html.includes("The file name&#x27;s date (2026-07-20)"));
  assert.doesNotMatch(html, /data-testid="date-question-sheet"[^>]*disabled/);
});

test("a Viewer sees the question with every control disabled", () => {
  for (const question of [MONTH, DATE]) {
    const html = renderQuestion(question, ["viewer"]);
    const controls = html.match(/<(button|input)[^>]*>/g) ?? [];
    assert.ok(controls.length >= 2);
    for (const control of controls) assert.ok(control.includes("disabled"), control);
  }
});

test("no date question, no panel", () => {
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client(["engineer"])}>
      <SheetDateQuestion
        sheet={sheetWith({ date_question: null })}
        plant="FTM"
        fileHash={fileHash}
      />
    </QueryClientProvider>,
  );
  assert.equal(html, "");
});

test("'Not a point of this list' sits in the row and posts the label as written", () => {
  const label = { raw_location: "035 LB PILLAR", rows: 2 };
  assert.deepEqual(notAPointBody(1801, label), {
    load_id: 1801,
    raw_location: "035 LB PILLAR",
  });
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client(["engineer"])}>
      <WorksheetRows
        sheet={sheetWith({
          film_unknown_labels: [label],
          film_point_choices: [],
          rows: [
            {
              source_sheet: "Quick Summary",
              source_row: 15,
              panel_label: "035 LB PILLAR",
              checkzone: null,
              model_text: null,
              model: "P703 SGL",
              color_text: "Arctic White",
              color: "Arctic White",
              date_text: "2026-07-02",
              measured_date: "2026-07-02",
              outcome: "needs_confirmation",
              operator_message: "Which point is this?",
              counted: null,
              film_tail: false,
            },
          ],
        })}
        plant="FTM"
        fileHash={fileHash}
      />
    </QueryClientProvider>,
  );
  assert.ok(html.includes('data-testid="film-not-a-point-035 LB PILLAR"'));
  assert.ok(html.includes("Not a point of this list"));
});

test("the Aliases screen names a not-a-point spelling", () => {
  assert.equal(ALIAS_KIND.not_a_point, "Not a point of this list — kept, never loaded");
});
