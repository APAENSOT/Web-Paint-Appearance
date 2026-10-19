import assert from "node:assert/strict";
import { test } from "node:test";
import { resolveGuideQuestion } from "../src/features/analysis/guide-conversation";
import type { Ask } from "../src/features/analysis/assistant-intents";
import type { AssistantAnswer } from "../src/features/analysis/report-types";
import { QUESTIONS } from "./ar05-fixtures";

const live = {
  models: ["P703 DBL RAPTOR"],
  colours: ["Red"],
  months: ["2026-10", "2026-09"],
  layers: ["CLEAR"],
  metrics: ["CLEAR"],
};
const query = { month: "2026-10", domain: "both" as const };
const ask: Ask = { id: 1, topic: "summary", target: null, query };
const answer = {
  followups: [
    { topic: "why_failing", target: "film|PRIMER|RANGER|Blue|V", label: "Why is this failing?" },
  ],
} as AssistantAnswer;

test("natural starter phrases resolve to an available catalogue question", () => {
  assert.equal(
    resolveGuideQuestion("What should I check first?", QUESTIONS, live, query)?.id,
    "summary",
  );
  assert.equal(
    resolveGuideQuestion("What needs attention this month?", QUESTIONS, live, query)?.id,
    "summary",
  );
  assert.equal(resolveGuideQuestion("order paint for tomorrow", QUESTIONS, live, query), null);
});

test("a typed follow-up reuses the API-offered target; changed controls discard it", () => {
  assert.equal(
    resolveGuideQuestion("why?", QUESTIONS, live, query, { ask, answer })?.target,
    answer.followups[0].target,
  );
  assert.equal(
    resolveGuideQuestion("why?", QUESTIONS, live, { ...query, month: "2026-09" }, { ask, answer })
      ?.target,
    null,
  );
});

test("a named comparison month is the second month, not a replacement for the active month", () => {
  const result = resolveGuideQuestion("Compare with September", QUESTIONS, live, query, {
    ask,
    answer,
  });
  assert.equal(result?.id, "compare_months");
  assert.deepEqual(result?.slots, { month: "2026-10", month2: "2026-09" });
});

test("a typed month can continue its conversation while the page controls stay unchanged", () => {
  const previous = {
    ask: { ...ask, query: { ...query, month: "2026-09" }, controlQuery: query },
    answer,
  };
  assert.equal(
    resolveGuideQuestion("Why is this failing?", QUESTIONS, live, query, previous)?.query.month,
    "2026-09",
  );
  assert.equal(
    resolveGuideQuestion(
      "Why is this failing?",
      QUESTIONS,
      live,
      { ...query, domain: "film" },
      previous,
    )?.target,
    null,
  );
});

test("conversational comparison requests resolve without exact catalogue wording", () => {
  assert.equal(
    resolveGuideQuestion("Can you show me the difference?", QUESTIONS, live, query, { ask, answer })
      ?.id,
    "changes",
  );
  assert.equal(resolveGuideQuestion("How are we doing?", QUESTIONS, live, query)?.id, "summary");
  assert.equal(
    resolveGuideQuestion("What about Raptor?", QUESTIONS, live, query, { ask, answer })?.id,
    "model_report",
  );
});

test("a short model reply completes only one unambiguous pending choice", async () => {
  const { resolveSlotChoice } = await import("../src/features/analysis/guide-conversation");
  const slot = {
    name: "a",
    prompt: "Which model?",
    choices: [
      { value: "P703 DBL RAPTOR", label: "P703 DBL RAPTOR" },
      { value: "P703 DBL RANGER", label: "P703 DBL RANGER" },
    ],
  };
  assert.equal(resolveSlotChoice("Raptor", slot)?.value, "P703 DBL RAPTOR");
  assert.equal(resolveSlotChoice("P703", slot), null);
  assert.equal(
    resolveSlotChoice("White", {
      ...slot,
      choices: [
        { value: "Arctic White", label: "Arctic White" },
        { value: "Oxford White", label: "Oxford White" },
      ],
    }),
    null,
  );
});

test("a follow-up carries compatible explicit slots, while a new model overrides the old one", () => {
  const previous = {
    ask: {
      ...ask,
      topic: "model_report" as const,
      slots: { model: "P703 DBL RAPTOR", metric: "CLEAR" },
    },
    answer,
  };
  const next = resolveGuideQuestion(
    "compare left and right for this",
    QUESTIONS,
    live,
    query,
    previous,
  );
  assert.equal(next?.id, "compare_sides");
  assert.equal(next?.slots.metric, "CLEAR");
  const models = { ...live, models: ["P703 DBL RAPTOR", "P703 DBL RANGER"] };
  const other = resolveGuideQuestion("What about Ranger?", QUESTIONS, models, query, previous);
  assert.equal(other?.slots.model, "P703 DBL RANGER");
});

test("comparing the current model with another model keeps both in the request scope", () => {
  const models = { ...live, models: ["P703 DBL RAPTOR", "P703 DBL RANGER"] };
  const previous = {
    ask: {
      ...ask,
      topic: "model_report" as const,
      slots: { model: "P703 DBL RAPTOR" },
      query: { ...query, models: ["P703 DBL RAPTOR"] },
      controlQuery: query,
    },
    answer,
  };
  const result = resolveGuideQuestion("Compare it with Ranger", QUESTIONS, models, query, previous);
  assert.equal(result?.id, "compare_models");
  assert.deepEqual(result?.slots, { a: "P703 DBL RAPTOR", b: "P703 DBL RANGER" });
  assert.deepEqual(result?.query.models, ["P703 DBL RAPTOR", "P703 DBL RANGER"]);
});

test("shared short model names do not silently choose the first matching model", async () => {
  const { scanLiveNames } = await import("../src/features/analysis/slot-match");
  const names = { ...live, models: ["P703 DBL RANGER", "P703 REGULAR RANGER"] };
  assert.equal(scanLiveNames("Ranger", names).filter((x) => x.kind === "model").length, 0);
  assert.equal(
    scanLiveNames("P703 DBL RANGER", names).find((x) => x.kind === "model")?.value,
    "P703 DBL RANGER",
  );
});

test("an explicit English month year wins over a newer month with the same name", () => {
  const years = { ...live, months: ["2026-01", "2025-01", "2024-01", "2026-05", "2025-05"] };
  const january = resolveGuideQuestion("What changed in January 2025?", QUESTIONS, years, query);
  assert.equal(january?.slots.month, "2025-01");
  assert.equal(
    resolveGuideQuestion("What changed in Jan, 2024?", QUESTIONS, years, query)?.slots.month,
    "2024-01",
  );
  assert.equal(
    resolveGuideQuestion("What changed in May 2025?", QUESTIONS, years, query)?.slots.month,
    "2025-05",
  );
  const pair = resolveGuideQuestion(
    "Compare January 2025 with January 2026",
    QUESTIONS,
    years,
    query,
  );
  assert.equal(pair?.id, "compare_months");
  assert.deepEqual(pair?.slots, { month: "2025-01", month2: "2026-01" });
  assert.equal(
    resolveGuideQuestion("What changed in January 2023?", QUESTIONS, years, query)?.slots.month,
    "2023-01",
  );
});
