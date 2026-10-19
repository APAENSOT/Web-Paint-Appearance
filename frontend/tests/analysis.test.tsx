import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { createApiClient } from "../src/api/client";
import { buildPreviewQuery } from "../src/api/preview-query";
import { GradingUnavailable, TruncationNotice } from "../src/features/analysis/PreviewNotices";
import { PointDetails } from "../src/features/analysis/PointDetails";
import { measurement } from "./fixtures";

test("preview filters omit empty and non-preview keys, preserve canonical values and default cap", async () => {
  const query = buildPreviewQuery({
    plant: "AAT",
    model: "",
    color: "White",
    checkzone: null,
    date_from: "",
    dimension: "color",
    ...{ color_group: "WHITE", grading_family: "solid", point_limit: 20000 },
  });
  assert.deepEqual(query, { plant: "AAT", color: "White", dimension: "color" });
  let requested = "";
  const api = createApiClient("http://localhost:8000", async (url, init) => {
    requested = String(url);
    assert.equal(init?.credentials, "omit");
    assert.equal(new Headers(init?.headers).has("Authorization"), false);
    return new Response(JSON.stringify({ series: [] }));
  });
  await api.preview(query);
  assert.equal(
    requested,
    "http://localhost:8000/api/v1/dashboard/preview?dimension=color&plant=AAT&color=White",
  );
});

test("preview rejects reversed, impossible and outside-window dates before request", () => {
  for (const query of [
    { date_from: "2026-09-14", date_to: "2026-09-13" },
    { date_from: "1999-12-31" },
    { date_to: "2101-01-01" },
    { date_from: "2026-02-30" },
  ])
    assert.throws(() => buildPreviewQuery(query), /date/i);
  assert.deepEqual(buildPreviewQuery({ date_from: "2000-01-01", date_to: "2100-12-31" }), {
    date_from: "2000-01-01",
    date_to: "2100-12-31",
  });
});

test("cap banner appears only for truncated payload and quotes returned cap", () => {
  assert.match(renderToStaticMarkup(<TruncationNotice truncated point_limit={5000} />), /5000/);
  assert.equal(renderToStaticMarkup(<TruncationNotice truncated={false} point_limit={5000} />), "");
});

test("tooltip preserves full API CF string and point identity", () => {
  const html = renderToStaticMarkup(
    <PointDetails seriesKey="RRHOOD" point={{ ...measurement, cf: "62.1234567890123456789" }} />,
  );
  assert.match(html, /62\.1234567890123456789/);
  assert.match(html, /RRHOOD/);
  assert.match(html, /2026-09-13/);
});

test("grading is unavailable with no numeric KPI or grade", () => {
  const html = renderToStaticMarkup(
    <GradingUnavailable grading_note="Grouping remains unresolved." />,
  );
  assert.match(html, /Grading unavailable/);
  assert.match(html, /Grouping remains unresolved/);
  assert.doesNotMatch(html.replace(/<[^>]*>/g, ""), /%|PASS|FAIL|Ford|\d/);
});

test("table preserves the decimal string and canonical plant link", async () => {
  const { createMemoryHistory, createRootRoute, createRouter, RouterProvider } =
    await import("@tanstack/react-router");
  const { PreviewTable } = await import("../src/features/analysis/PreviewTable");
  const route = createRootRoute({
    component: () => (
      <PreviewTable
        series={[{ key: "RRHOOD", points: [{ ...measurement, cf: "62.1234567890123456789" }] }]}
      />
    ),
  });
  const router = createRouter({ routeTree: route, history: createMemoryHistory() });
  await router.load();
  const html = renderToStaticMarkup(<RouterProvider router={router} />);
  assert.match(html, /62\.1234567890123456789/);
  assert.match(html, /href="\/plant\/AAT"/);
});

test("retirement clears every filtered preview and preview does not retry", async () => {
  const { QueryClient } = await import("@tanstack/react-query");
  const { refreshActiveMeasurements, previewOptions } = await import("../src/api/queries");
  const client = new QueryClient();
  for (const query of [{ plant: "AAT" }, { dimension: "color" as const }])
    client.setQueryData(["preview", query], { series: [{ key: "RRHOOD", points: [measurement] }] });
  await refreshActiveMeasurements(client);
  assert.equal(client.getQueryData(previewOptions({ plant: "AAT" }).queryKey), undefined);
  assert.equal(client.getQueryData(previewOptions({ dimension: "color" }).queryKey), undefined);
  assert.equal(previewOptions({}).retry, false);
  client.clear();
});
