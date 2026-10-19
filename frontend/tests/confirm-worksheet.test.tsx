import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { components } from "../src/api/types";
import { checkzoneAliasPayload } from "../src/api/mapping-state";
import { ConfirmWorksheet, WorksheetRows } from "../src/features/measurements/ConfirmWorksheet";
import {
  EMPTY_IDENTITY_COPY,
  IGNORE_COPY,
  emptyIdentityCopy,
} from "../src/features/measurements/review-copy";
import { identity } from "./fixtures";
import { canTeach, heldAliasProposal } from "../src/features/measurements/held-alias";
import { workbookFixture, fileHash } from "./workbook-fixtures";

const held: components["schemas"]["HeldLabelGroup"] = {
  reason: "UNKNOWN_COLOR",
  column: "color",
  raw_value: "Black",
  count: 2,
  teachable_kind: "ALIAS_COLOR",
  candidates: ["Absolute / Shadow Black", "Agate Black"],
  display_group: "colour",
  operator_message: "Pick the official catalogue colour.",
};
const worksheet: components["schemas"]["WorksheetOut"] = {
  plant_code: "AAT",
  file_hash: fileHash,
  source_file: "review.xlsx",
  plant_question: null,
  extra_columns: ["Panel2"],
  missing_optional: ["doi"],
  missing_optional_message: "This file has no DOI column. Rows can still load with DOI empty.",
  ready_sheet_count: 1,
  rows_ready: 10,
  rows_held: 2,
  rows_already_in_history: 1,
  rows_need_confirmation: 0,
  summary_message: "10 readings ready to add, 2 held out, 1 already in History.",
  checklist: [],
  load_button_label: "Yes, load these rows",
  sheets: [
    {
      load_id: workbookFixture.sheets[0].batch.load_id,
      sheet: "Absolute / Shadow Black",
      status: "PENDING_REVIEW",
      state: "ready",
      commit_blockers: [],
      rows_ready: 10,
      rows_loaded: 0,
      rows_held: 2,
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
        {
          source_sheet: "Absolute / Shadow Black",
          film_tail: false,
          source_row: 4,
          panel_label: "06 LFFender",
          checkzone: "LFFENDER",
          model_text: "Ranger",
          model: "P703",
          color_text: "Black",
          color: "Absolute / Shadow Black",
          date_text: "7 June 2026",
          measured_date: "2026-06-07",
          outcome: "held_out",
          operator_message: "The other copy is added; this one is kept as a record.",
        },
      ],
      extra_columns: ["Panel2"],
      missing_optional: ["doi"],
      hole_rows: [],
      plant_texts: [],
      held: [held],
      vehicle_count: 1,
      short_vehicles: [],
      operator_message: "Ten rows can load. Two remain held.",
    },
  ],
};

function renderWorksheet(data: components["schemas"]["WorksheetOut"]) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], identity);
  client.setQueryData(["worksheet", "AAT", fileHash], data);
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ConfirmWorksheet code="AAT" hash={fileHash} workbook={workbookFixture} onLoaded={() => {}} />
    </QueryClientProvider>,
  );
  client.clear();
  return html;
}

test("evidence-only cover tab does not block ready colour rows", () => {
  const cover: components["schemas"]["WorksheetSheetOut"] = {
    ...worksheet.sheets[0],
    load_id: 999,
    sheet: "Instructions",
    status: "REJECTED_TEMPLATE",
    state: "not_wavescan",
    commit_blockers: ["REJECTED_TEMPLATE"],
    rows_ready: 0,
    rows_held: 0,
    held: [],
    rows: [],
    rows_already_in_history: 0,
    rows_need_confirmation: 0,
    operator_message: "Extra tab kept. Not loaded.",
  };
  const html = renderWorksheet({
    ...worksheet,
    extra_columns: [],
    sheets: [cover, worksheet.sheets[0]],
  });
  assert.match(html, /Instructions/);
  assert.match(html, /Extra tab kept\. Not loaded\./);
  assert.doesNotMatch(html, /Advanced layout details|Propose mapping/);
  assert.match(html, /<button[^>]*>Approve<\/button>/);
});

test("extra columns disable Yes until Ignore is answered", () => {
  const html = renderWorksheet(worksheet);
  assert.match(html, /Review ignored columns/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>Approve<\/button>/);
});

test("whole-file checklist uses exact action copy and both official colour candidates", () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], {
    ...identity,
    principal: { ...identity.principal, roles: ["engineer"] },
  });
  client.setQueryData(["worksheet", "AAT", fileHash], worksheet);
  client.setQueryData(["batch", worksheet.sheets[0].load_id], { held_labels: [held] });
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ConfirmWorksheet code="AAT" hash={fileHash} workbook={workbookFixture} onLoaded={() => {}} />
    </QueryClientProvider>,
  );
  assert.match(html, /Confirm this worksheet/);
  assert.ok(html.includes(IGNORE_COPY));
  assert.match(html, />Approve<\/button>/);
  assert.match(html, /This file has no DOI column/);
  assert.ok(html.includes("Absolute / Shadow Black"));
  assert.ok(html.includes("Agate Black"));
  assert.match(html, /Pick catalogue colour/);
  client.clear();
});

