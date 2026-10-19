import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import type { components } from "../src/api/types";
import { PlantFiles } from "../src/features/measurements/PlantFiles";
import { WorksheetRows, ConfirmWorksheet } from "../src/features/measurements/ConfirmWorksheet";
import { PointCheck } from "../src/features/filmthickness/PointCheck";
import { WorkbookDetail } from "../src/features/measurements/WorkbookDetail";
import { identity } from "./fixtures";
import { workbookFixture, detailFixture, fileHash } from "./workbook-fixtures";

function render(node: ReactNode, seed?: (client: QueryClient) => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  client.setQueryData(["identity"], identity);
  seed?.(client);
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>{node}</QueryClientProvider>,
  );
  client.clear();
  return html;
}

const longSheet = "https://sharepoint.example/" + "a-long-sheet-name/".repeat(25);
const skipped = {
  source_sheet: longSheet,
  reason: "Outside the measurement sheets",
  legacy_load_id: null,
};
const allSkipped = {
  ...workbookFixture,
  operational_summary: "SKIPPED",
  sheets: [],
  sheet_count: 0,
  skipped_sheet_count: 1,
  skipped_sheets: [skipped],
} as components["schemas"]["WorkbookOut"];

test("a workbook groups skipped sheet evidence and contains long sheet chips", () => {
  const workbook = {
    ...workbookFixture,
    skipped_sheet_count: 1,
    skipped_sheets: [skipped],
    sheets: workbookFixture.sheets.map((s) => ({
      ...s,
      batch: { ...s.batch, source_sheet: longSheet },
    })),
  };
  const html = render(
    <PlantFiles
      code="AAT"
      inactive={false}
      domain="both"
      onDomainChange={() => {}}
      onOpen={() => {}}
    />,
    (client) =>
      client.setQueryData(["workbooks", "AAT", "all", undefined], {
        plant_code: "AAT",
        plant_is_active: true,
        items: [workbook],
        page: { total: 1, limit: 200, offset: 0 },
      }),
  );
  assert.match(html, /Skipped sheets of review\.xlsx/);
  assert.match(html, /Outside the measurement sheets/);
  assert.match(html, /data-sheet-chip="true"[^>]*max-w-full[^>]*break-all/);
});

test("all-skipped workbook review is evidence only and exposes no worksheet actions", () => {
  const html = render(
    <ConfirmWorksheet code="AAT" hash={fileHash} workbook={allSkipped} onLoaded={() => {}} />,
  );
  assert.match(html, /No measurement sheets to review/);
  assert.match(html, /Outside the measurement sheets/);
  assert.doesNotMatch(html, /Loading worksheet table|Load ready|Load remaining|Confirm all/);
  const detail = render(<WorkbookDetail code="AAT" hash={fileHash} onBack={() => {}} />, (client) =>
    client.setQueryData(["workbook", "AAT", fileHash], { ...detailFixture, workbook: allSkipped }),
  );
  assert.match(detail, /Skipped sheets of review\.xlsx/);
  assert.doesNotMatch(detail, /Commit all eligible|Commit sheet/);
});

test("worksheet row reasons carry their own mobile label and stay in the stacked row", () => {
  const sheet = {
    load_id: 19,
    sheet: "Quick Summary",
    status: "PENDING_REVIEW",
    state: "needs_answer",
    rows: [
      {
        source_sheet: "Quick Summary",
        source_row: 4,
        panel_label: "061TGATE",
        outcome: "held_out",
        operator_message: "Name this point before loading",
        model: "J73 DBL",
        color: "Arctic White",
        counted: null,
      },
    ],
    rows_ready: 0,
    rows_loaded: 0,
    rows_held: 1,
    rows_already_in_history: 0,
    rows_need_confirmation: 0,
    extra_columns: [],
    held: [],
    plant_texts: [],
    panel_rename: [],
    rough_panels: [],
    hole_rows: [],
    short_vehicles: [],
    commit_blockers: [],
    missing_optional: [],
    vehicle_count: 1,
    operator_message: "Check this tab",
  } as unknown as components["schemas"]["WorksheetSheetOut"];
  const html = render(<WorksheetRows sheet={sheet} plant="SAP" fileHash={fileHash} />);
  assert.match(html, /data-label="Reason"/);
  assert.match(html, /Name this point before loading/);
  assert.match(html, /@media\s*\(max-width:\s*639px\)/);
  assert.match(html, /\.ro19-worksheet tbody tr\s*\{[^}]*display:\s*grid/);
});

test("Viewer Point Check explains Point Check access", async () => {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => <PointCheck code="SAP" /> }),
    history: createMemoryHistory(),
  });
  await router.load();
  const html = render(<RouterProvider router={router} />, (client) =>
    client.setQueryData(["identity"], {
      ...identity,
      principal: { ...identity.principal, roles: ["viewer"] },
    }),
  );
  assert.match(html, /Point Check needs Engineer or Admin access\./);
  assert.doesNotMatch(html, /Upload, commit and mapping require/);
});
