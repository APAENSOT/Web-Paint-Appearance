/** AR04/AR05: typed text matched to a catalog question by its keywords, plus the asks. No AI. */

import { monthWords } from "./report-slides";
import { fillSlots, type LiveNames } from "./slot-match";
import type {
  AnalysisReport,
  AnalysisReportQuery,
  AssistantFollowup,
  AssistantQuestions,
} from "./report-types";

type Id = AssistantFollowup["topic"];

export type { LiveNames };

const LAYERS = ["ECOAT", "PRIMER", "BASE", "CLEAR"];
const WS_METRICS = ["lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b"];

/** Names typed text can mention: this plant's months, models and colours plus the fixed layers/metrics. */
export const liveNames = (o: AnalysisReport["options"]): LiveNames => ({
  models: o.models,
  colours: o.colors,
  months: o.months,
  layers: LAYERS,
  metrics: [...LAYERS, ...WS_METRICS],
});

// Band codes are also English ("we", "wa"): they count only when no question word matched.
const BAND_CODES = ["du", "wa", "wb", "wc", "wd", "we"];

// ASCII words must start a word ("trend" hits "trending", never "west" for "we");
// two-letter words must be the whole word. Thai has no spaces: plain substring.
const hit = (text: string, k: string) =>
  /^[a-z ]+$/.test(k)
    ? new RegExp(`\\b${k}${k.length <= 2 ? "\\b" : ""}`).test(text)
    : text.includes(k);

/**
 * The question the text asks and the details it names. The longest matched keyword
 * wins (ties: registry order), so "compare models" beats "compare". A generic
 * keyword ("compare", "เทียบ": inside another question's longer keyword) gives way:
 * first to a question whose first two details the text fills ("compare Raptor and
 * Ranger" → compare_models), then to any other question whose own keyword matched
 * ("compare left and right" → compare_sides).
 */
export function matchQuestion(
  text: string,
  catalog: AssistantQuestions,
  live: LiveNames,
): { id: Id; slots: Record<string, string> } | null {
  const t = text.toLowerCase();
  const kw = (id: Id) => catalog.keywords[id] ?? [];
  const hits: { id: Id; k: string }[] = [];
  for (const q of catalog.questions)
    for (const k of kw(q.id)) if (hit(t, k)) hits.push({ id: q.id, k });
  // Longest first; the sort is stable, so ties keep registry order.
  hits.sort((a, b) => b.k.length - a.k.length);
  if (!hits.length && BAND_CODES.some((k) => hit(t, k))) hits.push({ id: "bands", k: "" });
  if (!hits.length) return null;
  const { id, k } = hits[0];
  const fill = (id: Id) =>
    fillSlots(
      text,
      catalog.questions.find((x) => x.id === id)!,
      live,
    );
  const generic =
    k !== "" && catalog.questions.some((q) => kw(q.id).some((x) => x !== k && x.includes(k)));
  if (generic) {
    for (const q of catalog.questions) {
      const more = kw(q.id).some((x) => x !== k && x.includes(k));
      if (q.id === id || !more || q.slots.length < 2) continue;
      const slots = fill(q.id);
      if (slots[q.slots[0].name] && slots[q.slots[1].name]) return { id: q.id, slots };
    }
    const other = hits.find((h) => h.id !== id);
    if (other) return { id: other.id, slots: fill(other.id) };
  }
  return { id, slots: fill(id) };
}

// ------------------------------------------------------------------ asks
/** One question asked, with the filters it was asked with. Lives in the workspace. */
export type Ask = {
  id: number;
  topic: Id | null; // a catalog id; null: the typed text matched nothing, show the help card
  target: string | null;
  query: AnalysisReportQuery;
  slots?: Record<string, string>; // details sent with the ask (a, b, metric, ...)
  said?: string; // the user's bubble: the question label, typed text or chip picked
  added?: true; // already put in the slide deck
  controlQuery?: AnalysisReportQuery; // controls when asked; distinguishes a typed month from a filter change
};

/** A turn's fields; a month detail is the turn's month, so it goes in its query. */
const turn = (
  topic: Id | null,
  target: string | null,
  query: AnalysisReportQuery,
  slots: Record<string, string> = {},
  said?: string,
) => {
  const { month, ...rest } = slots;
  return { topic, target, query: month ? { ...query, month } : query, slots: rest, said };
};

/** The chat, oldest first: the new turn goes last. */
export const newAsk = (
  asks: Ask[],
  topic: Id | null,
  target: string | null,
  query: AnalysisReportQuery,
  slots?: Record<string, string>,
  said?: string,
): Ask[] => [
  ...asks,
  { id: Math.max(0, ...asks.map((a) => a.id)) + 1, ...turn(topic, target, query, slots, said) },
];

/** The re-ask when a needs_slot chip is tapped: the card's own query, the slot merged in. */
export const slotAsk = (ask: Ask, name: string, value: string) => ({
  topic: ask.topic,
  target: name === "target" ? value : ask.target,
  query: ask.query,
  slots: name === "target" ? { ...ask.slots } : { ...ask.slots, [name]: value },
});

/** A tapped chip answers its own turn: same id and place, so the prompt is not left behind. */
export const slotAnswer = (
  asks: Ask[],
  id: number,
  name: string,
  value: string,
  label: string,
): Ask[] =>
  asks.map((a) => {
    if (a.id !== id) return a;
    const r = slotAsk(a, name, value);
    return {
      ...a,
      ...turn(r.topic, r.target, r.query, r.slots, a.said ? `${a.said} · ${label}` : label),
    };
  });

const DOMAIN = { both: "Wave Scan and Film", wavescan: "Wave Scan", film: "Film" } as const;
// An unset month is the plant's newest month (the report's default).
const norm = (q: AnalysisReportQuery, month: string | null) =>
  JSON.stringify([
    q.month ?? month,
    q.domain ?? "both",
    [...(q.models ?? [])].sort(),
    [...(q.colors ?? [])].sort(),
  ]);

/** True when two turns were asked with the same month and filters. */
export const sameFilters = (
  a: AnalysisReportQuery,
  b: AnalysisReportQuery,
  newest: string | null,
) => norm(a, newest) === norm(b, newest);

/** "{Month YYYY} · {domain} · {models} · {colours}" for a turn's query. */
export function filterLabel(q: AnalysisReportQuery, newest: string | null): string {
  const month = q.month ?? newest;
  return [
    month ? monthWords(month) : "No month",
    DOMAIN[q.domain ?? "both"],
    (q.models ?? []).join(", "),
    (q.colors ?? []).join(", "),
  ]
    .filter(Boolean)
    .join(" · ");
}
