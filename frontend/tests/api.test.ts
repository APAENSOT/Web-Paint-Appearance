import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, createApiClient } from "../src/api/client.ts";

test("film reads use only T48 paths, omit credentials, and preserve error detail", async () => {
  const calls: URL[] = [];
  const api = createApiClient("http://localhost:8012", async (input, init) => {
    const url = new URL(String(input));
    calls.push(url);
    assert.equal(init?.credentials, "omit");
    assert.equal(init?.method, "GET");
    if (url.pathname.endsWith("points"))
      return Response.json(
        {
          statusCode: 404,
          error: "Not Found",
          message: "Film vehicle absent",
          correlationId: "film-404",
        },
        { status: 404 },
      );
    return Response.json({});
  });
  await api.filmFacets("FTM", { month: "2026-08", model: "P703 DBL RANGER" });
  await api.filmVehicles("FTM", { month: "2026-08", color: "Blue", limit: 200, offset: 0 });
  await assert.rejects(
    api.filmVehiclePoints("FTM", "a".repeat(64)),
    (error: unknown) =>
      error instanceof ApiError &&
      error.body?.message === "Film vehicle absent" &&
      error.body.correlationId === "film-404",
  );
  assert.equal(calls.length, 3);
  assert.equal(calls[0].searchParams.get("month"), "2026-08");
  assert.equal(calls[1].searchParams.get("color"), "Blue");
  assert.ok(calls.every((url) => url.pathname.includes("/filmthickness/")));
});

