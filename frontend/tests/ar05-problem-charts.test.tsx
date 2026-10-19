import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { EvidenceChart } from "../src/features/analysis/charts";
import type { AssistantAnswer } from "../src/features/analysis/report-types";

type Evidence = AssistantAnswer["evidence"];
const ev = (kind: string, columns: string[], rows: Evidence["rows"]) =>
  ({ kind, columns, rows, series: [], limits: null }) as unknown as Evidence;

test("breakdown: one panel per dimension, top 5 bars, full table", () => {
  const rows = [
    ...[1, 2, 3, 4, 5, 6].map((i) => ["Point", `P${i}`, 10 - i, 20]),
    ["Side", "right", 8, 40],
  ];
  const html = renderToStaticMarkup(
    <EvidenceChart evidence={ev("breakdown", ["By", "Where", "Out", "Readings"], rows)} />,
  );
  assert.equal((html.match(/data-dimension=/g) ?? []).length, 2);
  assert.equal((html.match(/<tr/g) ?? []).length, 1 + rows.length);
  assert.ok(html.includes("Readings") && html.includes("right"));
});

test("car bars: a bar per car and a table", () => {
  const rows = [
    ["2000004", 5, 5],
    ["2000005", 1, 5],
  ];
  const html = renderToStaticMarkup(
    <EvidenceChart evidence={ev("car_bars", ["Car", "Points out", "Points measured"], rows)} />,
  );
  assert.equal((html.match(/data-car=/g) ?? []).length, 2);
  assert.ok(html.includes("5 of 5") && html.includes("<table"));
});

test("distribution: a bar per bin, limit lines, mean marker and a table", () => {
  const rows = Array.from({ length: 10 }, (_, i) => [`${20 + i}.0–${21 + i}.0`, i + 1]);
  const e = {
    ...ev("distribution", ["Bin", "Readings"], rows),
    limits: { lo: 22, hi: null },
    card: [
      { label: "Mean", value: "25.0 µm" },
      { label: "σ", value: "2.0 µm" },
    ],
  } as unknown as Evidence;
  const html = renderToStaticMarkup(<EvidenceChart evidence={e} />);
  assert.equal((html.match(/data-bin=/g) ?? []).length, 10);
  assert.ok(html.includes('data-line="Lower limit"') && html.includes('data-line="Mean"'));
  assert.ok(!html.includes('data-line="Upper limit"') && html.includes("<table"));
});
