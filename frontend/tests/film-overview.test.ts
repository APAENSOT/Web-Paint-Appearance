import assert from "node:assert/strict";
import test from "node:test";
import { QueryClient } from "@tanstack/react-query";
import { filmOverviewOptions } from "../src/api/queries.ts";
import { createApiClient, ApiError } from "../src/api/client.ts";
import { filmBox, filmOverviewFixture } from "./film-overview-fixtures.ts";
import {
  boxKey,
  groupFilmBoxes,
  filmDomain,
  specSegments,
  colourPairWidth,
} from "../src/features/filmthickness/film-overview-display.ts";

test("T66 transport repeats plural arrays, omits empty filters, retains decimals and signal", async () => {
  const controller = new AbortController();
  const seen: URL[] = [];
  const client = createApiClient("http://localhost:8012", async (input, init) => {
    seen.push(new URL(String(input)));
    assert.equal(init?.signal, controller.signal);
    assert.equal(init?.method, "GET");
    assert.equal(init?.credentials, "omit");
    return Response.json(filmOverviewFixture);
  });
  const data = await client.filmOverview(
    "FTM",
    { month: "2026-08", models: ["Ranger", "Raptor"], colors: ["Absolute / Shadow Black", "Blue"] },
    controller.signal,
  );
  await client.filmOverview("FTM", { models: [], colors: [] }, controller.signal);
  assert.deepEqual(seen[0].searchParams.getAll("models"), ["Ranger", "Raptor"]);
  assert.deepEqual(seen[0].searchParams.getAll("colors"), ["Absolute / Shadow Black", "Blue"]);
  assert.equal(seen[0].searchParams.has("model"), false);
  assert.equal(seen[0].searchParams.has("color"), false);
  assert.equal(seen[1].search, "");
  assert.equal(
    data.boxes.find(
      (box) =>
        box.color_name === "Absolute / Shadow Black" &&
        box.layer_code === "ECOAT" &&
        box.orient === "H",
    )!.box_min,
    "10.00000000000000001",
  );
});

test("T66 cancellation and actual error envelope propagate", async () => {
  const controller = new AbortController();
  controller.abort();
  const aborted = createApiClient("http://localhost:8012", async (_, init) => {
    init?.signal?.throwIfAborted();
    return Response.json({});
  });
  await assert.rejects(aborted.filmOverview("FTM", {}, controller.signal), { name: "AbortError" });
  for (const status of [401, 403, 404, 422, 503]) {
    const client = createApiClient("http://localhost:8012", async () =>
      Response.json(
        {
          statusCode: status,
          error: "Read refused",
          message: `Actual ${status}`,
          correlationId: `film-${status}`,
        },
        { status },
      ),
    );
    await assert.rejects(
      client.filmOverview("FTM"),
      (error: unknown) =>
        error instanceof ApiError &&
        error.body?.message === `Actual ${status}` &&
        error.body.correlationId === `film-${status}`,
    );
  }
});

test("T66 query caches separate exact plant/month/model/colour scopes without a layer key", () => {
  const client = new QueryClient();
  const scopes = [
    filmOverviewOptions("FTM", { month: "2026-08" }),
    filmOverviewOptions("SAP", { month: "2026-08" }),
    filmOverviewOptions("FTM", { month: "2026-07" }),
    filmOverviewOptions("FTM", { month: "2026-08", models: ["Ranger"] }),
    filmOverviewOptions("FTM", { month: "2026-08", colors: ["Absolute / Shadow Black"] }),
  ];
  scopes.forEach((options, index) =>
    client.setQueryData(options.queryKey, {
      ...filmOverviewFixture,
      standards_note: `Scope ${index}`,
    }),
  );
  scopes.forEach((options, index) => {
    assert.equal(client.getQueryData(options.queryKey)?.standards_note, `Scope ${index}`);
    assert.equal(options.retry, false);
    assert.equal(options.queryKey.includes("CLEAR"), false);
  });
  assert.equal(client.getQueryCache().getAll().length, 5);
  client.clear();
});

test("grouping preserves response model order, canonical colours and H/V grains without partners", () => {
  const original = JSON.stringify(filmOverviewFixture);
  const groups = groupFilmBoxes(filmOverviewFixture, "ECOAT");
  assert.deepEqual(
    groups.map((g) => g.model),
    filmOverviewFixture.model_options,
  );
  assert.deepEqual(
    groups[1].colours.map((c) => c.name),
    ["Absolute / Shadow Black", "Blue", "Seismic Tan"],
  );
  assert.deepEqual(
    groups[1].colours[0].boxes.map((b) => b.orient),
    ["H", "V"],
  );
  assert.equal(groups[1].colours[1].boxes.length, 1);
  assert.equal(
    new Set(filmOverviewFixture.boxes.map(boxKey)).size,
    filmOverviewFixture.boxes.length,
  );
  assert.equal(JSON.stringify(filmOverviewFixture), original);
  assert.deepEqual(groupFilmBoxes(filmOverviewFixture, "PRIMER"), []);
});

test("spec geometry is per slot, zero differs from null, NONE keeps statistics without lines", () => {
  assert.deepEqual(specSegments(filmBox(), 100, 60), [
    { field: "lo", label: "Minimum", value: 0, raw: "0", x1: 80, x2: 120, dash: "6 4" },
  ]);
  const h = specSegments(filmBox({ lo: "36", target: "46" }), 100, 60);
  const v = specSegments(filmBox({ orient: "V", lo: "30", target: "46" }), 160, 60);
  assert.equal(h[0].value, 36);
  assert.equal(v[0].value, 30);
  assert.ok(h.every((s) => s.x2 < v[0].x1));
  assert.deepEqual(specSegments(filmBox({ standard_scope: "NONE", lo: null }), 100, 60), []);
  assert.equal(specSegments(filmBox({ lo: "20", hi: "20", target: "20" }), 100, 60).length, 3);
});

test("domain includes all specs/returned points and padding for single values, pair width keeps full identity", () => {
  const [lo, hi] = filmDomain([
    filmBox({
      target: "46",
      out_of_spec: [
        { value: "-7", side: "LOW", point_code: "A", measured_date: null, logical_vehicle_id: "a" },
        {
          value: "80",
          side: "HIGH",
          point_code: "B",
          measured_date: null,
          logical_vehicle_id: "b",
        },
      ],
    }),
  ]);
  assert.ok(lo < 0 && hi > 40);
  assert.ok(filmDomain([filmBox({ target: "1000" })])[1] > 1000);
  const singleton = filmBox({
    q1: "1",
    median: "1",
    q3: "1",
    whisker_lo: "1",
    whisker_hi: "1",
    outliers: [],
    lo: null,
  });
  assert.ok(filmDomain([singleton])[0] < 1 && filmDomain([singleton])[1] > 1);
  assert.ok(colourPairWidth("Blue") >= 144);
  assert.ok(colourPairWidth("A very long canonical colour name with complete identity") > 144);
});
