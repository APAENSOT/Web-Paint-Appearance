import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryClient } from "@tanstack/react-query";
import { buildMeasurementQuery } from "../src/api/measurement-query";
import {
  historyFacetsOptions,
  historySummariesOptions,
  historyVehiclePointsOptions,
  historyVehiclesOptions,
  measurementsOptions,
  refreshActiveMeasurements,
  workbookHistoryOptions,
  workbookIssuesOptions,
  workbookOptions,
  workbookRowsOptions,
  workbooksOptions,
  refreshSettledReplayProposals,
} from "../src/api/queries";

test("History query options keep plant, filters, paging and drill-down identity in cache keys", () => {
  assert.deepEqual(historyFacetsOptions("FTM").queryKey, ["history", "FTM", "facets", {}]);
  assert.deepEqual(historySummariesOptions("FTM", { month: "2026-09", color: "Blue" }).queryKey, [
    "history",
    "FTM",
    "summaries",
    { month: "2026-09", color: "Blue" },
  ]);
  assert.deepEqual(
    historyVehiclesOptions("FTM", {
      month: "2026-09",
      week: 4,
      model: "P703",
      color: "Blue",
      offset: 20,
      limit: 20,
    }).queryKey,
    [
      "history",
      "FTM",
      "vehicles",
      {
        month: "2026-09",
        week: 4,
        model: "P703",
        color: "Blue",
        offset: 20,
        limit: 20,
      },
    ],
  );
  assert.deepEqual(historyVehiclePointsOptions("FTM", "vehicle", {}).queryKey, [
    "history",
    "FTM",
    "vehicles",
    "vehicle",
    "points",
    {},
  ]);
  assert.equal(historyFacetsOptions("FTM").retry, false);
  assert.equal(historySummariesOptions("FTM", { month: "2026-09" }).retry, false);
  assert.equal(
    historyVehiclesOptions("FTM", {
      month: "2026-09",
      week: 1,
      model: "P703",
      color: "Blue",
    }).retry,
    false,
  );
  assert.equal(historyVehiclePointsOptions("FTM", "vehicle").retry, false);
});

test("list query omits empty and unsupported fields; route and pagination cannot be overridden", () => {
  const input = {
    model: "P703",
    color: "",
    checkzone: null,
    date_from: "",
    ...{
      plant: "FVL",
      limit: 20000,
      offset: 999,
      color_group: "WHITE",
      grading_family: "solid",
      serial_no: "serial",
      dimension: "color",
    },
  };
  assert.deepEqual(buildMeasurementQuery("AAT", 50, input), {
    plant: "AAT",
    offset: 50,
    limit: 50,
    model: "P703",
  });
  assert.deepEqual(buildMeasurementQuery("AAT", 0, {}), { plant: "AAT", offset: 0, limit: 50 });
  assert.throws(() => buildMeasurementQuery("", 0, {}), /plant/i);
});

test("list query includes load_id only when explicitly requested", () => {
  assert.deepEqual(buildMeasurementQuery("FTM", 0, { load_id: 42 }), {
    plant: "FTM",
    offset: 0,
    limit: 50,
    load_id: 42,
  });
  assert.equal("load_id" in buildMeasurementQuery("FTM", 0), false);
});

test("workbook query options keep plant, hash, paging and row filters in cache keys", () => {
  assert.deepEqual(workbooksOptions("FTM", 200).queryKey, ["workbooks", "FTM", 200]);
  assert.deepEqual(workbookOptions("FTM", "abc").queryKey, ["workbook", "FTM", "abc"]);
  assert.deepEqual(
    workbookRowsOptions("FTM", "abc", { disposition: "REJECT", offset: 50, limit: 50 }).queryKey,
    ["workbook", "FTM", "abc", "rows", { disposition: "REJECT", offset: 50, limit: 50 }],
  );
  assert.deepEqual(workbookIssuesOptions("FTM", "abc").queryKey, [
    "workbook",
    "FTM",
    "abc",
    "issues",
  ]);
  assert.deepEqual(workbookHistoryOptions("FTM", "abc").queryKey, [
    "workbook",
    "FTM",
    "abc",
    "history",
  ]);
});

