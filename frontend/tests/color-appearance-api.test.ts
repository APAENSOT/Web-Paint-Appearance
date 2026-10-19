import test from "node:test";
import assert from "node:assert/strict";
import { ApiError, createApiClient } from "../src/api/client.ts";

test("colour appearance reads remain distinct from an empty profile, and saves encode canonical names", async () => {
  const calls: { path: string; method: string; body: unknown }[] = [];
  const client = createApiClient("http://localhost:8012", (async (input, init) => {
    const url = new URL(String(input));
    calls.push({
      path: url.pathname,
      method: init?.method ?? "GET",
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    return Response.json(
      init?.method === "POST"
        ? {
            color_name: "Absolute / Shadow Black",
            hex: "#123456",
            revision: 1,
            saved_at: "2026-10-12T00:00:00Z",
            saved_by: "Engineer",
            replayed: false,
          }
        : {
            plant_code: "FTM",
            items: [
              { color_name: "Absolute / Shadow Black", family_name: "Black", appearance: null },
            ],
            unavailable: [],
          },
    );
  }) as typeof fetch);

  const read = await client.colorAppearances("FTM");
  assert.equal(read.items[0].appearance, null);
  await client.saveColorAppearance("FTM", "Absolute / Shadow Black", {
    hex: "#123456",
    expected_revision: null,
  });
  assert.deepEqual(calls, [
    { path: "/api/v1/plants/FTM/color-appearances", method: "GET", body: null },
    {
      path: "/api/v1/plants/FTM/color-appearances/Absolute%20%2F%20Shadow%20Black",
      method: "POST",
      body: { hex: "#123456", expected_revision: null },
    },
  ]);
});

test("a failed appearance read and a revision conflict retain API error status and message", async () => {
  const client = createApiClient("http://localhost:8012", (async () =>
    Response.json(
      {
        statusCode: 409,
        error: "Conflict",
        message: "Current revision 2 (#AABBCC)",
        correlationId: "test",
      },
      { status: 409 },
    )) as typeof fetch);
  await assert.rejects(
    client.saveColorAppearance("FTM", "Blue", { hex: "#123456", expected_revision: 1 }),
    (error: unknown) =>
      error instanceof ApiError && error.status === 409 && error.message.includes("revision 2"),
  );
});
