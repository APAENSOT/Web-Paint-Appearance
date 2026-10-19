import assert from "node:assert/strict";
import { test } from "node:test";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { assistantAnswerOptions, assistantQuestionsOptions } from "../src/api/queries";
import { AssistantPanel } from "../src/features/analysis/AssistantPanel";
import { AnswerCard, SlotChips } from "../src/features/analysis/AnswerCard";
import { Heatmap } from "../src/features/analysis/charts/Heatmap";
import { BoxplotGroup } from "../src/features/analysis/charts/BoxplotGroup";
import { BoxplotPair } from "../src/features/analysis/charts/BoxplotPair";
import { MirroredBar } from "../src/features/analysis/charts/MirroredBar";
import { PointBars } from "../src/features/analysis/charts/PointBars";
import { WeeklyStrip } from "../src/features/analysis/charts/WeeklyStrip";
import { QuestionMenu } from "../src/features/analysis/QuestionMenu";
import { matchQuestion, slotAsk, type Ask } from "../src/features/analysis/assistant-intents";
import { fillSlots } from "../src/features/analysis/slot-match";
import type { AssistantAnswer } from "../src/features/analysis/report-types";
import { LIVE, QUESTIONS } from "./ar05-fixtures";

const q = (id: string) => QUESTIONS.questions.find((x) => x.id === id)!;

test("matchQuestion: AR05 questions, longest keyword wins, details filled from the text", () => {
  const cases: [string, { id: string; slots: Record<string, string> } | null][] = [
    [
      "compare Raptor and Ranger on Clear",
      {
        id: "compare_models",
        slots: { a: "P703 DBL RAPTOR", b: "P703 DBL RANGER", metric: "CLEAR" },
      },
    ],
    [
      "เทียบ Raptor กับ Ranger สี",
      { id: "compare_models", slots: { a: "P703 DBL RAPTOR", b: "P703 DBL RANGER" } },
    ],
    ["colour report for September", { id: "colour_report", slots: { month: "2026-09" } }],
    ["why is it failing", { id: "why_failing", slots: {} }],
    ["is the data complete", { id: "data_complete", slots: {} }],
    [
      "compare Race Red with Arctic White on wc",
      {
        id: "compare_colours",
        slots: { a: "Race Red", b: "Arctic White", metric: "wc" },
      },
    ],
    [
      "เทียบ สิงหาคม กับ กันยายน",
      { id: "compare_months", slots: { month: "2026-08", month2: "2026-09" } },
    ],
    ["what changed", { id: "changes", slots: {} }],
    ["model report raptor", { id: "model_report", slots: { model: "P703 DBL RAPTOR" } }],
    ["west door", null],
    // Fix round 1: ordinary words never fill a detail ("we", "b", "may")
    [
      "how do we compare Raptor and Ranger",
      { id: "compare_models", slots: { a: "P703 DBL RAPTOR", b: "P703 DBL RANGER" } },
    ],
    ["are we ok on left vs right", { id: "compare_sides", slots: {} }],
    ["may I see the colour report", { id: "colour_report", slots: {} }],
    [
      "compare Raptor and Ranger on band We",
      { id: "compare_models", slots: { a: "P703 DBL RAPTOR", b: "P703 DBL RANGER", metric: "we" } },
    ],
    [
      "compare Raptor and Ranger B value",
      { id: "compare_models", slots: { a: "P703 DBL RAPTOR", b: "P703 DBL RANGER", metric: "b" } },
    ],
    // A generic keyword loses to another question's own keyword
    ["compare left and right", { id: "compare_sides", slots: {} }],
    ["เทียบซ้ายขวา", { id: "compare_sides", slots: {} }],
    ["compare by family", { id: "compare_families", slots: {} }],
  ];
  for (const [text, want] of cases)
    assert.deepEqual(matchQuestion(text, QUESTIONS, LIVE), want, text);
});