test("workbook list and detail poll RUNNING sheets with bounded backoff and stop otherwise", () => {
  const runningBatch = {
    status: "RUNNING",
    job: { status: "RUNNING" },
  };
  const terminalBatch = {
    status: "PENDING_REVIEW",
    job: { status: "DONE" },
  };
  const listInterval = workbooksOptions("FTM", 0).refetchInterval;
  const detailInterval = workbookOptions("FTM", "abc").refetchInterval;
  assert.equal(typeof listInterval, "function");
  assert.equal(typeof detailInterval, "function");
  if (typeof listInterval !== "function" || typeof detailInterval !== "function") return;

  const query = (data: unknown, updates = 1, status: "success" | "error" = "success") =>
    ({ state: { data, dataUpdateCount: updates, status } }) as never;
  const list = (batch: typeof runningBatch) => ({
    items: [{ sheets: [{ batch }] }],
  });
  const detail = (batch: typeof runningBatch) => ({
    workbook: { sheets: [{ batch }] },
  });

  assert.equal(listInterval(query(list(runningBatch), 1)), 1000);
  assert.equal(listInterval(query(list(runningBatch), 6)), 10000);
  assert.equal(detailInterval(query(detail(runningBatch), 2)), 2000);
  assert.equal(listInterval(query(list(terminalBatch as typeof runningBatch))), false);
  assert.equal(detailInterval(query(detail(terminalBatch as typeof runningBatch))), false);
  assert.equal(listInterval(query(list(runningBatch), 1, "error")), false);
  assert.equal(detailInterval(query(undefined)), false);
});

test("a replay reaching terminal state invalidates that sheet's proposals", async () => {
  const client = new QueryClient();
  client.setQueryData(["proposals", 42, 0], { items: [] });
  client.setQueryData(["proposals", 43, 0], { items: [] });
  const sheet = (load_id: number, status: "RUNNING" | "PENDING_REVIEW") =>
    ({ batch: { load_id, status } }) as never;

  await refreshSettledReplayProposals(
    client,
    [sheet(42, "RUNNING"), sheet(43, "PENDING_REVIEW")],
    [sheet(42, "PENDING_REVIEW"), sheet(43, "PENDING_REVIEW")],
  );

  assert.equal(client.getQueryState(["proposals", 42, 0])?.isInvalidated, true);
  assert.equal(client.getQueryState(["proposals", 43, 0])?.isInvalidated, false);
  client.clear();
});

test("list query accepts inclusive date boundaries and refuses impossible or reversed dates", () => {
  for (const input of [
    { date_from: "2026-09-14", date_to: "2026-09-13" },
    { date_from: "1999-12-31" },
    { date_to: "2101-01-01" },
    { date_from: "2026-02-30" },
  ])
    assert.throws(() => buildMeasurementQuery("AAT", 0, input), /date/i);
  assert.deepEqual(
    buildMeasurementQuery("AAT", 0, { date_from: "2000-01-01", date_to: "2100-12-31" }),
    { plant: "AAT", offset: 0, limit: 50, date_from: "2000-01-01", date_to: "2100-12-31" },
  );
});

test("applied filters separate cache pages; retirement clears filtered and unfiltered pages", async () => {
  const client = new QueryClient();
  const all = measurementsOptions("AAT", 0);
  const white = measurementsOptions("AAT", 0, { color: "White" });
  assert.notDeepEqual(all.queryKey, white.queryKey);
  assert.deepEqual(all.queryKey, measurementsOptions("AAT", 0, { color: "" }).queryKey);
  const page = {
    items: [],
    page: { total: 0, returned: 0, limit: 50, offset: 0 },
    filters: {
      plant: "AAT",
      model: null,
      color: null,
      checkzone: null,
      date_from: null,
      date_to: null,
    },
    active_data_source: "v_wavescan_active",
  };
  client.setQueryData(all.queryKey, page);
  client.setQueryData(white.queryKey, { ...page, filters: { ...page.filters, color: "White" } });
  client.setQueryData(["history", "AAT", "vehicles", "vehicle", "points", {}], {
    items: [{ measurement_id: 41 }],
  });
  await refreshActiveMeasurements(client);
  assert.equal(client.getQueryData(all.queryKey), undefined);
  assert.equal(client.getQueryData(white.queryKey), undefined);
  assert.equal(
    client.getQueryData(["history", "AAT", "vehicles", "vehicle", "points", {}]),
    undefined,
  );
  client.clear();
});

