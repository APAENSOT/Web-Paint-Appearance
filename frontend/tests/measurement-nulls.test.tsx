import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MeasurementTable } from "../src/features/measurements/MeasurementTable";
import { identity, measurement } from "./fixtures";

// Backend T76: MeasurementOut lw/sw/doi (and du..we) are nullable; NULL is
// "not recorded", never a zero reading.
test("null LW, SW and DOI render as a dash marked not recorded, never 0", () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], identity);
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MeasurementTable rows={[{ ...measurement, lw: null, sw: null, doi: null }]} />
    </QueryClientProvider>,
  );
  assert.equal(html.match(/aria-label="Not recorded">—</g)?.length, 3);
  assert.equal(/<td[^>]*>0<\/td>/.test(html), false);
});

test("recorded LW, SW and DOI still render their exact values", () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], identity);
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MeasurementTable rows={[measurement]} />
    </QueryClientProvider>,
  );
  assert.equal(html.includes('aria-label="Not recorded">—'), false);
  for (const key of ["lw", "sw", "doi"] as const)
    if (measurement[key] != null) assert.ok(html.includes(String(measurement[key])));
});
