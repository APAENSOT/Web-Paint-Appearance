import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { ApiError, createApiClient } from "../src/api/client";
import {
  PairingReadiness,
  PairingReadinessView,
  type PairingReadinessData,
} from "../src/features/analysis/PairingReadiness";

const kinds = [
  "film_no_car_number",
  "wavescan_serial_not_7_digits",
  "film_colour_code_shared",
  "pair_model_mismatch",
  "pair_colour_mismatch",
  "wavescan_reading_unmapped",
  "film_reading_unmapped",
];

const ftm: PairingReadinessData = {
  plant_code: "FTM",
  car_rule: { pattern: "^[A-Z]{2}_[A-Z]{2,3}_(\\d{7})$", note: "FTM job_no" },
  wavescan_cars: 47,
  film_cars: 169,
  paired_cars: 6,
  by_model_colour: [
    {
      model: "P703 DBL RANGER",
      color: "Arctic White",
      wavescan_cars: 9,
      film_cars: 20,
      paired_cars: 1,
    },
  ],
  by_pair_group: [
    {
      pair_group: "L_FENDER",
      wavescan_zones: ["LCFENDER", "LFFENDER", "LRFENDER"],
      film_points: 5,
      paired_cars: 6,
    },
    { pair_group: "TAILGATE", wavescan_zones: ["LTTAILGATE"], film_points: 9, paired_cars: 0 },
  ],
  pairs: [
    {
      car_no: "1967069",
      wavescan_model: "P703 DBL RANGER",
      film_model: "P703 DBL RAPTOR",
      wavescan_color: "Desert Island Blue",
      film_color: "Desert Island Blue",
      wavescan_dates: ["2026-08-19"],
      film_dates: ["2026-08-20"],
      gap_days: 1,
      flags: ["model_mismatch"],
    },
  ],
  quality: kinds.map((kind) =>
    kind === "film_colour_code_shared"
      ? { kind, count: 1, examples: ["AM: Aluminum Metallic (11), Arctic White (AM_SGL_1961607)"] }
      : { kind, count: 0, examples: [] },
  ),
};

const html = (data: PairingReadinessData) =>
  renderToStaticMarkup(<PairingReadinessView data={data} />);

test("renders the counts, the group table, a flagged pair and the quality list", () => {
  const out = html(ftm);
  assert.match(out, /data-testid="pairing-counts"/);
  for (const n of ["47", "169", ">6<"]) assert.ok(out.includes(n), n);
  assert.match(out, /data-pair-group="L_FENDER"/);
  assert.match(out, /LCFENDER LFFENDER LRFENDER/);
  assert.match(out, /data-pair="1967069"/);
  assert.match(out, /P703 DBL RANGER \/ P703 DBL RAPTOR/);
  assert.match(out, /data-testid="pairing-flags-1967069">Model differs</);
  for (const kind of kinds) assert.match(out, new RegExp(`data-quality="${kind}"`));
  assert.match(out, /AM: Aluminum Metallic \(11\), Arctic White \(AM_SGL_1961607\)/);
  assert.doesNotMatch(out, /pairing-no-rule/);
});

test("a plant with no car rule says so in one plain sentence", () => {
  const out = html({ ...ftm, plant_code: "AAT", car_rule: null, paired_cars: 0, pairs: [] });
  assert.ok(out.includes("No film car-number rule for this plant yet."));
  assert.match(out, /data-testid="pairing-no-pairs"/);
});

test("nothing is shown as a percentage", () => {
  assert.doesNotMatch(html(ftm), /%/);
});

test("at 390 px only the tables scroll, never the page", () => {
  const out = html(ftm);
  assert.match(out, /class="panel min-w-0/);
  const tables = out.match(/<table/g)?.length ?? 0;
  const wrapped = out.match(/overflow-x-auto[^>]*><table/g)?.length ?? 0;
  assert.equal(tables, 3);
  assert.equal(wrapped, tables);
  assert.doesNotMatch(out, /min-w-\[(?:[4-9]\d\d|\d{4,})px\]|w-\[(?:[4-9]\d\d|\d{4,})px\]/);
});

test("uses the house panel classes and no chart library", () => {
  const source = readFileSync(
    new URL("../src/features/analysis/PairingReadiness.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /className="panel /);
  assert.doesNotMatch(source, /from "(recharts|chart\.js|d3|echarts|plotly)/);
  const imports = [...source.matchAll(/from "([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(
    imports.filter(
      (m) =>
        ![
          "react",
          "@tanstack/react-query",
          "@/api/queries",
          "@/api/types",
          "@/components/ApiState",
        ].includes(m),
    ),
    [],
  );
});

const KEY = ["analysis", "pairing", "FTM"];
const mounted = (client: QueryClient) =>
  renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <PairingReadiness code="ftm" />
    </QueryClientProvider>,
  );

test("the wrapper shows loading, then the API error, then the counts", async () => {
  assert.match(mounted(new QueryClient()), /Loading pairing counts/);

  const failed = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } });
  const error = new ApiError(404, {
    statusCode: 404,
    error: "Not Found",
    message: "No plant 'FTM'.",
    correlationId: "c",
  } as never);
  await failed.prefetchQuery({ queryKey: KEY, queryFn: () => Promise.reject(error), retry: false });
  const out = mounted(failed);
  assert.match(out, /role="alert"/);
  assert.match(out, /HTTP 404/);
  assert.doesNotMatch(out, /pairing-panel/);

  const ok = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  ok.setQueryData(KEY, ftm);
  assert.match(mounted(ok), /data-testid="pairing-panel"/);
});

test("the client reads the pairing path with the plant encoded", async () => {
  let requested = "";
  const client = createApiClient("http://localhost:8012", (async (input) => {
    requested = String(input);
    return Response.json(ftm);
  }) as typeof fetch);
  const body = await client.pairingReadiness("FTM");
  assert.equal(requested, "http://localhost:8012/api/v1/plants/FTM/analysis/pairing");
  assert.equal(body.paired_cars, 6);
});
