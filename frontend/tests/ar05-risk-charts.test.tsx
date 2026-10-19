import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { EvidenceChart } from "../src/features/analysis/charts";
import type { AssistantAnswer } from "../src/features/analysis/report-types";

type Evidence = AssistantAnswer["evidence"];

test("trend_monthly: a table row per month, absent mean shown as a dash", () => {
  const e = {
    kind: "trend_monthly",
    columns: ["Month", "Mean", "Status"],
    rows: [
      ["January 2026", 3.1, "Pass"],
      ["February 2026", "—", "—"],
      ["March 2026", 1.5, "Fail"],
    ],
    series: [],
    limits: { lo: 2, hi: null },
  } as unknown as Evidence;
  const html = renderToStaticMarkup(<EvidenceChart evidence={e} />);
  assert.equal((html.match(/<tr/g) ?? []).length, 4);
  assert.ok(html.includes("February 2026") && html.includes("—") && html.includes("Fail"));
});

test("grid: boxes by month with status words", () => {
  const cell = (code: string | null, word: string) => ({
    status_code: code,
    word,
    note: "",
    arrow: "",
  });
  const e = {
    kind: "grid",
    columns: ["Box", "January 2026", "February 2026"],
    rows: [["Ranger Blue", "Fail", "—"]],
    cells: [[cell("FAIL", "Fail"), cell(null, "—")]],
    series: [],
    limits: null,
  } as unknown as Evidence;
  const html = renderToStaticMarkup(<EvidenceChart evidence={e} />);
  assert.ok(
    html.includes("<table") && html.includes("Ranger Blue") && html.includes("February 2026"),
  );
  assert.equal((html.match(/<tr/g) ?? []).length, 2);
});

test("risk bar: chart for the expected-out column", () => {
  const e = {
    kind: "bar",
    columns: ["Box", "Expected out of 30", "Basis", "Now"],
    rows: [["Ranger Blue", 6, "trend", "Pass"]],
    series: [],
    limits: null,
  } as unknown as Evidence;
  const html = renderToStaticMarkup(<EvidenceChart evidence={e} />);
  assert.ok(html.includes('role="img"') && html.includes("Expected out of 30"));
});

test("limit_card: a definition row per layer and orientation, plus the table", () => {
  const e = {
    kind: "limit_card",
    columns: ["Layer", "Orientation", "Model", "Lo", "Hi", "Target", "Rule"],
    rows: [["Clear", "Vertical", "Ranger", "40", "—", "—", "colour rule"]],
    card: [{ label: "Clear V", value: "Lo 40 µm · no Hi" }],
    series: [],
  } as unknown as Evidence;
  const html = renderToStaticMarkup(<EvidenceChart evidence={e} />);
  assert.ok(html.includes("<dl") && html.includes("Clear V") && html.includes("Lo 40 µm · no Hi"));
  assert.ok(html.includes("<table") && html.includes("colour rule"));
});

test("stat: one big number with its label, table fallback", () => {
  const e = {
    kind: "stat",
    columns: ["Measure", "Value"],
    rows: [["Paired cars", 6]],
    card: [
      { label: "Paired cars", value: "6" },
      { label: "Needed for solid layer checks", value: "about 100" },
    ],
    series: [],
  } as unknown as Evidence;
  const html = renderToStaticMarkup(<EvidenceChart evidence={e} />);
  assert.ok(html.includes("text-4xl") && html.includes(">6<") && html.includes("about 100"));
  assert.ok(html.includes("<table"));
});

test("weekly strip: a missing week shows its flag word", () => {
  const e = {
    kind: "weekly_strip",
    columns: ["Week", "Readings", "Out", "Flag"],
    rows: [["Week 3", 0, 0, "missing"]],
    series: [],
  } as unknown as Evidence;
  const html = renderToStaticMarkup(<EvidenceChart evidence={e} />);
  assert.ok(html.includes("missing"));
});

test("weekly strip caption: the flag word itself under the bar, not a fixed word", () => {
  const e = {
    kind: "weekly_strip",
    columns: ["Week", "Readings", "Out", "Flag"],
    rows: [
      ["Week 2", 6, 6, "flagged"],
      ["Week 3", 0, 0, "missing"],
    ],
    series: [],
  } as unknown as Evidence;
  const html = renderToStaticMarkup(<EvidenceChart evidence={e} />);
  assert.equal([...html.matchAll(/<span class="font-semibold">flagged<\/span>/g)].length, 1);
  assert.equal([...html.matchAll(/<span class="font-semibold">missing<\/span>/g)].length, 1);
});
