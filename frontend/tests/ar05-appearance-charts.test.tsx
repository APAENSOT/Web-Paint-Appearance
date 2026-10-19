import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { EvidenceChart } from "../src/features/analysis/charts";
import type { AssistantAnswer } from "../src/features/analysis/report-types";

type Evidence = AssistantAnswer["evidence"];

test("spectrum: colour line, dashed plant line, high bands labelled, table", () => {
  const rows = [
    ["du", 4, 4, 0, ""],
    ["Wa", 6, 5, 0.2, ""],
    ["Wd", 12, 7, 1.4, "high"],
  ];
  const e = {
    kind: "spectrum",
    columns: ["Band", "Colour", "Plant", "Gap (σ)", "High"],
    rows,
    series: rows.map((r) => ({ x: r[0], y: r[1] })),
    limits: null,
  } as unknown as Evidence;
  const html = renderToStaticMarkup(<EvidenceChart evidence={e} />);
  assert.ok(html.includes('data-line="Colour"') && html.includes('data-line="Plant"'));
  assert.ok(html.includes("stroke-dasharray"));
  assert.equal((html.match(/data-high=/g) ?? []).length, 1);
  assert.equal((html.match(/<tr/g) ?? []).length, 1 + rows.length);
});

test("scatter: a dot per point, fitted line from the card, table fallback", () => {
  const points = [
    { x: 40, y: 20, label: "1" },
    { x: 44, y: 18, label: "2" },
    { x: 48, y: 15, label: "3" },
  ];
  const base = {
    kind: "scatter",
    columns: ["Car", "Thickness", "Wa"],
    rows: points.map((p) => [p.label, p.x, p.y]),
    series: [],
    limits: null,
    points,
  };
  const card = [
    { label: "Slope", value: "-0.6" },
    { label: "Intercept", value: "44" },
  ];
  const html = renderToStaticMarkup(
    <EvidenceChart evidence={{ ...base, card } as unknown as Evidence} />,
  );
  assert.equal((html.match(/data-dot=/g) ?? []).length, 3);
  assert.ok(html.includes('data-line="Fit"') && html.includes("<table"));
  const bare = renderToStaticMarkup(
    <EvidenceChart evidence={{ ...base, card: [] } as unknown as Evidence} />,
  );
  assert.ok(!bare.includes('data-line="Fit"') && bare.includes("<table"));
  const none = renderToStaticMarkup(
    <EvidenceChart evidence={{ ...base, points: [] } as unknown as Evidence} />,
  );
  assert.ok(none.includes("<table"));
});

test("cf drivers bar: rho bars from the Band|ρ|n columns", () => {
  const e = {
    kind: "bar",
    columns: ["Band", "ρ", "n"],
    rows: [["Wb", -0.7, 12]],
    series: [],
    limits: null,
  } as unknown as Evidence;
  assert.ok(renderToStaticMarkup(<EvidenceChart evidence={e} />).includes('role="img"'));
});
