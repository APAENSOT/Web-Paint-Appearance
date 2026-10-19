/**
 * T94: a rough panel label is never "Ready", and the question is IN the row.
 *
 * The decisions these pin, in the order the task locks them:
 *
 * * D-94-2 -- a rough row never renders as "Ready";
 * * D-94-3 -- its control is inside `ConfirmWorksheet`'s own table row, with
 *   the proposed long name pre-selected and one click to accept, and not in a
 *   dialog;
 * * D-94-6 -- the pre-filled set is accepted in one call, and nothing is
 *   sent without a click.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { components } from "../src/api/types";
import { WorksheetRows } from "../src/features/measurements/ConfirmWorksheet";
import {
  ROUGH_PANEL_COPY,
  panelKey,
  pendingPanels,
  prefilledPairs,
  roughByLabel,
} from "../src/features/measurements/rough-panels";
import { fileHash } from "./workbook-fixtures";

type Sheet = components["schemas"]["WorksheetSheetOut"];
type RoughPanel = components["schemas"]["RoughPanelOut"];

const HOOD: RoughPanel = {
  raw_zone_text: "01HOOD",
  model_code: "P703 DBL RANGER",
  rows: 21,
  proposed_zone_code: "RRHOOD",
  prefilled_zone_code: null,
  confirmed_zone_code: null,
  fits_canonical: ["CFHOOD", "LFHOOD", "LRHOOD", "RFHOOD", "RRHOOD"],
  shares_name_with: ["02HOOD", "03HOOD", "04HOOD", "05HOOD"],
  rule: "group_ordinal",
  attention: "red",
  reason: "this is the first time this walk has been seen",
  choosable: ["RRHOOD", "RFHOOD", "CFHOOD", "LFHOOD", "LRHOOD"],
  operator_message:
    "01HOOD does not say which panel this is: with its leading number dropped the name " +
    "fits 5 positions on this model's list (CFHOOD, LFHOOD, LRHOOD, RFHOOD, RRHOOD). We " +
    "think it is RRHOOD -- confirm it in this row and the reading loads as RRHOOD.",
};

// Rough by D-94-1 (b) only, and with nothing to propose: it still asks, and
// the one click leaves it out because there is nothing pre-filled to accept.
const NO_PROPOSAL: RoughPanel = {
  ...HOOD,
  raw_zone_text: "25TGATE",
  rows: 21,
  proposed_zone_code: null,
  fits_canonical: [],
  shares_name_with: ["26TGATE", "27TGATE"],
  rule: "none",
  choosable: ["LTTAILGATE", "LBTAILGATE"],
  operator_message: "25TGATE does not say which panel this is",
};

const CONFIRMED: RoughPanel = {
  ...HOOD,
  raw_zone_text: "02HOOD",
  proposed_zone_code: "RFHOOD",
  confirmed_zone_code: "RFHOOD",
  attention: "yellow",
  operator_message: "Confirmed as RFHOOD for this upload.",
};

function sheetWith(rough: RoughPanel[], rows: Sheet["rows"]): Sheet {
  return {
    load_id: 4242,
    sheet: "PasteData",
    status: "PENDING_REVIEW",
    state: "ready",
    commit_blockers: [],
    rows_ready: 0,
    rows_loaded: 0,
    rows_held: 0,
    rows_already_in_history: 0,
    rows_need_confirmation: rows.filter((r) => r.outcome === "needs_confirmation").length,
    rows,
    extra_columns: [],
    missing_optional: [],
    hole_rows: [],
    plant_texts: [],
    held: [],
    panel_rename: [],
    rough_panels: rough,
    vehicle_count: 1,
    short_vehicles: [],
    operator_message: "Confirm the panel names.",
  };
}

function row(
  source_row: number,
  panel_label: string,
  outcome: components["schemas"]["WorksheetRowOut"]["outcome"],
  checkzone: string | null,
): components["schemas"]["WorksheetRowOut"] {
  return {
    source_sheet: "PasteData",
    film_tail: false,
    source_row,
    panel_label,
    checkzone,
    model_text: "P703 DBL",
    model: "P703 DBL RANGER",
    color_text: "Arctic White",
    color: "Arctic White",
    date_text: "2026-09-01",
    measured_date: "2026-09-01",
    outcome,
    operator_message:
      outcome === "needs_confirmation" ? "Confirm which panel this is." : "Ready to add.",
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

test("D-94-1: the questions are keyed by the file's own spelling, folded", () => {
  const sheet = sheetWith([HOOD, CONFIRMED], []);
  const byLabel = roughByLabel(sheet);
  assert.equal(byLabel.get("01hood")?.proposed_zone_code, "RRHOOD");
  assert.equal(panelKey(" 01Hood "), "01hood");
  // One sheet, two models, the same spelling: the first entry answers it.
  const twice = sheetWith([HOOD, { ...HOOD, model_code: "P703 DBL RAPTOR" }], []);
  assert.equal(roughByLabel(twice).size, 1);
});

test("D-94-6: only a pending panel that carries a proposal is pre-filled", () => {
  const sheet = sheetWith([HOOD, NO_PROPOSAL, CONFIRMED], []);
  assert.deepEqual(
    pendingPanels(sheet).map((p) => p.raw_zone_text),
    ["01HOOD", "25TGATE"],
    "a confirmed panel is no longer pending",
  );
  assert.deepEqual(prefilledPairs(sheet), [{ raw_zone_text: "01HOOD", zone_code: "RRHOOD" }]);
});

test("D-94-2: a rough row is never Ready, and says what it needs instead", () => {
  const html = render(
    sheetWith(
      [HOOD],
      [row(2, "01HOOD", "needs_confirmation", null), row(3, "12LCPILLAR", "ready", "LCPILLAR")],
    ),
  );
  assert.match(html, /Confirm the panel/, "the outcome cell says what it needs");
  assert.match(html, /data-outcome="needs_confirmation"/);
  // "Ready" appears for the specific row only, never on the rough one.
  const roughRow = html.slice(html.indexOf('data-rough-panel="01HOOD"'));
  const roughCell = roughRow.slice(0, roughRow.indexOf("</tr>"));
  assert.doesNotMatch(roughCell, />Ready</, "a rough row is never Ready (D-94-2)");
});

test("D-94-3: the control is in the row, pre-selected, one click, no dialog", () => {
  const html = render(sheetWith([HOOD], [row(2, "01HOOD", "needs_confirmation", null)]));

  // In the table: the control markup sits inside the row that carries the name.
  const start = html.indexOf('data-rough-panel="01HOOD"');
  assert.ok(start > 0, "the row itself is marked as the rough one");
  const rowHtml = html.slice(start, html.indexOf("</tr>", start));
  assert.match(rowHtml, /data-testid="rough-panel-row-01HOOD"/, "the control is IN the row");
  assert.match(rowHtml, /Which panel is 01HOOD\?/);
  assert.match(rowHtml, /data-testid="rough-panel-confirm-01HOOD"/, "one click, in the row");

  // Pre-selected: the proposal is the select's value, and it is named as ours.
  const select = rowHtml.slice(rowHtml.indexOf("<select"));
  assert.match(
    select,
    /<option value="RRHOOD" selected="">RRHOOD \(we think this one\)/,
    "the proposal is the selected option and is named as ours",
  );
  assert.match(rowHtml, /Confirm RRHOOD/, "one click accepts the proposal");
  // The whole choosable list is there, not only the proposal.
  for (const zone of HOOD.choosable) assert.match(select, new RegExp(`value="${zone}"`));

  // Highlighted.
  assert.match(rowHtml, /border-l-primary/);

  // And not in a dialog: nothing in this component opens one for it.
  assert.doesNotMatch(html, /role="dialog"/);
});

test("D-94-6: the accept-all bar offers exactly the pre-filled count", () => {
  const html = render(
    sheetWith(
      [HOOD, NO_PROPOSAL],
      [row(2, "01HOOD", "needs_confirmation", null), row(3, "25TGATE", "needs_confirmation", null)],
    ),
  );
  assert.match(html, /data-testid="rough-panel-accept-all"/);
  assert.match(html, /Confirm all 1 pre-filled panels/, "25TGATE has nothing to pre-fill");
  assert.match(html, new RegExp(ROUGH_PANEL_COPY.heading));
});

test("a sheet with no rough panel shows no question at all", () => {
  const html = render(sheetWith([], [row(2, "12LCPILLAR", "ready", "LCPILLAR")]));
  assert.doesNotMatch(html, /rough-panel-summary/);
  assert.doesNotMatch(html, /rough-panel-row-/);
  assert.match(html, />Ready</);
});