test("worksheet helpers use the six generated paths and exact JSON bodies", async () => {
  const seen: { path: string; method: string; body: unknown }[] = [];
  const api = createApiClient("http://localhost:8016", async (input, init) => {
    seen.push({
      path: new URL(String(input)).pathname,
      method: init?.method ?? "",
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    return Response.json({});
  });
  const hash = "a".repeat(64);
  await api.worksheet("FTM", hash);
  await api.ignoreColumns("FTM", hash, { headers: ["Panel2"] });
  await api.answerPlant("FTM", hash, { plant_code: "AAT" });
  await api.approveHoles("FTM", hash, { load_id: 123, source_rows: [7] });
  await api.loadReady("FTM", hash);
  await api.loadRemaining("FTM", hash);
  assert.deepEqual(
    seen.map((item) => [item.path.split("/").at(-1), item.method]),
    [
      ["worksheet", "GET"],
      ["ignore-columns", "POST"],
      ["plant-answer", "POST"],
      ["hole-approval", "POST"],
      ["load-ready", "POST"],
      ["load-remaining", "POST"],
    ],
  );
  assert.deepEqual(
    seen.slice(1).map((item) => item.body),
    [
      { headers: ["Panel2"] },
      { plant_code: "AAT" },
      { load_id: 123, source_rows: [7] },
      null,
      null,
    ],
  );
});

test("workbook X posts purge reason and preserves dependency 409 detail", async () => {
  const hash = "a".repeat(64);
  const api = createApiClient("http://localhost:8016", async (input, init) => {
    assert.equal(new URL(String(input)).pathname, `/api/v1/plants/FTM/workbooks/${hash}/purge`);
    assert.equal(init?.method, "POST");
    assert.equal(init?.credentials, "omit");
    assert.deepEqual(JSON.parse(String(init?.body)), { reason: "Wrong layout" });
    return Response.json(
      {
        statusCode: 409,
        error: "Conflict",
        message: "Another file depends on this hash",
        correlationId: "test",
      },
      { status: 409 },
    );
  });
  await assert.rejects(
    api.purgeWorkbook("FTM", hash, { reason: "Wrong layout" }),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 409 &&
      error.body?.message === "Another file depends on this hash",
  );
});

test("readiness uses the root health path, cancellation and no credentials, with an unknown body", async () => {
  const controller = new AbortController();
  const api = createApiClient("http://localhost:8016", async (input, init) => {
    assert.equal(String(input), "http://localhost:8016/health/ready");
    assert.equal(init?.method, "GET");
    assert.equal(init?.signal, controller.signal);
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    return Response.json({ status: "ready", extra: [1] });
  });
  assert.deepEqual(await api.ready(controller.signal), { status: "ready", extra: [1] });
});

test("by-id and correction never inherit list filters; supersede uses strict JSON with no credentials", async () => {
  const requests: { url: URL; init?: RequestInit }[] = [];
  const api = createApiClient("http://localhost:8016", async (url, init) => {
    requests.push({ url: new URL(String(url)), init });
    return Response.json({});
  });
  await api.measurements({ plant: "FTM", model: "P703", date_from: "2026-01-01" });
  await api.measurement(41);
  await api.correct(41, { reason: "check", cf: "62.1234567890123456789" });
  await api.supersede(123, { reason: "bad workbook", replacement_load_id: 124 });
  assert.deepEqual(
    requests.slice(1).map(({ url }) => url.pathname + url.search),
    [
      "/api/v1/measurements/41",
      "/api/v1/measurements/41/corrections",
      "/api/v1/batches/123/supersede",
    ],
  );
  assert.deepEqual(JSON.parse(String(requests[2].init?.body)), {
    reason: "check",
    cf: "62.1234567890123456789",
  });
  assert.deepEqual(JSON.parse(String(requests[3].init?.body)), {
    reason: "bad workbook",
    replacement_load_id: 124,
  });
  for (const { init } of requests) {
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
  }
});

for (const status of [400, 403, 404, 409, 422])
  test(`T09 HTTP ${status} preserves the error envelope`, async () => {
    const body = {
      statusCode: status,
      error: "Refused",
      message: "Measurement 41 replaced by 42",
      correlationId: `t09-${status}`,
    };
    const api = createApiClient("http://localhost:8016", async () =>
      Response.json(body, { status }),
    );
    for (const action of [
      () => api.measurement(41),
      () => api.correct(41, { reason: "check", cf: "63" }),
      () => api.supersede(123, { reason: "check" }),
    ]) {
      await assert.rejects(
        action,
        (error: unknown) =>
          error instanceof ApiError &&
          error.status === status &&
          JSON.stringify(error.body) === JSON.stringify(body),
      );
    }
  });

test("reads preserve decimal strings and encode plant filters without credentials", async () => {
  const original = { items: [{ cf: "62.1234567890123456789" }] };
  const api = createApiClient("http://127.0.0.1:8012", async (input, init) => {
    const url = new URL(String(input));
    assert.equal(url.pathname, "/api/v1/measurements");
    assert.equal(url.searchParams.get("plant"), "AAT & FTM");
    assert.equal(url.searchParams.get("offset"), "50");
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    assert.equal(init?.method, "GET");
    return Response.json(original);
  });
  assert.deepEqual(await api.measurements({ plant: "AAT & FTM", offset: 50 }), original);
});

test("overview repeats model and color query params", async () => {
  const api = createApiClient("http://127.0.0.1:8012", async (input) => {
    const url = new URL(String(input));
    assert.equal(url.pathname, "/api/v1/plants/FTM/wavescan/overview");
    assert.equal(url.searchParams.get("month"), "2026-09");
    assert.deepEqual(url.searchParams.getAll("model"), ["P703 DBL RAPTOR", "P703 DBL RANGER"]);
    assert.deepEqual(url.searchParams.getAll("color"), ["Arctic White"]);
    return Response.json({ boxes: [] });
  });
  await api.wavescanOverview("FTM", {
    month: "2026-09",
    model: ["P703 DBL RAPTOR", "P703 DBL RANGER"],
    color: ["Arctic White"],
  });
});

test("base URL must be an explicit origin", () => {
  for (const base of [
    "",
    "http://localhost:8012/",
    "http://localhost:8012/api",
    "http://user:secret@localhost",
    "ftp://localhost",
    "http://localhost?x=y",
    "http://localhost#x",
  ]) {
    assert.throws(() => createApiClient(base), /VITE_API_BASE_URL/);
  }
});

for (const status of [401, 503]) {
  test(`HTTP ${status} is an error, never an empty page`, async () => {
    const api = createApiClient(
      "http://localhost:8012",
      async () => new Response("unavailable", { status }),
    );
    await assert.rejects(
      api.measurements({ plant: "AAT" }),
      (error: unknown) => error instanceof ApiError && error.status === status,
    );
  });
}

test("query cancellation reaches fetch", async () => {
  const controller = new AbortController();
  const api = createApiClient("http://localhost:8012", async (_input, init) => {
    assert.equal(init?.signal, controller.signal);
    throw new DOMException("Aborted", "AbortError");
  });
  await assert.rejects(api.measurements({ plant: "AAT" }, controller.signal), {
    name: "AbortError",
  });
});

test("upload sends repeated binary files and required expected plant with browser multipart boundary", async () => {
  const files = [new File(["one"], "one.xlsx"), new File(["two"], "two.xlsm")];
  const api = createApiClient("http://localhost:8012", async (input, init) => {
    assert.equal(new URL(String(input)).pathname, "/api/v1/uploads");
    assert.equal(init?.method, "POST");
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    assert.equal(new Headers(init?.headers).has("content-type"), false);
    assert.ok(init?.body instanceof FormData);
    assert.deepEqual([...init.body.keys()], ["files", "files", "expected_plant"]);
    assert.equal(init.body.get("expected_plant"), "FTM");
    const parts = init.body.getAll("files") as File[];
    assert.deepEqual(
      parts.map((part) => part.name),
      ["one.xlsx", "two.xlsm"],
    );
    assert.deepEqual(await Promise.all(parts.map((part) => part.text())), ["one", "two"]);
    return Response.json({ accepted_files: 2, batches: [] }, { status: 202 });
  });
  assert.equal((await api.upload({ files, expected_plant: "FTM" })).accepted_files, 2);
});

for (const status of [400, 403, 409, 422]) {
  test(`mutation HTTP ${status} preserves the contract message and correlation ID`, async () => {
    const body = {
      statusCode: status,
      error: "Refused",
      message: "Prior batch 123 / request refused",
      correlationId: "t07-trace",
    };
    const api = createApiClient("http://localhost:8012", async () =>
      Response.json(body, { status }),
    );
    await assert.rejects(
      api.upload({ files: [new File(["x"], "test.xlsx")], expected_plant: "AAT" }),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, status);
        assert.equal(error.message, body.message);
        assert.deepEqual(error.body, body);
        return true;
      },
    );
  });
}

