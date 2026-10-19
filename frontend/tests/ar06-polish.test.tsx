import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { assistantAnswerOptions } from "../src/api/queries";
import { AnswerCard } from "../src/features/analysis/AnswerCard";
import { AssistantPanel } from "../src/features/analysis/AssistantPanel";
import {
  filterLabel,
  newAsk,
  sameFilters,
  slotAnswer,
  type Ask,
} from "../src/features/analysis/assistant-intents";
import { answerSlide } from "../src/features/analysis/report-slides";
import type { AssistantAnswer } from "../src/features/analysis/report-types";

type Evidence = AssistantAnswer["evidence"];
const ev = (kind: string, columns: string[], rows: unknown[][], points: unknown[] = []) =>
  ({
    kind,
    columns,
    rows,
    series: [],
    limits: null,
    cells: [],
    groups: [],
    points,
    card: [],
  }) as unknown as Evidence;

const EXPLAIN =
  "Raptor Red Clear is the box to fix: 9 of 34 readings were out, so the process can't keep it inside the standard.";
const answer: AssistantAnswer = {
  topic: "summary",
  month: "2026-09",
  previous_month: "2026-08",
  domain: "both",
  models: [],
  colors: [],
  status: "answer",
  decision: { status_code: "FAIL", headline: "Fix first: Raptor Red · Clear · Horizontal" },
  proof: "9 of 34 readings out",
  explanation: EXPLAIN,
  next_step: "Check Clear film build at R-12 and R-14",
  risk: { expected_out: 5, of_next: 30, basis: "current mean and spread" },
  confidence: "solid",
  evidence: ev(
    "bar",
    ["Box", "Status", "Out", "n"],
    Array.from({ length: 3 }, (_, i) => [`Box ${i + 1}`, "Fail", 9 - i, 34]),
  ),
  followups: [{ label: "Which colours?", topic: "colours", target: null }],
  method: { rule: "Rank boxes by severity", n: 12, caveats: ["One week missing"] },
};

const noop = () => {};
const card = (a: AssistantAnswer) =>
  renderToStaticMarkup(
    <AnswerCard
      answer={a}
      stale={null}
      collapsed={false}
      added={false}
      onExpand={noop}
      onFollowup={noop}
      onSlot={noop}
      onAddToSlides={noop}
    />,
  );
const fold = (html: string) => html.slice(html.indexOf("<details"));
const open = (html: string) => html.slice(0, html.indexOf("<details"));

test("layout: headline, explanation, open graph, next step, chips, one fold, actions", () => {
  const out = card(answer);
  const at = (s: string) => {
    const i = out.indexOf(s);
    assert.ok(i >= 0, s);
    return i;
  };
  const order = [
    at("data-headline"),
    at("data-explanation"),
    at('role="img"'),
    at("Next step:"),
    at("If not fixed"),
    at("Solid"),
    at("<details"),
    at("Numbers and method"),
    at("Which colours?"),
    at("Slides"),
  ];
  assert.deepEqual(
    order,
    [...order].sort((a, b) => a - b),
  );
  assert.equal((out.match(/<details/g) ?? []).length, 1, "one fold only");
  assert.match(out, /<summary[^>]*>(<svg.*?<\/svg>)?Numbers and method<\/summary>/);
  // body text, readable measure
  const para = out.match(/<p data-explanation="" class="([^"]*)"/)?.[1] ?? "";
  assert.ok(para.includes("text-[15px]") && para.includes("max-w-[70ch]"), para);
  assert.ok(out.includes(EXPLAIN.replace("'", "&#x27;")));
  // the graph is open, the numbers are in the fold
  assert.ok(open(out).includes('role="img"'));
  const f = fold(out);
  for (const s of ["9 of 34 readings out", "data-evidence-row", "Rank boxes by severity"])
    assert.ok(f.includes(s), s);
  assert.ok(open(out).includes("One week missing"), "limitations remain visible");
  assert.ok(f.includes("Looked at 12."));
  assert.ok(
    open(out).includes("9 of 34 readings out"),
    "supporting facts visible beside the graph",
  );
});

test("an empty explanation draws no paragraph", () => {
  assert.ok(!card({ ...answer, explanation: "" }).includes("data-explanation"));
});

test("a chart that renders nothing: the table is shown directly, no empty frame", () => {
  const shiftCols = ["Box", "Before", "Now", "Change", "Verdict"];
  const shiftRows = [["M3 Red · Primer · H", "—", "Pass", "—", "New"]];
  const cases: [string, Evidence][] = [
    ["shift without points", ev("shift", shiftCols, shiftRows, [])],
    ["bar lookup miss", ev("bar", ["A", "B", "Out", "n"], [["x", "Fail", 3, 9]])],
    ["bar with no numbers", ev("bar", ["Box", "Status", "Out", "n"], [["x", "Fail", null, 9]])],
  ];
  for (const [name, evidence] of cases) {
    const out = card({ ...answer, evidence });
    assert.ok(!out.includes('role="img"'), name);
    assert.ok(open(out).includes("data-evidence-row"), `${name}: table open`);
    assert.ok(!fold(out).includes("data-evidence-row"), `${name}: not only in the fold`);
  }
  // a shift that does plot keeps the graph open and the table folded
  const plotted = ev(
    "shift",
    shiftCols,
    [["M1", "Pass", "Fail", "+10.0 µm", "Real shift"]],
    [{ x: 20, y: 30, label: "M1" }],
  );
  const out = card({ ...answer, evidence: plotted });
  assert.ok(open(out).includes("data-shift=") && !open(out).includes("data-evidence-row"));
  assert.ok(fold(out).includes("data-evidence-row"));
});

