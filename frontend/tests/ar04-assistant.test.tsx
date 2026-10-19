import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { assistantAnswerOptions } from "../src/api/queries";
import { AnswerCard } from "../src/features/analysis/AnswerCard";
import { AssistantPanel } from "../src/features/analysis/AssistantPanel";
import { matchQuestion, newAsk, type Ask } from "../src/features/analysis/assistant-intents";
import {
  answerSlide,
  withAssistantSlides,
  type SlideSpec,
} from "../src/features/analysis/report-slides";
import type { AssistantAnswer } from "../src/features/analysis/report-types";
import { LIVE, QUESTIONS } from "./ar05-fixtures";

// AR05: the AR04 keyword rules now read the catalog's keywords.
const matchTopic = (q: string) => matchQuestion(q, QUESTIONS, LIVE)?.id ?? null;

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
  explanation: "",
  next_step: "Check Clear film build at R-12 and R-14",
  risk: { expected_out: 5, of_next: 30, basis: "current mean and spread" },
  confidence: "solid",
  evidence: {
    kind: "bar",
    columns: ["Box", "Status", "Out", "n"],
    rows: Array.from({ length: 7 }, (_, i) => [`Box ${i + 1}`, "Fail", 9 - i, i === 1 ? null : 34]),
    series: [],
    limits: null,
    cells: [],
    groups: [],
    points: [],
    card: [],
  },
  followups: [{ label: "Which colours?", topic: "colours", target: null }],
  method: { rule: "Rank boxes by severity", n: 12, caveats: [] },
};

const noop = () => {};
const card = (stale: string | null = null, a = answer, added = false) =>
  renderToStaticMarkup(
    <AnswerCard
      answer={a}
      stale={stale}
      collapsed={false}
      added={added}
      onExpand={noop}
      onFollowup={noop}
      onSlot={noop}
      onAddToSlides={noop}
    />,
  );
const text = (html: string) => html.replace(/<[^>]+>/g, " ");

test("matchTopic: ASCII whole-word starts, Thai substrings, first hit wins", () => {
  const cases: [string, string | null][] = [
    ["which colour is worst", "colours"],
    ["สีไหนต้องแก้", "colours"],
    ["is Wb getting worse", "trend"],
    // AR05 adds "why" to why_failing; band codes only count when no question keyword matched.
    ["why is wc high", "why_failing"],
    ["west door", null],
    ["จุดไหนเสีย", "points"],
    ["Is it trending?", "trend"],
    ["What changed", "changes"],
    ["quick summary", "summary"],
    // two-letter band codes only when nothing else matches ("we" is ordinary English)
    ["which colour do we fix first", "colours"],
    ["how are we doing this month", "summary"],
    ["where are we failing", "points"],
    ["what should we improve", "colours"],
    ["what about we", "bands"],
    ["band we", "bands"],
  ];
  for (const [q, want] of cases) assert.equal(matchTopic(q), want, q);
});

test("AnswerCard leads with the decision and folds the evidence to the top 5", () => {
  const out = card();
  assert.ok(out.includes("Fix first: Raptor Red · Clear · Horizontal"));
  assert.match(out, /data-tone="FAIL"[^>]*>.*?Fail</);
  assert.equal([...out.matchAll(/data-evidence-row/g)].length, 5);
  assert.ok(out.indexOf("data-evidence-row") < out.indexOf("Show all"));
  assert.ok(out.includes("If not fixed: about 5 of the next 30 cars out"));
  assert.ok(out.includes("Solid"));
  assert.ok(!text(out).includes("%"));
  assert.ok(!out.includes("data-stale"));
  assert.ok(card("October 2026 · Film").includes("For October 2026 · Film"));
});

test("an exploratory answer says how many it looked at", () => {
  const out = card(null, { ...answer, confidence: "exploratory", risk: null });
  assert.ok(out.includes("Exploratory, n 12"));
  assert.ok(!out.includes("If not fixed"));
});