test("batch reads forward paging and cancellation; commit has no body or credentials", async () => {
  const controller = new AbortController();
  const requests: string[] = [];
  const api = createApiClient("http://localhost:8012", async (input, init) => {
    requests.push(String(input));
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    assert.equal(init?.body, undefined);
    if (init?.method === "GET") assert.equal(init.signal, controller.signal);
    return Response.json({});
  });
  await api.batches({ offset: 20, limit: 10 }, controller.signal);
  await api.batch(123, controller.signal);
  await api.commit(123);
  assert.deepEqual(requests, [
    "http://localhost:8012/api/v1/batches?offset=20&limit=10",
    "http://localhost:8012/api/v1/batches/123",
    "http://localhost:8012/api/v1/batches/123/commit",
  ]);
});

test("plant workbook reads encode path values, paging, row filters and cancellation", async () => {
  const controller = new AbortController();
  const requests: string[] = [];
  const api = createApiClient("http://localhost:8012", async (input, init) => {
    requests.push(String(input));
    assert.equal(init?.method, "GET");
    assert.equal(init?.signal, controller.signal);
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    return Response.json({});
  });
  await api.workbooks("AAT & FTM", { offset: 200, limit: 200 }, controller.signal);
  await api.workbook("AAT & FTM", "hash/value", controller.signal);
  await api.workbookRows(
    "AAT & FTM",
    "hash/value",
    { load_id: 42, disposition: "QUARANTINE", offset: 50, limit: 50 },
    controller.signal,
  );
  await api.workbookIssues("AAT & FTM", "hash/value", controller.signal);
  await api.workbookHistory("AAT & FTM", "hash/value", controller.signal);
  assert.deepEqual(requests, [
    "http://localhost:8012/api/v1/plants/AAT%20%26%20FTM/workbooks?offset=200&limit=200",
    "http://localhost:8012/api/v1/plants/AAT%20%26%20FTM/workbooks/hash%2Fvalue",
    "http://localhost:8012/api/v1/plants/AAT%20%26%20FTM/workbooks/hash%2Fvalue/rows?load_id=42&disposition=QUARANTINE&offset=50&limit=50",
    "http://localhost:8012/api/v1/plants/AAT%20%26%20FTM/workbooks/hash%2Fvalue/issues",
    "http://localhost:8012/api/v1/plants/AAT%20%26%20FTM/workbooks/hash%2Fvalue/history",
  ]);
});

