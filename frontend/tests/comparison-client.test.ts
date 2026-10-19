import test from "node:test";
import assert from "node:assert/strict";
import { createApiClient, ApiError } from "../src/api/client";

test("T80 picker repeats filters and aligned points preserve ordered IDs with omit credentials", async () => {
  const calls: Array<{ url: URL; init: RequestInit }> = [];
  const client = createApiClient("http://localhost:8012", (async (input, init) => {
    calls.push({ url: new URL(String(input)), init: init! });
    return new Response(JSON.stringify({ items: [] }), { status: 200 });
  }) as typeof fetch);
  assert.equal(typeof client.comparisonVehicles, "function");
  await client.comparisonVehicles("AAT", {
    domain: "WAVESCAN",
    month: ["2026-06", "2026-07"],
    color: ["Arctic White", "Traction Green"],
    period: ["2026-06-W4", "2026-07-W1"],
    model: "P703 DBL RANGER",
    q: "Alpha",
    limit: 50,
    offset: 50,
  });
  await client.comparisonPoints("AAT", {
    domain: "WAVESCAN",
    model: "P703 DBL RANGER",
    metric: "cf",
    vehicle_id: ["b".repeat(64), "a".repeat(64)],
  });
  assert.deepEqual(calls[0].url.searchParams.getAll("month"), ["2026-06", "2026-07"]);
  assert.deepEqual(calls[0].url.searchParams.getAll("color"), ["Arctic White", "Traction Green"]);
  assert.deepEqual(calls[0].url.searchParams.getAll("period"), ["2026-06-W4", "2026-07-W1"]);
  assert.equal(calls[0].url.searchParams.get("offset"), "50");
  assert.deepEqual(calls[1].url.searchParams.getAll("vehicle_id"), [
    "b".repeat(64),
    "a".repeat(64),
  ]);
  assert.ok(
    calls.every(({ init }) => init.credentials === "omit" && init.method === "GET" && !init.body),
  );
});

test("T80 Comparison errors retain message and correlation ID", async () => {
  const client = createApiClient(
    "http://localhost:8012",
    (async () =>
      new Response(
        JSON.stringify({
          statusCode: 404,
          error: "Not Found",
          message: "Vehicle no longer active",
          correlationId: "T80-read-error",
        }),
        { status: 404 },
      )) as typeof fetch,
  );
  await assert.rejects(
    () =>
      client.comparisonPoints("FTM", {
        domain: "FILMTHICKNESS",
        model: "P703 DBL RANGER",
        metric: "clear",
        vehicle_id: ["a".repeat(64)],
      }),
    (error: unknown) =>
      error instanceof ApiError &&
      error.message === "Vehicle no longer active" &&
      error.body?.correlationId === "T80-read-error",
  );
});