test("a chart that prints its own table adds none to the fold", () => {
  const rows = [["2005924", 4, 10]];
  const out = card({
    ...answer,
    evidence: ev("car_bars", ["Car", "Points out", "Points measured"], rows),
  });
  assert.ok(open(out).includes("data-car="));
  assert.ok(!out.includes("data-evidence-row"));
});

test("needs_slot: the prompt and its chips only", () => {
  const out = card({
    ...answer,
    status: "needs_slot",
    slot: {
      name: "model",
      prompt: "Which model?",
      choices: [{ value: "R", label: "Raptor" }],
    },
  } as AssistantAnswer);
  assert.ok(out.includes("Which model?") && out.includes('data-choice="R"'));
  for (const s of ["data-explanation", "<details", "Next step:", 'role="img"', "Slides"])
    assert.ok(!out.includes(s), s);
});

test("answerSlide: the explanation is the first summary line when present", () => {
  const first = (a: AssistantAnswer) => {
    const s = answerSlide(a);
    return s.kind === "notes" ? s.summary[0] : null;
  };
  assert.equal(first(answer), EXPLAIN);
  assert.equal(first({ ...answer, explanation: "" }), "9 of 34 readings out");
});

// ------------------------------------------------------------------ Task 5: chat history
const LIVE6 = {
  models: ["P703 DBL RAPTOR"],
  colours: ["Red"],
  months: ["2026-10", "2026-09"],
  layers: ["CLEAR"],
  metrics: ["CLEAR"],
};
const SEP = { domain: "both" as const, month: "2026-09" };
const OCT = { domain: "film" as const, month: "2026-10", models: ["P703 DBL RAPTOR"] };
const needs = {
  ...answer,
  topic: "colour_report",
  status: "needs_slot",
  explanation: "",
  decision: { status_code: null, headline: "Which colour?" },
  slot: { name: "colour", prompt: "Which colour?", choices: [{ value: "Red", label: "Red" }] },
} as AssistantAnswer;

test("newAsk: turns go oldest to newest; a month detail goes in the turn's query", () => {
  const one = newAsk([], "summary", null, SEP, {}, "Month summary");
  const two = newAsk(one, "colour_report", null, SEP, { month: "2026-10", colour: "Red" }, "x");
  assert.deepEqual(
    two.map((a) => [a.id, a.topic, a.query.month, a.slots]),
    [
      [1, "summary", "2026-09", {}],
      [2, "colour_report", "2026-10", { colour: "Red" }],
    ],
  );
});

test("slotAnswer: the chip answers its own turn (same id and place, query updated), no orphan", () => {
  const asks = newAsk(
    newAsk([], "colour_report", null, SEP, {}, "Colour report"),
    "summary",
    null,
    SEP,
  );
  const next = slotAnswer(asks, 1, "colour", "Red", "Red");
  assert.equal(next.length, 2);
  assert.deepEqual(
    next.map((a) => [a.id, a.topic, a.slots, a.said]),
    [
      [1, "colour_report", { colour: "Red" }, "Colour report · Red"],
      [2, "summary", {}, undefined],
    ],
  );
  // a month chip moves into the turn's query
  assert.equal(slotAnswer(asks, 1, "month", "2026-10", "October 2026")[0].query.month, "2026-10");
});

test("sameFilters / filterLabel: unset month is the newest month, lists sorted", () => {
  assert.ok(sameFilters({ domain: "both" }, SEP, "2026-09"));
  assert.ok(sameFilters({ models: ["B", "A"] }, { models: ["A", "B"], domain: "both" }, null));
  assert.ok(!sameFilters(SEP, OCT, "2026-10"));
  assert.equal(filterLabel(OCT, null), "October 2026 · Film · P703 DBL RAPTOR");
  assert.equal(filterLabel({}, "2026-09"), "September 2026 · Wave Scan and Film");
});

const panel = (asks: Ask[], client: QueryClient, query = OCT) =>
  renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AssistantPanel
        code="P703"
        query={query}
        live={LIVE6}
        asks={asks}
        onAsks={noop}
        onAddToSlides={noop}
      />
    </QueryClientProvider>,
  );
const seed = (client: QueryClient, a: Ask, data: AssistantAnswer) =>
  client.setQueryData(
    assistantAnswerOptions("P703", { ...a.query, topic: a.topic!, target: a.target, ...a.slots })
      .queryKey,
    data,
  );