test("empty identity copy explicitly declines guessing", () => {
  assert.match(EMPTY_IDENTITY_COPY, /We will not guess/);
  assert.match(EMPTY_IDENTITY_COPY, /Fix the Excel file and upload again/);
  assert.match(
    emptyIdentityCopy([{ ...held, column: "model", display_group: "empty_identity" }]),
    /no model/,
  );
});

test("panel alias payload requires plant and model and rejects extra fields", () => {
  const valid = {
    raw_value: "Front hood",
    zone_code: "Hood",
    plant_code: "AAT",
    model_code: "P703 DBL RANGER",
  };
  assert.equal(checkzoneAliasPayload.safeParse(valid).success, true);
  assert.equal(checkzoneAliasPayload.safeParse({ ...valid, model_code: undefined }).success, false);
  assert.equal(checkzoneAliasPayload.safeParse({ ...valid, invented_panel: "yes" }).success, false);
});

test("confirm table preserves file panel text, outcomes, and summary", () => {
  const html = renderWorksheet({ ...worksheet, extra_columns: [] });
  assert.match(html, /<table/);
  assert.match(html, /01HOOD/);
  assert.match(html, /Held out/);
  assert.match(html, /The other copy is added/);
  assert.match(html, /10 readings ready to add, 2 held out, 1 already in History/);
  assert.doesNotMatch(html, /RRHOOD|LOAD|DUPLICATE|QUARANTINE|REJECT/);
  assert.doesNotMatch(html, /<input/);
});

test("Viewer cannot approve or fetch the worksheet", () => {
  const client = new QueryClient();
  client.setQueryData(["identity"], {
    ...identity,
    principal: { ...identity.principal, roles: ["viewer"] },
  });
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ConfirmWorksheet code="AAT" hash={fileHash} workbook={workbookFixture} onLoaded={() => {}} />
    </QueryClientProvider>,
  );
  assert.doesNotMatch(html, /Approve|<table/);
  assert.equal(client.getQueryState(["worksheet", "AAT", fileHash])?.fetchStatus, "idle");
  client.clear();
});

test("confirm renders all rows in API order without a page limit", () => {
  const base = worksheet.sheets[0].rows[1];
  const rows = Array.from({ length: 1001 }, (_, index) => ({
    ...base,
    source_row: index + 2,
    panel_label: index === 1000 ? "LAST FILE PANEL" : `Panel ${index}`,
  }));
  const html = renderWorksheet({
    ...worksheet,
    extra_columns: [],
    sheets: [{ ...worksheet.sheets[0], rows, held: [] }],
  });
  assert.equal((html.match(/data-outcome="ready"/g) ?? []).length, 1001);
  assert.ok(html.indexOf("Panel 0") < html.indexOf("LAST FILE PANEL"));
});

test("T59 held rows are highlighted and colour select is in the matching table cell", () => {
  const html = renderWorksheet({ ...worksheet, extra_columns: [] });
  const row = html.match(/<tr[^>]*data-outcome="held_out"[^>]*>[\s\S]*?<\/tr>/)?.[0] ?? "";
  assert.match(row, /bg-\[var\(--primary-soft\)\]/);
  assert.match(row, /Choose colour/);
  assert.match(row, /<option value="Absolute \/ Shadow Black"/);
  assert.match(row, /<option value="Agate Black"/);
  assert.match(html, /All rows/);
  assert.match(html, /Need attention/);
  const ready = html.match(/<tr[^>]*data-outcome="ready"[^>]*>[\s\S]*?<\/tr>/)?.[0] ?? "";
  assert.doesNotMatch(ready, /primary-soft|<select/);
});

const modelHeld: components["schemas"]["HeldLabelGroup"] = {
  ...held,
  reason: "UNKNOWN_MODEL",
  column: "model",
  raw_value: "Ranjer",
  display_group: "model",
  teachable_kind: "ALIAS_MODEL",
  candidates: ["P703"],
  operator_message: "Pick the model.",
};
const panelHeld: components["schemas"]["HeldLabelGroup"] = {
  ...held,
  reason: "UNKNOWN_CHECKZONE",
  column: "checkzone",
  raw_value: "01HOOD",
  display_group: "zone",
  teachable_kind: "ALIAS_CHECKZONE",
  model_code: "P703",
  candidates: ["RRHOOD"],
  operator_message: "Pick the panel.",
};

