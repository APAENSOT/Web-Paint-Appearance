import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { buildCorrection, correctionValues, supersedeSchema } from "../src/api/correction-form";
import { refreshActiveMeasurements } from "../src/api/queries";
import { MeasurementTable } from "../src/features/measurements/MeasurementTable";
import { BatchReviewCard } from "../src/features/intake/BatchReviewCard";
import { createApiClient } from "../src/api/client";
import { cleanReview, identity, measurement } from "./fixtures";

test("correction sends trimmed reason and changed decimal strings only, with explicit B clearing", () => {
  assert.deepEqual(
    buildCorrection(
      measurement,
      { ...correctionValues(measurement), cf: "62.1234567890123456789", b: "" },
      "  instrument check  ",
    ),
    {
      reason: "instrument check",
      cf: "62.1234567890123456789",
      b: null,
    },
  );
  assert.deepEqual(buildCorrection(measurement, { cf: "062.000", sw: "4.3" }, "check"), {
    reason: "check",
    sw: "4.3",
  });
});

test("form refuses identity keys, unchanged values, invalid ranges and dates before POST", () => {
  for (const key of [
    "plant",
    "model",
    "checkzone",
    "color",
    "tolerance_group",
    "paintline",
    "load_id",
    "source_sheet",
    "source_row",
  ]) {
    assert.throws(() => buildCorrection(measurement, { cf: "63", [key]: "changed" }, "check"));
  }
  for (const [changes, reason] of [
    [{}, "reason only"],
    [{ cf: "62.00" }, "unchanged"],
    [{ cf: "63" }, "  "],
    [{ cf: "63" }, "x".repeat(2001)],
    [{ cf: "101" }, "check"],
    [{ cf: "100.00000000000000000001" }, "check"],
    [{ cf: "NaN" }, "check"],
    [{ doi: "-1" }, "check"],
    [{ b: "-100.001" }, "check"],
    [{ lw: "-0.01" }, "check"],
    [{ cf: 63 }, "check"],
    [{ serial_no: "   " }, "check"],
    [{ measured_date: "1990-01-01" }, "check"],
    [{ measured_date: "2101-01-01" }, "check"],
    [{ measured_date: "2026-02-30" }, "check"],
  ] as const)
    assert.throws(() => buildCorrection(measurement, changes, reason));
  assert.deepEqual(
    buildCorrection(measurement, { measured_date: "2000-01-01", b: "-100" }, "check"),
    { reason: "check", measured_date: "2000-01-01", b: "-100" },
  );
  assert.equal(supersedeSchema.safeParse({ reason: " " }).success, false);
  assert.deepEqual(supersedeSchema.parse({ reason: " check " }), { reason: "check" });
});

test("unchanged nullable serial in the API response does not require an unrelated serial correction", () => {
  const row = { ...measurement, serial_no: null };
  assert.deepEqual(buildCorrection(row, { ...correctionValues(row), cf: "63" }, "check"), {
    reason: "check",
    cf: "63",
  });
});

for (const role of ["viewer", "engineer", "admin"] as const) {
  test(`${role} correction and supersede chrome comes from API identity`, () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
    client.setQueryData(["identity"], {
      ...identity,
      principal: { ...identity.principal, roles: [role] },
    });
    const table = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <MeasurementTable rows={[measurement]} />
      </QueryClientProvider>,
    );
    assert.equal(table.includes("Correct measurement 41"), role !== "viewer");
    for (const status of [
      "COMMITTED",
      "SUPERSEDED",
      "RUNNING",
      "PENDING_REVIEW",
      "FAILED",
      "REJECTED_TEMPLATE",
    ] as const) {
      client.setQueryData(["batch", 123], {
        ...cleanReview,
        batch: { ...cleanReview.batch, plant_code: null, status },
      });
      const card = renderToStaticMarkup(
        <QueryClientProvider client={client}>
          <BatchReviewCard id={123} canMutate={role !== "viewer"} />
        </QueryClientProvider>,
      );
      assert.equal(
        card.includes("Supersede batch</button>"),
        role === "admin" && status === "COMMITTED",
      );
    }
    client.clear();
  });
}

test("successful retirement clears cached active rows even if the next read fails", async () => {
  const client = new QueryClient();
  client.setQueryData(["measurements", "AAT", 0], { items: [measurement] });
  client.setQueryData(["measurement", 41], measurement);
  await refreshActiveMeasurements(client);
  assert.equal(client.getQueryData(["measurements", "AAT", 0]), undefined);
  assert.equal(client.getQueryData(["measurement", 41]), undefined);
  client.clear();
});

test("after a mocked 201 the refetched table contains the replacement ID and not the retired ID", async () => {
  const replacement = { ...measurement, measurement_id: 42, cf: "63", corrects_measurement_id: 41 };
  let active = measurement;
  const api = createApiClient("http://localhost:8016", async () => {
    active = replacement;
    return Response.json(
      {
        measurement: replacement,
        superseded_measurement_id: 41,
        supersession_id: 7,
        audit_action: "measurement.correct",
        note: "Retained",
      },
      { status: 201 },
    );
  });
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], identity);
  const options = {
    queryKey: ["measurements", "AAT", 0],
    queryFn: async () => ({ items: [active], page: { total: 1 } }),
  };
  await client.fetchQuery(options);
  await api.correct(41, { reason: "check", cf: "63" });
  await refreshActiveMeasurements(client);
  const refreshed = await client.fetchQuery(options);
  const table = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MeasurementTable rows={refreshed.items} />
    </QueryClientProvider>,
  );
  assert.equal(table.includes('data-measurement-id="41"'), false);
  assert.equal(table.includes('data-measurement-id="42"'), true);
  assert.equal(refreshed.page.total, 1);
  client.clear();
});