test("fillSlots: May only with a capital or a year", () => {
  const live = { ...LIVE, months: ["2026-05", "2025-05"] };
  const report = q("colour_report");
  assert.deepEqual(fillSlots("colour report for May", report, live), { month: "2026-05" });
  assert.deepEqual(fillSlots("colour report may 2026", report, live), { month: "2026-05" });
  assert.deepEqual(fillSlots("may I see the colour report", report, live), {});
});

test("slotAsk: a chip keeps the card's own query and merges the slot (target goes to target)", () => {
  const ask: Ask = {
    id: 3,
    topic: "compare_models",
    target: "film|CLEAR|R|Red|H",
    query: { domain: "film", month: "2026-08" },
    slots: { a: "A", b: "B" },
  };
  assert.deepEqual(slotAsk(ask, "metric", "wc"), {
    topic: "compare_models",
    target: "film|CLEAR|R|Red|H",
    query: ask.query,
    slots: { a: "A", b: "B", metric: "wc" },
  });
  assert.deepEqual(slotAsk({ ...ask, slots: undefined }, "target", "film|BASE|R|Red|V"), {
    topic: "compare_models",
    target: "film|BASE|R|Red|V",
    query: ask.query,
    slots: {},
  });
});

test("fillSlots: layer words (EN + TH), sides and months in text order", () => {
  assert.deepEqual(fillSlots("thickness of เคลียร์ vs wa", q("layer_vs_band"), LIVE), {
    layer: "CLEAR",
    metric: "wa",
  });
  assert.deepEqual(fillSlots("E-coat and Wd", q("layer_vs_band"), LIVE), {
    layer: "ECOAT",
    metric: "wd",
  });
  // final I4: DOI is not a band a layer links to
  assert.deepEqual(fillSlots("E-coat and DOI", q("layer_vs_band"), LIVE), { layer: "ECOAT" });
  assert.deepEqual(fillSlots("left vs right on Base", q("compare_sides"), LIVE), {
    metric: "BASE",
  });
  assert.deepEqual(fillSlots("nothing here", q("compare_models"), LIVE), {});
});