test("History reads encode plant and vehicle paths, preserve queries, cancellation and no credentials", async () => {
  const controller = new AbortController();
  const requests: string[] = [];
  const api = createApiClient("http://localhost:8012", async (input, init) => {
    requests.push(String(input));
    assert.equal(init?.method, "GET");
    assert.equal(init?.signal, controller.signal);
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    return Response.json({});
  });

  await api.historyFacets(
    "AAT & FTM",
    { month: "2026-09", model: "P703", color: "Frozen White" },
    controller.signal,
  );
  await api.historySummaries(
    "AAT & FTM",
    { month: "2026-09", color: "Frozen White" },
    controller.signal,
  );
  await api.historyVehicles(
    "AAT & FTM",
    {
      month: "2026-09",
      week: 5,
      model: "P703",
      color: "Frozen White",
      limit: 20,
      offset: 40,
    },
    controller.signal,
  );
  await api.historyVehiclePoints(
    "AAT & FTM",
    "vehicle/value",
    { limit: 100, offset: 200 },
    controller.signal,
  );

  assert.deepEqual(requests, [
    "http://localhost:8012/api/v1/plants/AAT%20%26%20FTM/history/facets?month=2026-09&model=P703&color=Frozen+White",
    "http://localhost:8012/api/v1/plants/AAT%20%26%20FTM/history/summaries?month=2026-09&color=Frozen+White",
    "http://localhost:8012/api/v1/plants/AAT%20%26%20FTM/history/vehicles?month=2026-09&week=5&model=P703&color=Frozen+White&limit=20&offset=40",
    "http://localhost:8012/api/v1/plants/AAT%20%26%20FTM/history/vehicles/vehicle%2Fvalue/points?limit=100&offset=200",
  ]);
});

test("acknowledgement posts the exact generated body without credentials", async () => {
  const body = {
    load_id: 42,
    category: "REJECTED_ROWS" as const,
    review_revision: "a".repeat(64),
    note: "Reviewed against the source workbook",
  };
  const api = createApiClient("http://localhost:8012", async (input, init) => {
    assert.equal(
      String(input),
      "http://localhost:8012/api/v1/plants/FTM/workbooks/hash/acknowledgements",
    );
    assert.equal(init?.method, "POST");
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).get("content-type"), "application/json");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    assert.deepEqual(JSON.parse(String(init?.body)), body);
    return Response.json({}, { status: 201 });
  });
  await api.acknowledge("FTM", "hash", body);
});

