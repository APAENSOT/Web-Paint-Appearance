import { matchQuestion, sameFilters, type Ask, type LiveNames } from "./assistant-intents";
import { fillSlots, scanLiveNames, explicitMonths } from "./slot-match";
import { conversationalIntent } from "./guide-language";
export { resolveSlotChoice } from "./guide-language";
import type { AnalysisReportQuery, AssistantAnswer, AssistantQuestions } from "./report-types";

type ResolvedQuestion = {
  id: AssistantAnswer["topic"];
  target: string | null;
  query: AnalysisReportQuery;
  slots: Record<string, string>;
};

/** Explicit phrases and API-provided follow-ups, never a guess at a measurement or target. */
export function resolveGuideQuestion(
  text: string,
  catalog: AssistantQuestions,
  live: LiveNames,
  query: AnalysisReportQuery,
  previous?: { ask: Ask; answer?: AssistantAnswer },
): ResolvedQuestion | null {
  const normalized = text
    .trim()
    .toLowerCase()
    .replace(/[?!.,]+$/g, "");
  const contextual =
    previous &&
    sameFilters(previous.ask.controlQuery ?? previous.ask.query, query, live.months[0] ?? null);
  const followup = contextual
    ? previous.answer?.followups.find(
        (f) => f.label.toLowerCase().replace(/[?!.,]+$/g, "") === normalized,
      )
    : undefined;
  if (followup && previous)
    return { id: followup.topic, target: followup.target, query: previous.ask.query, slots: {} };
  const aliases: Record<string, AssistantAnswer["topic"]> = {
    "what needs attention": "summary",
    "what needs attention this month": "summary",
    "what should i check first": "summary",
    "where should i start": "summary",
    why: "why_failing",
    "why is this failing": "why_failing",
    "which colour": "colours",
    "which color": "colours",
    "what changed": "changes",
  };
  const alias = aliases[normalized];
  const named = scanLiveNames(text, live);
  const models = named.filter((x) => x.kind === "model").map((x) => x.value);
  const colours = named.filter((x) => x.kind === "colour").map((x) => x.value);
  const dated = explicitMonths(text);
  const months = dated.length ? dated : named.filter((x) => x.kind === "month").map((x) => x.value);
  const comparison = /\b(?:compar\w*|versus|vs|difference|different)\b/i.test(text);
  const about = /\b(?:what about|how about|and for)\b/i.test(text);
  const refer =
    contextual && /\b(?:it|that|this|those|same|what about|how about|why|difference)\b/i.test(text);
  const priorModel = refer
    ? (previous?.ask.slots?.model ??
      (previous?.ask.query.models?.length === 1 ? previous.ask.query.models[0] : undefined))
    : undefined;
  if (
    comparison &&
    refer &&
    models.length === 1 &&
    priorModel &&
    models[0] !== priorModel &&
    live.models.includes(priorModel) &&
    catalog.questions.some((q) => q.id === "compare_models")
  )
    return {
      id: "compare_models" as const,
      target: null,
      query: { ...previous.ask.query, models: [priorModel, models[0]] },
      slots: {
        a: priorModel,
        b: models[0],
        ...(previous.ask.slots?.metric ? { metric: previous.ask.slots.metric } : {}),
      },
    };
  const explicitIntent =
    comparison && models.length >= 2
      ? "compare_models"
      : comparison && colours.length >= 2
        ? "compare_colours"
        : comparison && months.length >= 2
          ? "compare_months"
          : about && models.length === 1
            ? "model_report"
            : about && colours.length === 1
              ? "colour_report"
              : (alias ?? conversationalIntent(text, catalog));
  const question = explicitIntent && catalog.questions.find((q) => q.id === explicitIntent);
  const parsed = question
    ? { id: question.id, slots: fillSlots(text, question, live) }
    : matchQuestion(text, catalog, live);
  // A single named month after "compare with" compares the active month with that month.
  if (/\bcompare (?:it |that )?(?:with|to)\s/i.test(text)) {
    const comparison = catalog.questions.find((q) => q.id === "compare_months");
    if (comparison) {
      const slots = fillSlots(text, comparison, live);
      if (months.length === 1) slots.month = months[0];
      if (slots.month && !slots.month2)
        return {
          id: comparison.id,
          target: null,
          query: contextual ? previous.ask.query : query,
          slots: {
            month: (contextual ? previous.ask.query.month : query.month) ?? live.months[0],
            month2: slots.month,
          },
        };
    }
  }
  if (!parsed) return null;
  const slots = { ...parsed.slots };
  if (parsed.id === "compare_months" && months.length >= 2) {
    slots.month = months[0];
    slots.month2 = months[1];
  }
  const selected = catalog.questions.find((q) => q.id === parsed.id);
  if (refer && previous)
    for (const spec of selected?.slots ?? []) {
      const value = previous.ask.slots?.[spec.name];
      const comparable =
        spec.name === "a" || spec.name === "b"
          ? previous.ask.topic === parsed.id
          : spec.name !== "month" && spec.name !== "month2" && spec.name !== "target";
      if (value && comparable && !slots[spec.name]) slots[spec.name] = value;
    }
  // Reuse only an explicit target offered by the backend for this particular next question.
  const offered =
    contextual && !Object.keys(parsed.slots).length
      ? previous.answer?.followups.find((f) => f.topic === parsed.id)
      : undefined;
  const scoped = refer && previous ? previous.ask.query : query;
  const filtered = !parsed.id.startsWith("compare_")
    ? {
        ...scoped,
        ...(models.length === 1 ? { models } : refer && priorModel ? { models: [priorModel] } : {}),
        ...(colours.length === 1 ? { colors: colours } : {}),
      }
    : {
        ...scoped,
        ...(parsed.id === "compare_models" && slots.a && slots.b
          ? { models: [slots.a, slots.b] }
          : {}),
        ...(parsed.id === "compare_colours" && slots.a && slots.b
          ? { colors: [slots.a, slots.b] }
          : {}),
      };
  return {
    ...parsed,
    slots: {
      ...slots,
      ...(months.length === 1 && parsed.id !== "compare_months" ? { month: months[0] } : {}),
    },
    target: offered?.target ?? null,
    query: offered && previous ? previous.ask.query : filtered,
  };
}