test("QuestionMenu: six group headings and all 32 questions", () => {
  const out = renderToStaticMarkup(
    <QuestionMenu questions={QUESTIONS.questions} onPick={() => {}} />,
  );
  for (const h of [
    "This month",
    "Compare",
    "Find the problem",
    "Trend and risk",
    "Appearance and layers",
    "Data and standards",
  ])
    assert.ok(out.includes(`>${h}</h4>`), h);
  assert.equal([...out.matchAll(/data-question="/g)].length, 32);
  assert.ok(out.includes("What can I ask?"));
});

const needs: AssistantAnswer = {
  topic: "compare_models",
  month: "2026-09",
  previous_month: "2026-08",
  domain: "both",
  models: [],
  colors: [],
  status: "needs_slot",
  decision: { status_code: null, headline: "Which layer or Wave Scan metric?" },
  proof: "",
  explanation: "",
  next_step: null,
  risk: null,
  confidence: "",
  evidence: {
    kind: null,
    columns: [],
    rows: [],
    series: [],
    limits: null,
    cells: [],
    groups: [],
    points: [],
    card: [],
  },
  followups: [],
  method: { rule: "Asks for a missing detail", n: 0, caveats: [] },
  slot: {
    name: "metric",
    prompt: "Which layer or Wave Scan metric?",
    choices: [
      { value: "CLEAR", label: "Clear" },
      { value: "wc", label: "Wc" },
    ],
  },
};

/** Every element in a tree of plain (hook-free) elements, depth first. */
const walk = (n: ReactNode): ReactElement<{ onClick?: () => void; children?: ReactNode }>[] =>
  Array.isArray(n)
    ? n.flatMap(walk)
    : isValidElement<{ children?: ReactNode }>(n)
      ? [
          n as ReactElement<{ onClick?: () => void; children?: ReactNode }>,
          ...walk(n.props.children),
        ]
      : [];

test("a needs_slot answer shows its prompt and one chip per choice; a chip asks with that slot", () => {
  const out = renderToStaticMarkup(
    <AnswerCard
      answer={needs}
      stale={null}
      collapsed={false}
      added={false}
      onExpand={() => {}}
      onFollowup={() => {}}
      onSlot={() => {}}
      onAddToSlides={() => {}}
    />,
  );
  assert.ok(out.includes("Which layer or Wave Scan metric?"));
  assert.equal([...out.matchAll(/data-choice="/g)].length, 2);
  assert.ok(!out.includes("Slides"));

  const picked: [string, string][] = [];
  const tree = SlotChips({ slot: needs.slot!, onSlot: (n, v) => picked.push([n, v]) });
  const buttons = walk(tree).filter((e) => e.type === "button");
  assert.equal(buttons.length, 2);
  buttons[1].props.onClick!();
  assert.deepEqual(picked, [["metric", "wc"]]);
});

test("panel: typed details go with the first ask; the user bubble and the menu show", () => {
  const client = new QueryClient();
  const query = { domain: "both" as const };
  const slots = { a: "P703 DBL RAPTOR", b: "P703 DBL RANGER" };
  const asks: Ask[] = [
    {
      id: 1,
      topic: "compare_models",
      target: null,
      query,
      slots,
      said: "compare Raptor and Ranger",
    },
  ];
  client.setQueryData(assistantQuestionsOptions("P703").queryKey, QUESTIONS);
  client.setQueryData(
    assistantAnswerOptions("P703", { ...query, topic: "compare_models", target: null, ...slots })
      .queryKey,
    needs,
  );
  const out = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AssistantPanel
        code="P703"
        query={query}
        live={LIVE}
        asks={asks}
        onAsks={() => {}}
        onAddToSlides={() => {}}
      />
    </QueryClientProvider>,
  );
  assert.ok(out.includes("compare Raptor and Ranger"));
  assert.equal([...out.matchAll(/data-choice="/g)].length, 2);
  assert.equal([...out.matchAll(/data-question="/g)].length, 32);
  assert.equal(client.isFetching(), 0);
});

test("Heatmap: every cell shows its status word, note and arrow, with row and column headers", () => {
  const cell = (status_code: string | null, word: string, note = "", arrow = "") => ({
    status_code,
    word,
    note,
    arrow,
  });
  const html = renderToStaticMarkup(
    <Heatmap
      evidence={
        {
          kind: "heatmap",
          columns: ["Colour", "Primer", "Clear"],
          rows: [
            ["Blue", "Pass", "Fail · RANGER V"],
            ["Red", "—", "For Improvement"],
          ],
          series: [],
          limits: null,
          groups: [],
          points: [],
          card: [],
          cells: [
            [cell("PASS", "Pass"), cell("FAIL", "Fail", "RANGER V", "↓")],
            [cell(null, "—"), cell("WARNING", "For Improvement")],
          ],
        } as never
      }
    />,
  );
  for (const t of ["Blue", "Primer", "Clear", "Pass", "Fail", "RANGER V", "↓"]) {
    assert.ok(html.includes(t), t);
  }
  assert.match(html, /<th scope="row"/);
  assert.match(html, /data-tone="FAIL"/);
  assert.match(html, /data-tone="NONE"[^>]*>[^<]*<span[^>]*><\/span>—/);
  assert.ok(html.includes("whitespace-normal"), "chip word may wrap");
});

test("WeeklyStrip: a bar per week, the flagged week says flagged, and the table repeats the numbers", () => {
  const html = renderToStaticMarkup(
    <WeeklyStrip
      evidence={
        {
          kind: "weekly_strip",
          columns: ["Week", "Readings", "Out", "Flag"],
          rows: [
            ["Week 1", 30, 0, ""],
            ["Week 2", 6, 6, "flagged"],
            ["Day not recorded", 5, 5, ""],
          ],
          series: [],
        } as never
      }
    />,
  );
  assert.equal([...html.matchAll(/data-week="/g)].length, 3);
  assert.equal([...html.matchAll(/<span class="font-semibold">flagged<\/span>/g)].length, 1);
  assert.ok(html.includes("Day not recorded") && html.includes("<table"));
});

test("BoxplotPair: two boxes, n under each, dashed limit lines with values, and a table", () => {
  const g = (label: string, n: number, m: number) => ({
    label,
    n,
    q1: m - 1,
    median: m,
    q3: m + 1,
    low: m - 2,
    high: m + 2,
    mean: m,
  });
  const html = renderToStaticMarkup(
    <BoxplotPair
      evidence={
        {
          kind: "boxplot_pair",
          columns: ["Group", "n", "Q1", "Median", "Q3", "Mean"],
          rows: [
            ["RAPTOR", 12, 15, 16, 17, 16],
            ["RANGER", 11, 19, 20, 21, 20],
          ],
          series: [],
          groups: [g("RAPTOR", 12, 16), g("RANGER", 11, 20)],
          limits: { lo: 14, hi: null },
        } as never
      }
    />,
  );
  assert.equal([...html.matchAll(/data-box="/g)].length, 2);
  for (const t of ["RAPTOR", "RANGER", "n 12", "n 11", "Lower limit 14"])
    assert.ok(html.includes(t), t);
  assert.equal([...html.matchAll(/stroke-dasharray/g)].length, 1);
  assert.ok(html.includes("<table"));
});

test("MirroredBar and BoxplotGroup render their bars/boxes with the table", () => {
  const mb = renderToStaticMarkup(
    <MirroredBar
      evidence={
        {
          kind: "mirrored_bar",
          columns: ["Panel", "Left", "Right", "Δ", "Verdict"],
          rows: [
            ["DOOR", 18.2, 21, "-2.8", "Real difference"],
            ["FENDER", 20, 20.1, "-0.1", "No real difference"],
          ],
          series: [],
          groups: [],
          limits: null,
        } as never
      }
    />,
  );
  assert.equal([...mb.matchAll(/data-panel="/g)].length, 2);
  assert.ok(mb.includes("Δ -2.8 · Real difference") && mb.includes("<table"));
  const g = (label: string) => ({
    label,
    n: 11,
    q1: 1,
    median: 2,
    q3: 3,
    low: 0,
    high: 4,
    mean: 2,
  });
  const bg = renderToStaticMarkup(
    <BoxplotGroup
      evidence={
        {
          kind: "boxplot_group",
          columns: ["Family", "n", "Q1", "Median", "Q3", "Mean"],
          rows: [["Dark", 11, 1, 2, 3, 2]],
          series: [],
          groups: [g("Dark"), g("Light"), g("No family")],
          limits: null,
        } as never
      }
    />,
  );
  assert.equal([...bg.matchAll(/data-box="/g)].length, 3);
  assert.equal([...bg.matchAll(/stroke-dasharray/g)].length, 0);
});

test("PointBars: A and B bars per point, out as words, a gap draws one bar, and a table", () => {
  const html = renderToStaticMarkup(
    <PointBars
      evidence={
        {
          kind: "point_bars",
          columns: ["Layer", "Point", "Car A", "Car B", "Out"],
          rows: [
            ["Clear", "094RROOF", "20.0", "10.0", "B out"],
            ["Clear", "050HOOD", "22.0", "—", ""],
          ],
          series: [],
          groups: [],
          limits: null,
        } as never
      }
    />,
  );
  assert.equal([...html.matchAll(/data-point="/g)].length, 2);
  assert.equal([...html.matchAll(/class="h-2 /g)].length, 3);
  assert.ok(html.includes("B out") && html.includes("<table") && html.includes("Car A"));
});
