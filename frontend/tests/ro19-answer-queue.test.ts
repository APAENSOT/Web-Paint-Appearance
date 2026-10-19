import assert from "node:assert/strict";
import { test } from "node:test";
import { createApiClient } from "../src/api/client.ts";

test("ten quick answers wait for the tab to be reread and all apply in order", async () => {
  let reading = false;
  const applied: string[] = [];
  const client = createApiClient("http://localhost:8012", async (input, options) => {
    if (options?.method === "GET") {
      const state = reading ? "processing" : "needs_answer";
      reading = false;
      return Response.json({ sheets: [{ load_id: 19, state }] });
    }
    if (reading)
      return Response.json(
        { statusCode: 409, error: "Conflict", message: "held for: nothing" },
        { status: 409 },
      );
    applied.push(JSON.parse(String(options?.body)).raw_location);
    reading = true;
    return Response.json({ replayed_load_ids: [19], operator_message: "Reading again" });
  });
  const answers = Array.from({ length: 10 }, (_, i) => `label ${i}`);
  await Promise.all(
    answers.map((raw_location) =>
      client.answerFilmNotAPoint("FTM", "a".repeat(64), { load_id: 19, raw_location }),
    ),
  );
  assert.deepEqual(applied, answers);
  assert.equal(reading, false);
});

// `api()` (src/api/queries.ts) builds a new client on every call, so the queue
// has to be shared between clients, not per client. Those queries cannot be
// imported here: they read `import.meta.env`, which node --test does not have.
test("two separately built clients still serialise answers to one workbook", async () => {
  let reading = false;
  const applied: string[] = [];
  const fetcher: typeof fetch = async (_, options) => {
    if (options?.method === "GET") {
      const state = reading ? "processing" : "needs_answer";
      reading = false;
      return Response.json({ sheets: [{ load_id: 19, state }] });
    }
    if (reading)
      return Response.json(
        { statusCode: 409, error: "Conflict", message: "held for: nothing" },
        { status: 409 },
      );
    applied.push(JSON.parse(String(options?.body)).raw_location);
    reading = true;
    return Response.json({ replayed_load_ids: [19], operator_message: "Reading again" });
  };
  const workbook = "c".repeat(64);
  const answer = (raw_location: string) =>
    createApiClient("http://localhost:8012", fetcher).answerFilmNotAPoint("FTM", workbook, {
      load_id: 19,
      raw_location,
    });
  await Promise.all([answer("first"), answer("second")]);
  assert.deepEqual(applied, ["first", "second"]);
  assert.equal(reading, false);
});

test("a failed queued answer is reported and does not discard the next answer", async () => {
  const applied: string[] = [];
  const client = createApiClient("http://localhost:8012", async (_, options) => {
    const label = JSON.parse(String(options?.body)).raw_location;
    if (label === "wrong")
      return Response.json(
        { statusCode: 422, error: "Unprocessable Entity", message: "Not offered" },
        { status: 422 },
      );
    applied.push(label);
    return Response.json({ replayed_load_ids: [] });
  });
  const results = await Promise.allSettled(
    ["wrong", "right"].map((raw_location) =>
      client.answerFilmNotAPoint("FTM", "b".repeat(64), { load_id: 19, raw_location }),
    ),
  );
  assert.equal(results[0].status, "rejected");
  assert.equal(results[1].status, "fulfilled");
  assert.deepEqual(applied, ["right"]);
});

test("a saved answer is not reported as failed when one re-read check fails", async () => {
  let gets = 0;
  const client = createApiClient("http://localhost:8012", async (_, options) => {
    if (options?.method === "GET") {
      gets += 1;
      if (gets === 1)
        return Response.json(
          { statusCode: 503, error: "Service Unavailable", message: "busy" },
          { status: 503 },
        );
      return Response.json({ sheets: [{ load_id: 19, state: "needs_answer" }] });
    }
    return Response.json({ replayed_load_ids: [19], operator_message: "Reading again" });
  });
  const result = await client.answerFilmNotAPoint("FTM", "d".repeat(64), {
    load_id: 19,
    raw_location: "saved",
  });
  assert.deepEqual(result.replayed_load_ids, [19]);
  assert.equal(gets, 2);
});