test("answerSlide carries the risk line; withAssistantSlides goes before observations", () => {
  const s = answerSlide(answer);
  assert.deepEqual(s, {
    kind: "notes",
    title: "Fix first: Raptor Red · Clear · Horizontal — September 2026",
    nextSteps: ["Check Clear film build at R-12 and R-14"],
    summary: [
      "9 of 34 readings out",
      "If not fixed: about 5 of the next 30 cars out",
      "Method: Rank boxes by severity",
      "Box 1 · Fail · 9 · 34",
      "Box 2 · Fail · 8 · —",
      "Box 3 · Fail · 7 · 34",
      "Box 4 · Fail · 6 · 34",
      "Box 5 · Fail · 5 · 34",
    ],
  });
  const plan: SlideSpec[] = [
    { kind: "title", date: "", title: "t", subtitle: "" },
    { kind: "observations", title: "o", rows: [] },
    { kind: "notes", title: "n", nextSteps: [], summary: [] },
  ];
  assert.deepEqual(
    withAssistantSlides(plan, [s]).map((x) => x.title),
    ["t", s.title, "o", "n"],
  );
  assert.deepEqual(
    withAssistantSlides(plan.slice(0, 1), [s]).map((x) => x.title),
    ["t", s.title],
  );
});

test("an added answer cannot be added twice", () => {
  assert.match(card(null, answer, true), /disabled=""[^>]*>.*?Added to slides/);
  assert.ok(!card().includes("Added to slides"));
});

test("the ranked bar comes from a known column set only", () => {
  assert.match(card(), /role="img"/);
  const unknown = { ...answer, evidence: { ...answer.evidence, columns: ["A", "B", "Out", "n"] } };
  assert.doesNotMatch(card(null, unknown), /role="img"/);
  assert.equal([...card(null, unknown).matchAll(/data-evidence-row/g)].length, 5);
});

const asked = { domain: "both" as const };
test("a follow-up keeps the filters of the card it came from", () => {
  const old = { domain: "film" as const, month: "2026-08" };
  const asks = newAsk([], "summary", null, old);
  const next = newAsk(asks, "trend", "film|CLEAR|R|Red|H", asks[0].query);
  // AR06: oldest first.
  assert.deepEqual(
    next.map((a) => [a.id, a.topic, a.target, a.query]),
    [
      [1, "summary", null, old],
      [2, "trend", "film|CLEAR|R|Red|H", old],
    ],
  );
});

test("panel: after a filter change the card is still there, from its own query", () => {
  const client = new QueryClient();
  // AR06: oldest first; the newest (summary) is open.
  const asks: Ask[] = [
    { id: 1, topic: null, target: null, query: asked },
    { id: 2, topic: "summary", target: null, query: asked, added: true },
  ];
  client.setQueryData(
    assistantAnswerOptions("P703", { ...asked, topic: "summary", target: null }).queryKey,
    answer,
  );
  const out = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AssistantPanel
        code="P703"
        query={{ domain: "both", month: "2026-10" }}
        live={LIVE}
        asks={asks}
        onAsks={noop}
        onAddToSlides={noop}
      />
    </QueryClientProvider>,
  );
  assert.ok(out.includes("Fix first: Raptor Red · Clear · Horizontal"));
  // AR06: no per-card stale label any more.
  assert.ok(!out.includes("data-stale"));
  assert.ok(out.includes("Added to slides"));
  assert.ok(!out.includes("Working out"));
  assert.equal(client.isFetching(), 0);
  // The help card is older: collapsed to its title. The live region starts empty.
  assert.ok(out.includes("Let’s make that question more specific."));
  assert.match(out, /<p class="sr-only" aria-live="polite"><\/p>/);
});

test("AnswerCard: all clear is a Pass chip only for summary and colours", () => {
  const clear = (topic: AssistantAnswer["topic"]) =>
    card(null, {
      ...answer,
      topic,
      status: "all_clear",
      decision: { status_code: null, headline: "Ok" },
    });
  for (const topic of ["summary", "colours"] as const)
    assert.match(clear(topic), /data-tone="PASS"[^>]*>.*?All clear</, topic);
  assert.match(clear("changes"), /data-tone="NONE"[^>]*>.*?No change</);
  for (const topic of ["points", "bands"] as const)
    assert.match(clear(topic), /data-tone="NONE"[^>]*>.*?Nothing stands out</, topic);
});
