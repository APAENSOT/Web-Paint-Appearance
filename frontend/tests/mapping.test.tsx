import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BatchReviewCard } from "../src/features/intake/BatchReviewCard";
import { createApiClient, ApiError } from "../src/api/client";
import { cleanReview, identity } from "./fixtures";
import { refreshAfterApproval, batchOptions } from "../src/api/queries";
import { columnPayload, modelAliasPayload } from "../src/api/mapping-state";
import type { components } from "../src/api/types";

test("payload validation refuses extra keys and non-staged logical fields", () => {
  assert.equal(
    columnPayload.safeParse({ raw_header: "panel", logical_field: "checkzone", extra: true })
      .success,
    false,
  );
  assert.equal(
    columnPayload.safeParse({ raw_header: "panel", logical_field: "invented" }).success,
    false,
  );
  assert.equal(
    modelAliasPayload.safeParse({ raw_value: "truck spelling", model_code: "U704", extra: true })
      .success,
    false,
  );
});

test("approval clears stale committable state and reuses T07 backoff; terminal review stops polling", async () => {
  const client = new QueryClient();
  client.setQueryData(["batch", 123], cleanReview);
  await refreshAfterApproval(client, {
    proposal: { load_id: 123 },
    replay: { load_id: 123, status: "RUNNING" },
  } as components["schemas"]["ApprovalResult"]);
  const review = client.getQueryData<components["schemas"]["BatchReviewOut"]>(["batch", 123])!;
  assert.equal(review.committable, false);
  assert.equal(review.batch.status, "RUNNING");
  assert.equal(review.batch.job?.status, "QUEUED");
  const poll = batchOptions(123).refetchInterval;
  assert.equal(typeof poll, "function");
  if (typeof poll !== "function") return;
  type Review = components["schemas"]["BatchReviewOut"];
  const query = client
    .getQueryCache()
    .build<Review, Error, Review, (string | number)[]>(client, { queryKey: ["batch", 123] });
  // Exercise the production callback at the same query update counts as T07.
  for (const [updates, expected] of [
    [1, 1000],
    [2, 2000],
    [3, 4000],
    [4, 8000],
    [10, 10000],
  ]) {
    query.setState({ dataUpdateCount: updates });
    assert.equal(poll(query), expected);
  }
  client.setQueryData(["batch", 123], cleanReview);
  assert.equal(poll(query), false);
  client.clear();
});

test("mapping client encodes filtered reads and JSON proposal; approval has no body or identity headers", async () => {
  const calls: string[] = [];
  const body = {
    kind: "COLUMN" as const,
    load_id: 123,
    payload: { raw_header: "panel", logical_field: "checkzone" },
  };
  const controller = new AbortController();
  const api = createApiClient("http://localhost:8016", async (input, init) => {
    calls.push(String(input));
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("authorization"), false);
    if (init?.method === "GET") assert.equal(init.signal, controller.signal);
    if (init?.body) {
      assert.equal(new Headers(init.headers).get("content-type"), "application/json");
      assert.deepEqual(JSON.parse(String(init.body)), body);
    }
    return Response.json({});
  });
  await api.proposals({ load_id: 123, offset: 20, limit: 10 }, controller.signal);
  await api.proposal("id/with space", controller.signal);
  await api.propose(body);
  await api.approve("id/with space");
  assert.deepEqual(calls, [
    "http://localhost:8016/api/v1/mappings/proposals?load_id=123&offset=20&limit=10",
    "http://localhost:8016/api/v1/mappings/proposals/id%2Fwith%20space",
    "http://localhost:8016/api/v1/mappings/proposals",
    "http://localhost:8016/api/v1/mappings/proposals/id%2Fwith%20space/approve",
  ]);
});

for (const status of [400, 403, 404, 409, 422, 501]) {
  test(`mapping HTTP ${status} retains all error fields, including extra-key 422`, async () => {
    const body = {
      statusCode: status,
      error: "Refused",
      message: "Mapping refused",
      correlationId: "t08-trace",
    };
    const api = createApiClient("http://localhost:8016", async () =>
      Response.json(body, { status }),
    );
    await assert.rejects(
      api.propose({
        kind: "COLUMN",
        load_id: 123,
        payload: { raw_header: "x", logical_field: "checkzone", extra: true },
      }),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.deepEqual(error.body, body);
        return true;
      },
    );
    await assert.rejects(
      api.approve("proposal"),
      (error: unknown) => error instanceof ApiError && error.body?.correlationId === "t08-trace",
    );
  });
}

for (const role of ["viewer", "engineer", "admin"] as const) {
  test(`${role} mapping chrome respects identity and never offers diagnostic approval`, () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
    client.setQueryData(["identity"], {
      ...identity,
      principal: { ...identity.principal, roles: [role] },
    });
    client.setQueryData(["batch", 123], {
      ...cleanReview,
      committable: false,
      batch: { ...cleanReview.batch, status: "REJECTED_TEMPLATE" },
    });
    const base = {
      kind: "COLUMN",
      load_id: 123,
      status: "PROPOSED",
      similarity: "0.99",
      proposed_by: null,
      decided_by: null,
      created_at: "2026-09-13T00:00:00Z",
      decided_at: null,
    };
    client.setQueryData(["proposals", 123, 0], {
      items: [
        {
          ...base,
          id: "diagnostic",
          payload: {
            missing_required: ["checkzone"],
            unrecognised_headers: ["unknown-panel"],
            after_replay: true,
          },
        },
        {
          ...base,
          id: "applicable",
          payload: { raw_header: "unknown-panel", logical_field: "checkzone" },
        },
      ],
      page: { offset: 0, limit: 10, returned: 2, total: 2 },
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <BatchReviewCard id={123} canMutate={role !== "viewer"} />
      </QueryClientProvider>,
    );
    assert.ok(html.includes("unknown-panel"));
    assert.ok(html.includes("Missing required"));
    assert.ok(html.includes("After replay"));
    assert.ok(html.includes("0.99"));
    // RO12 CHANGE (D-RO12-4): propose is an Engineer route; a Viewer is not offered it.
    assert.equal(html.includes("Propose mapping</button>"), role !== "viewer");
    assert.equal(
      (html.match(/>Approve &amp; replay<\/button>/g) ?? []).length,
      role === "admin" ? 1 : 0,
    );
    client.clear();
  });
}