test("panel: all answers readable, oldest first, one divider, no refetch", () => {
  const client = new QueryClient();
  const asks: Ask[] = [
    { id: 1, topic: "summary", target: "t1", query: SEP, said: "First question" },
    { id: 2, topic: "summary", target: "t2", query: SEP, said: "Second question" },
    { id: 3, topic: "summary", target: "t3", query: OCT, said: "Third question" },
    { id: 4, topic: "summary", target: "t4", query: OCT, said: "Fourth question" },
  ];
  const head = (h: string) => ({ ...answer, decision: { ...answer.decision, headline: h } });
  seed(client, asks[0], head("Old headline one"));
  seed(client, asks[1], head("Old headline two"));
  seed(client, asks[2], head("Old headline three"));
  seed(client, asks[3], head("Newest headline"));
  const out = panel(asks, client);
  const at = (s: string) => out.indexOf(s);
  for (const s of ["First question", "Second question", "Third question", "Fourth question"])
    assert.ok(at(s) >= 0, s);
  assert.ok(at("First question") < at("Second question"));
  assert.ok(at("Second question") < at("Third question"));
  assert.ok(at("Third question") < at("Fourth question"));
  assert.ok(out.includes("You asked"));
  // Every answer stays readable without reopening an older card.
  assert.equal((out.match(/aria-label="Show answer:/g) ?? []).length, 0);
  assert.equal((out.match(/Next step:/g) ?? []).length, 4);
  assert.ok(at("Newest headline") > at("Fourth question"));
  // one divider, before the first turn with the new filters; no per-card labels
  assert.equal((out.match(/Showing:/g) ?? []).length, 1);
  assert.ok(out.includes(">Showing: October 2026 · Film · P703 DBL RAPTOR</p>"));
  assert.ok(at("Second question") < at("Showing:") && at("Showing:") < at("Third question"));
  assert.ok(!out.includes("data-stale") && !out.includes("For September"));
  // old answers kept from their own query: nothing refetches, nothing loads
  // isFetching proves nothing in a static render: the proof is every turn found under its own seeded query key (no skeleton).
  assert.ok(!out.includes("Working out"));
  assert.ok(out.includes(">Clear chat<"));
  assert.match(out, /<p class="sr-only" aria-live="polite"><\/p>/);
});

test("panel: an answered slot prompt leaves no orphan prompt in the chat", () => {
  const client = new QueryClient();
  const asked: Ask[] = newAsk([], "colour_report", null, OCT, {}, "Colour report");
  seed(client, asked[0], needs);
  assert.ok(panel(asked, client).includes('data-choice="Red"'));
  const replaced = slotAnswer(asked, 1, "colour", "Red", "Red");
  seed(client, replaced[0], { ...answer, topic: "colour_report" });
  const out = panel(replaced, client);
  assert.equal(replaced.length, 1);
  assert.ok(!out.includes("data-choice=") && !out.includes("Which colour?"));
  assert.ok(out.includes("Colour report · Red") && out.includes(answer.decision.headline));
  // isFetching proves nothing in a static render: the proof is every turn found under its own seeded query key (no skeleton).
});

test("panel: a typed month shows a Showing divider though the filter bar says October", () => {
  const client = new QueryClient();
  const one = newAsk([], "summary", null, OCT, {}, "Month summary");
  const two = newAsk(
    one,
    "colour_report",
    null,
    OCT,
    { month: "2026-09", colour: "Red" },
    "colour report for September",
  );
  seed(client, one[0], answer);
  seed(client, two[1], { ...answer, topic: "colour_report" });
  const out = panel(two, client);
  assert.equal((out.match(/Showing:/g) ?? []).length, 1);
  assert.ok(out.includes(">Showing: September 2026 · Film · P703 DBL RAPTOR</p>"));
  assert.ok(out.indexOf("Showing:") < out.indexOf("colour report for September"));
  assert.ok(!out.includes("Working out"));
});

test("panel: no Clear chat button on an empty chat", () => {
  assert.ok(!panel([], new QueryClient()).includes("Clear chat"));
});

test("explicit month comparisons label the chart chronologically even when the page selects the older month", () => {
  const earlier = {
    ...answer,
    topic: "compare_months" as const,
    month: "2026-09",
    previous_month: "2026-08",
    evidence: ev(
      "shift",
      ["Box", "Before", "Now", "Change", "Verdict"],
      [["Ranger", "Pass", "Fail", "+10 µm", "Real shift"]],
      [{ x: 20, y: 30, label: "Ranger" }],
    ),
  };
  const out = renderToStaticMarkup(
    <AnswerCard
      answer={earlier}
      referenceMonth="2026-10"
      stale={null}
      collapsed={false}
      added={false}
      onExpand={noop}
      onFollowup={noop}
      onSlot={noop}
      onAddToSlides={noop}
    />,
  );
  assert.match(out, /September 2026<\/span><strong>20/);
  assert.match(out, /October 2026<\/span><strong>30/);
});