test("Overview query sends only plant, limit and offset after a filtered list request", async () => {
  const { createServer } = await import("vite");
  const server = await createServer({
    configFile: false,
    envDir: false,
    cacheDir: "test-results/t12-vite-cache",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true },
    appType: "custom",
    define: { "import.meta.env.VITE_API_BASE_URL": JSON.stringify("http://localhost:8000") },
  });
  const requests: URL[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    requests.push(new URL(String(input)));
    return Response.json({ items: [] });
  };
  try {
    const options = await server.ssrLoadModule("/src/api/queries.ts");
    await options
      .measurementsOptions("AAT", 50, {
        model: "P703",
        color: "White",
        checkzone: "RRHOOD",
        date_from: "2026-09-01",
      })
      .queryFn({ signal: new AbortController().signal });
    await options.plantCountOptions("AAT").queryFn({ signal: new AbortController().signal });
    assert.deepEqual(Object.fromEntries(requests[0].searchParams), {
      plant: "AAT",
      offset: "50",
      limit: "50",
      model: "P703",
      color: "White",
      checkzone: "RRHOOD",
      date_from: "2026-09-01",
    });
    assert.deepEqual(Object.fromEntries(requests[1].searchParams), {
      plant: "AAT",
      limit: "1",
      offset: "0",
    });
  } finally {
    globalThis.fetch = originalFetch;
    await server.close();
  }
});

test("plant lenses and unavailable bays carry no grade figures", async () => {
  const { LENS_PLACEHOLDER, UNAVAILABLE_BAY_REASON } =
    await import("../src/features/measurements/plant-lens.ts");
  const copy = [
    UNAVAILABLE_BAY_REASON,
    ...Object.values(LENS_PLACEHOLDER).flatMap((item) => [item.title, item.reason]),
  ].join("\n");
  assert.doesNotMatch(copy, /%/);
  assert.doesNotMatch(copy, /NOMINAL/i);
  assert.doesNotMatch(copy, /96\.4/);
  assert.doesNotMatch(copy, /98\.2/);
});

test("T97: a sheet leaving RUNNING refetches the worksheet review read", async () => {
  // D-97-5. The review screen read the worksheet once while the batch was
  // still parsing and never again until the component remounted, which is
  // what leaving the page and coming back did. The workbook poll already
  // knows when parsing ended, so the refresh belongs on its invalidation
  // list -- no second polling loop.
  const { createServer } = await import("vite");
  const server = await createServer({
    configFile: false,
    envDir: false,
    cacheDir: "test-results/t97-vite-cache",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true },
    appType: "custom",
    define: { "import.meta.env.VITE_API_BASE_URL": JSON.stringify("http://localhost:8000") },
  });
  const originalFetch = globalThis.fetch;
  const sheet = (status: string) => ({ batch: { load_id: 7, file_hash: "abc", status } });
  globalThis.fetch = async () => Response.json({ workbook: { sheets: [sheet("PENDING_REVIEW")] } });
  try {
    const options = await server.ssrLoadModule("/src/api/queries.ts");
    const read = (previous: string) => {
      const client = new QueryClient();
      client.setQueryData(["workbook", "FTM", "abc"], { workbook: { sheets: [sheet(previous)] } });
      client.setQueryData(["worksheet", "FTM", "abc"], { sheets: [] });
      client.setQueryData(["workbook", "FTM", "abc", "rows", { offset: 0, limit: 50 }], {});
      return client;
    };
    const settled = read("RUNNING");
    await options.workbookOptions("FTM", "abc").queryFn({
      signal: new AbortController().signal,
      client: settled,
    });
    assert.equal(settled.getQueryState(["worksheet", "FTM", "abc"])?.isInvalidated, true);
    assert.equal(
      settled.getQueryState(["workbook", "FTM", "abc", "rows", { offset: 0, limit: 50 }])
        ?.isInvalidated,
      true,
    );

    // A poll that saw no sheet finish invalidates nothing: the worksheet key
    // joins the existing list and does not widen when it fires.
    const quiet = read("PENDING_REVIEW");
    await options.workbookOptions("FTM", "abc").queryFn({
      signal: new AbortController().signal,
      client: quiet,
    });
    assert.equal(quiet.getQueryState(["worksheet", "FTM", "abc"])?.isInvalidated, false);
    settled.clear();
    quiet.clear();
  } finally {
    globalThis.fetch = originalFetch;
    await server.close();
  }
});
