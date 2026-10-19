import type { AssistantAnswer, AssistantQuestions, AssistantSlot } from "./report-types";

/** High-specificity conversational phrases precede the catalogue's broad keywords. */
export function conversationalIntent(
  text: string,
  catalog: AssistantQuestions,
): AssistantAnswer["topic"] | null {
  const rules: [AssistantAnswer["topic"], RegExp][] = [
    ["cars_or_process", /\b(?:few cars|all cars|whole process|isolated|widespread)\b/i],
    ["centre_or_spread", /\b(?:centr(?:e|ing)|center(?:ing)?|spread|variation|consistent)\b/i],
    ["data_complete", /\b(?:missing data|enough data|data complete|measurement coverage)\b/i],
    ["next_month_risk", /\b(?:next month|forecast|predict|at risk)\b/i],
    ["compare_sides", /\b(?:left and right|left vs right|left versus right)\b/i],
    ["compare_orient", /\b(?:horizontal and vertical|horizontal vs vertical)\b/i],
    ["why_failing", /\b(?:why|what is causing|what causes|reason for|what went wrong)\b/i],
    ["recurring", /\b(?:keep happening|happened before|recurring|repeated issue)\b/i],
    [
      "changes",
      /\b(?:the difference|what(?: has)? changed|show (?:me )?(?:a )?comparison|since last month)\b/i,
    ],
    ["went_well", /\b(?:went well|got better|improved|good news)\b/i],
    [
      "summary",
      /\b(?:how (?:are we|is it|is the plant) doing|needs? attention|check first|start with|where (?:should|do) i start|main problem|biggest problem|priorit(?:y|ies|ize))\b/i,
    ],
  ];
  return (
    rules.find(
      ([id, pattern]) => catalog.questions.some((q) => q.id === id) && pattern.test(text),
    )?.[0] ?? null
  );
}

/** Exact choices first, then an unambiguous trailing name such as “Raptor”. */
export function resolveSlotChoice(text: string, slot: AssistantSlot) {
  const normalize = (value: string) =>
    value
      .normalize("NFKC")
      .trim()
      .toLowerCase()
      .replace(/[?!.,]+$/g, "");
  const typed = normalize(text).replace(/^(?:the |model |colour |color )/, "");
  if (!typed) return null;
  const exact = slot.choices.filter((c) => [c.value, c.label].some((v) => normalize(v) === typed));
  if (exact.length) return exact.length === 1 ? exact[0] : null;
  if (typed.length < 3) return null;
  const short = slot.choices.filter((c) =>
    [c.value, c.label].some((v) => normalize(v).endsWith(` ${typed}`)),
  );
  return short.length === 1 ? short[0] : null;
}