test("template publish posts the exact generated body without credentials", async () => {
  const body = {
    file_hash: "a".repeat(64),
    source_sheet: "CF Data",
    named_owner: "Somchai Quality",
    notes: "Verified against the stored September export",
    fill_missing_plant: false,
    ignored_headers: [{ header: "Panel2", reason: "Export-only helper column" }],
  };
  const published = {
    profile_id: 81,
    version: 2,
    domain: "WAVESCAN",
    plant_code: "FTM",
    semantic_signature: "b".repeat(64),
    template_fingerprint: "c".repeat(64),
    fixture_verified: true,
    fixture_file_hash: body.file_hash,
    named_owner: body.named_owner,
    previous_profile_id: 75,
    ignored_headers: 1,
    replayed_load_ids: [123, 124],
    audit_action: "profile.publish",
  };
  const api = createApiClient("http://localhost:8012", async (input, init) => {
    assert.equal(
      String(input),
      "http://localhost:8012/api/v1/plants/FTM/template-profiles/publish",
    );
    assert.equal(init?.method, "POST");
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).get("content-type"), "application/json");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    assert.deepEqual(JSON.parse(String(init?.body)), body);
    return Response.json(published);
  });
  assert.deepEqual(await api.publishTemplateProfile("FTM", body), published);
});

for (const status of [403, 404, 409, 422]) {
  test(`template publish HTTP ${status} preserves message and correlation ID`, async () => {
    const response = {
      statusCode: status,
      error: "Publish refused",
      message: "Stored workbook cannot prove this contract",
      correlationId: `publish-${status}`,
    };
    const api = createApiClient("http://localhost:8012", async () =>
      Response.json(response, { status }),
    );
    await assert.rejects(
      api.publishTemplateProfile("FTM", {
        file_hash: "a".repeat(64),
        source_sheet: "CF Data",
        named_owner: "Somchai Quality",
        notes: "Verified stored workbook",
        fill_missing_plant: false,
      }),
      (error: unknown) =>
        error instanceof ApiError &&
        error.status === status &&
        error.message === response.message &&
        error.body?.correlationId === response.correlationId,
    );
  });
}

test("T21 client exposes vehicle review and reason-only abandon with exact string overrides", async () => {
  const requests: { url: URL; init?: RequestInit }[] = [];
  const api = createApiClient("http://localhost:8012", async (input, init) => {
    requests.push({ url: new URL(String(input)), init });
    return Response.json({});
  });
  assert.equal(typeof api.workbookVehicles, "function");
  assert.equal(typeof api.workbookVehiclePoints, "function");
  assert.equal(typeof api.overrideWorkbook, "function");
  assert.equal(typeof api.abandon, "function");
  const signal = new AbortController().signal;
  await api.workbooks(
    "FTM",
    { inbox: "current_month", uploaded_month: "2026-09", limit: 200, offset: 0 },
    signal,
  );
  await api.workbookVehicles(
    "FTM",
    "a".repeat(64),
    { load_id: 123, limit: 200, offset: 200 },
    signal,
  );
  await api.workbookVehiclePoints(
    "FTM",
    "a".repeat(64),
    "d".repeat(64),
    { limit: 500, offset: 500 },
    signal,
  );
  const body = {
    load_id: 123,
    vehicle_id: "d".repeat(64),
    review_revision: "b".repeat(64),
    changes: [
      {
        source_row: 2,
        field: "cf" as const,
        value: "55.1234567890123456789",
        reason: "Instrument review",
      },
      { source_row: 2, field: "b" as const, value: null, reason: "No reading" },
    ],
  };
  await api.overrideWorkbook("FTM", "a".repeat(64), body);
  await api.abandon(123, { reason: "Wrong source" });
  assert.equal(requests[0].url.searchParams.get("inbox"), "current_month");
  assert.equal(requests[0].url.searchParams.get("uploaded_month"), "2026-09");
  assert.equal(requests[1].url.searchParams.get("load_id"), "123");
  assert.equal(requests[1].url.searchParams.get("offset"), "200");
  assert.ok(requests[2].url.pathname.endsWith(`/vehicles/${"d".repeat(64)}/points`));
  assert.equal(requests[2].url.searchParams.get("offset"), "500");
  assert.deepEqual(JSON.parse(String(requests[3].init?.body)), body);
  assert.deepEqual(JSON.parse(String(requests[4].init?.body)), { reason: "Wrong source" });
  assert.equal(requests[4].url.pathname, "/api/v1/batches/123/abandon");
  for (const { init } of requests) {
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    if (init?.method === "GET") assert.equal(init.signal, signal);
  }
});
