import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReviewQueue } from "../src/features/intake/ReviewQueue";
import { batchPollInterval } from "../src/api/batch-state";
import type { components } from "../src/api/types";
import { cleanReview, identity } from "./fixtures";
import { BatchReviewCard } from "../src/features/intake/BatchReviewCard";
import { VehiclePoints } from "../src/features/measurements/VehicleReviewDialog";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";

for (const roles of [["viewer"], ["engineer"], ["admin"]] as const) {
  test(`${roles[0]} chrome uses API identity for the file picker`, async () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
    client.setQueryData(["identity"], {
      ...identity,
      principal: { ...identity.principal, roles: [...roles] },
    });
    client.setQueryData(["batches", 0], {
      items: [],
      page: { offset: 0, limit: 10, returned: 0, total: 0 },
    });
    const root = createRootRoute({
      component: () => (
        <QueryClientProvider client={client}>
          <ReviewQueue />
        </QueryClientProvider>
      ),
    });
    const router = createRouter({ routeTree: root, history: createMemoryHistory() });
    await router.load();
    const html = renderToStaticMarkup(<RouterProvider router={router} />);
    // RO12 CHANGE (D-RO12-4): upload is Engineer or Admin; a Viewer is denied.
    assert.equal(html.includes('type="file"'), roles[0] !== "viewer");
    assert.equal(html.includes("Upload workbooks</button>"), roles[0] !== "viewer");
    assert.equal(html.includes("Commit sheet</button>"), false);
    client.clear();
  });
}

test("polling backs off, stops on all terminal signals, and stops on request error", () => {
  const running = {
    ...cleanReview.batch,
    status: "RUNNING",
    job: { ...cleanReview.batch.job!, status: "QUEUED" },
  } as components["schemas"]["BatchOut"];
  assert.equal(batchPollInterval(running, 1, false), 1000);
  assert.equal(batchPollInterval(running, 2, false), 2000);
  assert.equal(batchPollInterval(running, 20, false), 10000);
  for (const status of ["DONE", "FAILED"] as const) {
    assert.equal(
      batchPollInterval({ ...running, job: { ...running.job!, status } }, 1, false),
      false,
    );
  }
  assert.equal(batchPollInterval({ ...running, status: "PENDING_REVIEW" }, 1, false), false);
  assert.equal(batchPollInterval(running, 1, true), false);
});

test("commit is absent for Viewer even with a clean review; unbalanced and noncommittable reviews stay disabled", () => {
  for (const [canMutate, committable, balanced, enabled] of [
    [false, true, true, false],
    [true, false, true, false],
    [true, true, false, false],
    [true, true, true, true],
  ]) {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
    client.setQueryData(["batch", 123], {
      ...cleanReview,
      committable,
      batch: { ...cleanReview.batch, counts: { ...cleanReview.batch.counts, balanced } },
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <BatchReviewCard id={123} canMutate={canMutate} />
      </QueryClientProvider>,
    );
    const button = html.match(/<button[^>]*>Commit sheet<\/button>/)?.[0];
    assert.equal(Boolean(button), canMutate);
    if (button) assert.equal(!button.includes('disabled=""'), enabled);
    client.clear();
  }
});

test("RO11: a Film set's points show Film layers, never Wave Scan measures", () => {
  const vehicle: components["schemas"]["VehicleSetOut"] = {
    vehicle_id: "a".repeat(64),
    load_id: 123,
    plant_code: "AAT",
    measured_date: "2026-08-20",
    date_is_month_only: false,
    model: "P703 DBL RANGER",
    color: "Command Grey",
    serial_no: null,
    identity_complete: true,
    point_count: 94,
    expected_point_count: 94,
    incomplete_set: false,
    dispositions: { load: 94, duplicate: 0, reject: 0, quarantine: 0 },
  };
  const point: components["schemas"]["VehiclePointOut"] = {
    load_id: 123,
    source_sheet: "P703 Ranger",
    source_row: 16,
    checkzone: "001HOOD",
    disposition: "LOAD",
    reason: null,
    detail: null,
    raw: {
      values: { ecoat: 20.1877460479736, primer: 10.0000886917114, base: 15.06, clear: 38.8 },
    },
    proposed: {
      point_code: "001HOOD",
      orientation: "H",
      layers: { ECOAT: "20.1877460479736", PRIMER: "10.0000886917114", BASE: "15.0654592514038" },
    },
    current_overrides: [],
    measurement_id: null,
    projection_missing: false,
  };
  const page = {
    items: [point],
    page: { limit: 200, offset: 0, total: 1, returned: 1 },
    vehicle,
    file_hash: "0".repeat(64),
    plant_code: "AAT",
  };
  const render = (sheetClass: string) => {
    const client = new QueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <VehiclePoints
          code="AAT"
          hash={"0".repeat(64)}
          vehicleId={vehicle.vehicle_id}
          points={{ isPending: false, isError: false, isFetching: false, data: page } as never}
          sheet={
            {
              batch: { ...cleanReview.batch, sheet_class: sheetClass },
            } as components["schemas"]["WorkbookSheetOut"]
          }
          refreshing={false}
          onDrafts={() => {}}
          onSaved={() => {}}
        />
      </QueryClientProvider>,
    );
    client.clear();
    return html;
  };
  const film = render("FILMTHICKNESS");
  assert.match(film, /94 of 94 points/);
  assert.match(film, /001HOOD \/ Horizontal \/ LOAD/);
  for (const label of ["E-coat", "Primer", "Base", "Clear"]) assert.match(film, new RegExp(label));
  assert.match(film, /20\.1877460479736/, "the stored value, at the file's precision");
  assert.match(film, /File: 15\.06/, "the file's value where it differs");
  assert.match(film, /Not measured/, "a missing layer");
  for (const measure of [">LW<", ">SW<", ">CF<", ">DOI<", "Checkzone unavailable", ">Edit<"])
    assert.equal(film.includes(measure), false, measure);
  const wave = render("WAVESCAN");
  assert.match(wave, />CF</, "a Wave Scan sheet keeps its measures");
  assert.equal(wave.includes("E-coat"), false);
});
