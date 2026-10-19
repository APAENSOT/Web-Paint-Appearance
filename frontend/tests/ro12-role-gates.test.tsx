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
import { mayIngest } from "../src/api/roles";
import type { components } from "../src/api/types";
import { PointCheck } from "../src/features/filmthickness/PointCheck";
import { PlantStandard, type StandardView } from "../src/features/measurements/PlantStandard";
import { RemoveWorkbook } from "../src/features/measurements/RemoveWorkbook";
import { VehiclePoints } from "../src/features/measurements/VehicleReviewDialog";
import { Acknowledge } from "../src/features/measurements/WorkbookSections";
import { catalogueFixture, cleanReview, identity } from "./fixtures";
import { workbookFixture } from "./workbook-fixtures";

// RO12 (D-RO12-4): each role is offered only the controls its server routes allow.
const ROLES = ["viewer", "engineer", "admin"] as const;
type Role = (typeof ROLES)[number];

function render(role: Role, node: ReactNode, seed?: (client: QueryClient) => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  client.setQueryData(["identity"], {
    ...identity,
    principal: { ...identity.principal, roles: [role] },
  });
  seed?.(client);
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>{node}</QueryClientProvider>,
  );
  client.clear();
  return html;
}

const standard = (role: Role, view: StandardView) =>
  render(role, <PlantStandard code="FTM" view={view} />, (client) => {
    client.setQueryData(["standards", "catalogue"], catalogueFixture);
    client.setQueryData(["standards", "model-points", "FTM"], {
      plant_code: "FTM",
      models: [
        {
          model_code: "P703 DBL RANGER",
          display_name: null,
          series_code: "P703",
          body_style: "Pickup",
          wavescan_ok: true,
          wavescan_offered: true,
          wavescan_points: 32,
          film_points: 98,
        },
      ],
      attachable_models: ["P703 SGL"],
    });
  });

for (const role of ROLES) {
  const admin = role === "admin";

  test(`RO12 ${role}: Upload Data entry follows the upload route (Engineer or Admin)`, () => {
    assert.equal(mayIngest({ ...identity.principal, roles: [role] }), role !== "viewer");
  });

  test(`RO12 ${role}: Delete (purge) is offered to Admin only`, () => {
    const html = render(role, <RemoveWorkbook code="AAT" workbook={workbookFixture} />);
    assert.equal(html.includes('aria-label="Delete review.xlsx"'), admin);
  });

  test(`RO12 ${role}: Acknowledge is offered to Admin only`, () => {
    const sheet = {
      ...workbookFixture.sheets[0],
      required_acknowledgements: ["DUPLICATE_ROWS"],
    } as components["schemas"]["WorkbookSheetOut"];
    const html = render(
      role,
      <Acknowledge
        code="AAT"
        hash={workbookFixture.file_hash}
        sheet={sheet}
        category="DUPLICATE_ROWS"
      />,
    );
    assert.equal(html.includes("<form"), admin);
  });

  test(`RO12 ${role}: a Wave Scan point's override Edit is offered to Admin only`, () => {
    const point = {
      load_id: 123,
      source_sheet: "PasteData",
      source_row: 2,
      checkzone: "001HOOD",
      disposition: "LOAD",
      reason: null,
      detail: null,
      raw: { values: { cf: "60" } },
      proposed: { measures: { cf: "60" } },
      current_overrides: [],
      measurement_id: null,
      projection_missing: false,
    };
    const page = {
      items: [point],
      page: { limit: 200, offset: 0, total: 1, returned: 1 },
      file_hash: "0".repeat(64),
      plant_code: "AAT",
    };
    const html = render(
      role,
      <VehiclePoints
        code="AAT"
        hash={"0".repeat(64)}
        vehicleId={"a".repeat(64)}
        points={{ isPending: false, isError: false, isFetching: false, data: page } as never}
        sheet={
          {
            batch: { ...cleanReview.batch, sheet_class: "WAVESCAN", status: "PENDING_REVIEW" },
          } as components["schemas"]["WorkbookSheetOut"]
        }
        refreshing={false}
        onDrafts={() => {}}
        onSaved={() => {}}
      />,
    );
    assert.equal(html.includes(">Edit<"), admin);
  });

  test(`RO12 ${role}: Color Family is read-only except for Admin`, () => {
    const html = standard(role, "family");
    assert.match(html, /Standard Horizontal/);
    assert.match(html, /Ignite Orange/);
    for (const control of [
      "Adjust standards",
      "Remove from FTM",
      "Add colour",
      "Select a historical colour",
    ])
      assert.equal(html.includes(control), admin, control);
  });

  test(`RO12 ${role}: Model is read-only except for Admin`, () => {
    const html = standard(role, "model");
    assert.match(html, /P703 DBL RANGER/);
    for (const control of ["Remove from FTM", "Attach model", "Attach existing model"])
      assert.equal(html.includes(control), admin, control);
  });

  test(`RO12 ${role}: Point Check is Engineer or Admin; a Viewer is denied`, async () => {
    // AccessDenied links home, so this one renders inside a router.
    const router = createRouter({
      routeTree: createRootRoute({ component: () => <PointCheck code="FTM" /> }),
      history: createMemoryHistory(),
    });
    await router.load();
    const html = render(role, <RouterProvider router={router} />);
    assert.equal(html.includes('data-testid="point-check"'), role !== "viewer");
    assert.equal(html.includes("Engineer access required"), role === "viewer");
  });
}