function renderRows(
  groups: components["schemas"]["HeldLabelGroup"][],
  rows = worksheet.sheets[0].rows,
  role = "engineer",
) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], {
    ...identity,
    principal: { ...identity.principal, roles: [role] },
  });
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <WorksheetRows
        sheet={{ ...worksheet.sheets[0], held: groups, rows }}
        plant="AAT"
        fileHash={fileHash}
      />
    </QueryClientProvider>,
  );
  client.clear();
  return html;
}

test("T59 model and plant-scoped panel picks match only their held cell and model", () => {
  const html = renderRows(
    [modelHeld, panelHeld],
    [
      { ...worksheet.sheets[0].rows[0], source_row: 10, model_text: "Ranjer", model: null },
      { ...worksheet.sheets[0].rows[0], source_row: 11 },
      { ...worksheet.sheets[0].rows[0], source_row: 12, model: "U704" },
    ],
  );
  assert.equal((html.match(/<select/g) ?? []).length, 2);
  assert.match(html, /Choose model/);
  assert.match(html, /Choose panel/);
  const wrongModel = html.match(/<tr[^>]*>[\s\S]*?12<\/td>[\s\S]*?<\/tr>/)?.[0] ?? "";
  assert.doesNotMatch(wrongModel.slice(wrongModel.lastIndexOf("<tr")), /<select/);
});

test("T59 never offers picks for Film, missing values, or non-teachable model", () => {
  const groups = [
    "film_point",
    "film_model",
    "date",
    "measure",
    "empty_identity",
    "header",
    "plant",
  ] as const;
  const labels: components["schemas"]["HeldLabelGroup"][] = groups.map((display_group) => ({
    ...held,
    display_group,
    raw_value: "Black",
    teachable_kind: null,
  }));
  labels.push({ ...modelHeld, teachable_kind: null, reason: "MODEL_NOT_OFFERED" });
  const html = renderRows(labels, [
    { ...worksheet.sheets[0].rows[0], model_text: "Ranjer", date_text: null },
  ]);
  assert.doesNotMatch(html, /<select|<input/);
  assert.match(html, /held_out/);
  for (const label of labels) assert.equal(canTeach(label, true, "PENDING_REVIEW"), false);
});

test("T59 Viewer cannot pick even when the table has candidates", () => {
  assert.doesNotMatch(renderRows([held, panelHeld], undefined, "viewer"), /<select|<input/);
});

test("T59 shared proposal builder retains all existing alias bodies", () => {
  assert.deepEqual(
    heldAliasProposal(
      { item: held, name: "Absolute / Shadow Black" },
      "AAT",
      123,
      "PENDING_REVIEW",
    ),
    {
      kind: "ALIAS_COLOR",
      load_id: 123,
      payload: { raw_value: "Black", color_name: "Absolute / Shadow Black", plant_code: "AAT" },
    },
  );
  assert.deepEqual(
    heldAliasProposal({ item: modelHeld, name: "P703" }, "AAT", 123, "PENDING_REVIEW"),
    { kind: "ALIAS_MODEL", load_id: 123, payload: { raw_value: "Ranjer", model_code: "P703" } },
  );
  assert.deepEqual(
    heldAliasProposal({ item: panelHeld, name: "RRHOOD" }, "AAT", 123, "PENDING_REVIEW"),
    {
      kind: "ALIAS_CHECKZONE",
      load_id: 123,
      payload: { raw_value: "01HOOD", zone_code: "RRHOOD", plant_code: "AAT", model_code: "P703" },
    },
  );
  for (const item of [held, panelHeld])
    assert.equal(
      heldAliasProposal({ item, name: item.candidates![0] }, "AAT", 123, "COMMITTED").load_id,
      undefined,
    );
  assert.equal(canTeach(modelHeld, true, "COMMITTED"), false);
});

test("RO13 F12: Load remaining matched rows is disabled when no loaded tab has a ready row", () => {
  const loaded = { ...worksheet.sheets[0], status: "COMMITTED", state: "loaded" as const };
  const none = renderWorksheet({
    ...worksheet,
    extra_columns: [],
    ready_sheet_count: 0,
    sheets: [{ ...loaded, rows_ready: 0 }],
  });
  assert.match(none, /<button[^>]*disabled=""[^>]*>Load remaining matched rows<\/button>/);
  const some = renderWorksheet({ ...worksheet, extra_columns: [], sheets: [loaded] });
  assert.match(some, /<button(?![^>]*disabled="")[^>]*>Load remaining matched rows<\/button>/);
});

test("RO13 F14: the step-3 approve bar is sticky only from 768 px", () => {
  const html = renderWorksheet(worksheet);
  const bar = html.match(/<div class="([^"]*)"><p[^>]*>\d+\. Approve the ready readings/);
  assert.ok(bar);
  assert.match(bar[1], /(^| )md:sticky( |$)/);
  assert.doesNotMatch(bar[1], /(^| )sticky( |$)/);
});
