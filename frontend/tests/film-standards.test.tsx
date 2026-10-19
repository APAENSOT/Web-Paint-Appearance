import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  resolveOrientation,
  validateTriple,
  draftFrom,
  sameValues,
  displayValue,
  limitFields,
} from "../src/features/filmthickness/film-standards";
import { RuleSources, RuleValues } from "../src/features/filmthickness/FilmRulePresentation";
import { parsePlantSearch } from "../src/features/measurements/history-search";
import { StandardChildrenNav } from "../src/features/measurements/StandardChildrenNav";
import { createApiClient, ApiError } from "../src/api/client";
import { filmStandardsFixture, rule } from "./film-standards-fixtures";

test("independent own/plant precedence, absent rules, zero and null display", () => {
  const [wide, own] = filmStandardsFixture.rules;
  assert.deepEqual(resolveOrientation(own, wide, "h", "Blue"), { rule: own.h, inherited: false });
  assert.deepEqual(resolveOrientation(own, wide, "v", "Blue"), { rule: wide.v, inherited: true });
  assert.deepEqual(resolveOrientation(undefined, undefined, "h", "Amber"), {
    rule: null,
    inherited: false,
  });
  assert.equal(displayValue(0), "0 µm");
  assert.equal(displayValue(null), "Not set");
  assert.equal(displayValue(12.5), "12.5 µm");
  assert.deepEqual(draftFrom(null), { lo: "", hi: "", target: "" });
  assert.equal(sameValues(null, null), false);
  assert.equal(sameValues(rule(1), rule(1, null, null, "Different source")), true);
});
test("bounds: Minimum/Maximum layers and Clear's No point below + Minimum requirement (no Maximum)", () => {
  for (const draft of [
    { lo: "0", hi: "", target: "" },
    { lo: "12.25", hi: "", target: "46" },
    { lo: "30", hi: "", target: "30" },
  ])
    assert.deepEqual(validateTriple(draft, "CLEAR").errors, {});
  for (const value of ["-1", "501", "1e2", "1.234", ".2", "Infinity"])
    assert.ok(validateTriple({ lo: value, hi: "", target: "" }, "CLEAR").errors.lo);
  // Clear has no Maximum (T67 D-67-07): a stray hi is never sent and No point below is required.
  assert.deepEqual(validateTriple({ lo: "30", hi: "35", target: "35" }, "CLEAR").values, {
    lo: 30,
    hi: null,
    target: 35,
  });
  assert.ok(validateTriple({ lo: "", hi: "500", target: "" }, "CLEAR").errors.lo);
  assert.ok(validateTriple({ lo: "", hi: "", target: "46" }, "CLEAR").errors.lo);
  assert.ok(validateTriple({ lo: "20", hi: "", target: "19" }, "CLEAR").errors.target);
  assert.ok(validateTriple({ lo: "20", hi: "10", target: "" }, "BASE").errors.hi);
  assert.deepEqual(validateTriple({ lo: "", hi: "30", target: "99" }, "PRIMER").values, {
    lo: null,
    hi: 30,
    target: null,
  });
  assert.deepEqual(
    limitFields("CLEAR").map(([, label]) => label),
    ["No point below", "Minimum requirement"],
  );
  for (const layer of ["ECOAT", "PRIMER", "BASE"] as const)
    assert.deepEqual(
      limitFields(layer).map(([, label]) => label),
      ["Minimum", "Maximum"],
    );
});
test("source provenance, Clear-only Minimum requirement, semantic Bangkok time", () => {
  const html = renderToStaticMarkup(
    <RuleSources
      h={{ rule: rule(0), inherited: true }}
      v={{ rule: rule(18, null, null, "Separate vertical"), inherited: false }}
    />,
  );
  assert.match(html, /Plant-wide source \(Inherited\)/);
  assert.match(html, /Not provided/);
  assert.match(html, /Separate vertical/);
  assert.match(html, /Asia\/Bangkok/);
  assert.match(html, /dateTime="2026-10-06T03:00:00Z"/i);
  for (const layer of ["ECOAT", "PRIMER", "BASE", "CLEAR"] as const) {
    const values = renderToStaticMarkup(
      <RuleValues
        layer={layer}
        orientation="Horizontal"
        resolved={{ rule: rule(36, null, 46), inherited: false }}
      />,
    );
    assert.equal(values.includes("Minimum requirement"), layer === "CLEAR");
    assert.equal(values.includes("Maximum"), layer !== "CLEAR");
    assert.equal(values.includes("Min average"), false);
    if (layer !== "CLEAR") assert.match(values, /Not set/); // Clear shows no Maximum line at all.
  }
});
// T100-FIX2 CHANGE (D-100-9): the entry is no longer Admin-only -- it is drawn
// for anyone who may upload, read from identity in the nav itself. The
// `canEditFilm` prop keeps its old meaning and still decides on its own, which
// is what the rows with no principal assert; the Engineer and Admin rows are
// the widening, and a Viewer stays hidden.
test("film navigation parsing and the Film entry's role rule preserve other views", () => {
  assert.equal(parsePlantSearch({ standardView: "film" }).standardView, "film");
  assert.equal(parsePlantSearch({ standardView: "invalid" }).standardView, undefined);
  const cases: [boolean, string[] | null, boolean][] = [
    [true, null, true],
    [false, null, false],
    [false, ["engineer"], true],
    [false, ["admin"], true],
    [false, ["viewer"], false],
    [true, ["viewer"], true],
  ];
  for (const [canEditFilm, roles, shown] of cases) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    if (roles)
      client.setQueryData(["identity"], {
        principal: { user_id: "u", email: "e@f.g", roles, plant_scope: null },
      });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <StandardChildrenNav view="film" canEditFilm={canEditFilm} onSelect={() => {}} />
      </QueryClientProvider>,
    );
    assert.equal(html.includes("Film Thickness"), shown, `${canEditFilm} ${roles}`);
    assert.match(html, /Color Family/);
    assert.doesNotMatch(html, />Model</);
    assert.doesNotMatch(html, />Point Check</);
  }
});
test("typed T62 transport omits credentials and preserves error envelope", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetcher: typeof fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(
      JSON.stringify(
        init?.method === "POST"
          ? {
              plant_code: "FTM",
              layer_code: "ECOAT",
              color_name: null,
              audit_id: 1,
              created_at: "2026-10-06T03:00:00Z",
            }
          : filmStandardsFixture,
      ),
      { status: init?.method === "POST" ? 201 : 200 },
    );
  };
  const api = createApiClient("http://localhost:8012", fetcher);
  await api.filmStandards("FTM");
  const body = {
    plant_code: "FTM",
    layer_code: "ECOAT" as const,
    color_name: null,
    h: { lo: 0, hi: null, target: null },
    v: { lo: null, hi: 500, target: null },
    source_note: "Fixture",
  };
  await api.publishFilmStandard(body);
  assert.equal(calls[0].url, "http://localhost:8012/api/v1/plants/FTM/filmthickness/standards");
  assert.equal(calls[1].url, "http://localhost:8012/api/v1/filmthickness/standards");
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)), body);
  assert.ok(calls.every((c) => c.init?.credentials === "omit"));
  for (const status of [403, 404, 422]) {
    const client = createApiClient(
      "http://localhost:8012",
      async () =>
        new Response(
          JSON.stringify({
            statusCode: status,
            error: "refused",
            message: "Colour no longer offered",
            correlationId: "film-test",
          }),
          { status },
        ),
    );
    await assert.rejects(
      client.publishFilmStandard(body),
      (e: unknown) =>
        e instanceof ApiError &&
        e.body?.correlationId === "film-test" &&
        e.message === "Colour no longer offered",
    );
  }
});
