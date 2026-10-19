import assert from "node:assert/strict";
import { test } from "node:test";
import { isValidElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AnswerCard } from "../src/features/analysis/AnswerCard";
import { CarBars } from "../src/features/analysis/charts/CarBars";
import { EvidenceTable } from "../src/features/analysis/charts/Table";
import { fillSlots } from "../src/features/analysis/slot-match";
import type { AssistantAnswer } from "../src/features/analysis/report-types";
import { LIVE, QUESTIONS } from "./ar05-fixtures";

type Evidence = AssistantAnswer["evidence"];
const q = (id: string) => QUESTIONS.questions.find((x) => x.id === id)!;

const evidence = (kind: string, rows: unknown[][], columns: string[]): Evidence =>
  ({
    kind,
    columns,
    rows,
    series: [],
    limits: null,
    cells: [],
    groups: [],
    points: [],
    card: [],
  }) as unknown as Evidence;

/** Every list of keyed siblings in an element tree (functions called through, as React would). */
function duplicateKeys(node: ReactNode): string[] {
  const dupes: string[] = [];
  const walk = (n: ReactNode): void => {
    if (Array.isArray(n)) {
      const keys = n.filter(isValidElement).map((e) => e.key);
      keys.forEach((k, i) => k !== null && keys.indexOf(k) !== i && dupes.push(String(k)));
      n.forEach(walk);
      return;
    }
    if (!isValidElement(n)) return;
    const props = n.props as { children?: ReactNode };
    if (typeof n.type === "function") return walk((n.type as (p: unknown) => ReactNode)(n.props));
    walk(props.children);
  };
  walk(node);
  return dupes;
}

const twin = evidence(
  "car_bars",
  [
    ["2005924", 3, 10],
    ["2005924", 1, 10],
    ["2005930", 0, 10],
  ],
  ["Car", "Points out", "Points measured"],
);

test("I8d: duplicate first cells keep every row and unique keys (table and car bars)", () => {
  const table = <EvidenceTable evidence={twin} caption="c" />;
  assert.deepEqual(duplicateKeys(table), []);
  assert.equal((renderToStaticMarkup(table).match(/<tr/g) ?? []).length, 1 + 3);
  const bars = <CarBars evidence={twin} />;
  assert.deepEqual(duplicateKeys(bars), []);
  assert.equal((renderToStaticMarkup(bars).match(/data-car=/g) ?? []).length, 3);
});

const base: AssistantAnswer = {
  topic: "worst_cars",
  month: "2026-09",
  previous_month: "2026-08",
  domain: "both",
  models: [],
  colors: [],
  status: "answer",
  decision: { status_code: null, headline: "Car 2005924: 4 points out — open its history" },
  proof: null,
  next_step: null,
  risk: null,
  confidence: "solid",
  evidence: twin,
  followups: [],
  method: { rule: "r", n: 3, caveats: [] },
} as unknown as AssistantAnswer;

const card = (a: AssistantAnswer) =>
  renderToStaticMarkup(
    <AnswerCard
      answer={a}
      stale={null}
      collapsed={false}
      added={false}
      onExpand={() => {}}
      onFollowup={() => {}}
      onSlot={() => {}}
      onAddToSlides={() => {}}
    />,
  );

test("minor: a chart that prints its own table is not followed by the generic one", () => {
  const out = card(base);
  assert.equal((out.match(/data-evidence-row/g) ?? []).length, 0);
  assert.equal((out.match(/<table/g) ?? []).length, 1);
  // a plain bar still gets the generic table
  const bar = { ...base, evidence: evidence("bar", [["A", 1]], ["X", "Y"]) };
  assert.equal((card(bar).match(/data-evidence-row/g) ?? []).length, 1);
});

test("minor: a colour inside a longer colour match is not a second colour", () => {
  const live = { ...LIVE, colours: ["Oxford White", "White", "Blue"] };
  assert.deepEqual(fillSlots("compare Oxford White and Blue", q("compare_colours"), live), {
    a: "Oxford White",
    b: "Blue",
  });
  assert.deepEqual(fillSlots("compare White and Blue", q("compare_colours"), live), {
    a: "White",
    b: "Blue",
  });
});

test("I4: the layer_vs_band band slot takes du..we and CF only", () => {
  const live = { ...LIVE, metrics: [...LIVE.metrics, "lw", "wa", "cf"] };
  assert.deepEqual(fillSlots("thickness of clear vs lw", q("layer_vs_band"), live), {
    layer: "CLEAR",
  });
  assert.deepEqual(fillSlots("thickness of clear vs wa", q("layer_vs_band"), live), {
    layer: "CLEAR",
    metric: "wa",
  });
});
