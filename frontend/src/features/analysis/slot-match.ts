/** AR05: fill a question's details from typed text by matching live names. No AI. */

import type { AssistantQuestion } from "./report-types";

/** Names the typed text can mention: live from the AR03 report options, plus fixed vocabularies. */
export type LiveNames = {
  models: string[];
  colours: string[];
  layers: string[];
  metrics: string[];
  months: string[];
};

const LAYER_WORDS: Record<string, string[]> = {
  ECOAT: ["e-coat", "e coat", "ecoat", "อีโค้ท"],
  PRIMER: ["primer", "ไพรเมอร์"],
  BASE: ["base", "เบส"],
  CLEAR: ["clear", "เคลียร์"],
};
const SIDE_WORDS: Record<string, string[]> = { L: ["left", "ซ้าย"], R: ["right", "ขวา"] };
const MONTHS_EN = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
];
const MONTHS_TH = [
  "มกราคม",
  "กุมภาพันธ์",
  "มีนาคม",
  "เมษายน",
  "พฤษภาคม",
  "มิถุนายน",
  "กรกฎาคม",
  "สิงหาคม",
  "กันยายน",
  "ตุลาคม",
  "พฤศจิกายน",
  "ธันวาคม",
];

/** An explicitly requested date stays explicit even when that month has no readings. */
export function explicitMonths(text: string): string[] {
  const found: { at: number; value: string }[] = [];
  for (const match of text.matchAll(/\b(\d{4})-(0[1-9]|1[0-2])\b/g))
    found.push({ at: match.index, value: match[0] });
  MONTHS_EN.forEach((word, i) => {
    for (const match of text.matchAll(
      new RegExp(`\\b(?:${word}|${word.slice(0, 3)})[,\\s]+(\\d{4})\\b`, "gi"),
    ))
      found.push({ at: match.index, value: `${match[1]}-${String(i + 1).padStart(2, "0")}` });
  });
  return found.sort((a, b) => a.at - b.at).map((m) => m.value);
}
const PLAIN_WORDS = new Set(["we", "b"]);
// layer_vs_band's band slot: the bands a layer can be linked to (backend assistant_slots.BANDS).
const BANDS = ["du", "wa", "wb", "wc", "wd", "we", "cf"];
// A metric slot also takes a Film layer (metrics = layers + Wave Scan codes).
const TAKES: Record<string, string[]> = {
  model: ["model"],
  colour: ["colour"],
  layer: ["layer"],
  metric: ["layer", "metric"],
  band: ["metric"],
  side: ["side"],
  month: ["month"],
};

/** Where `term` first appears in lower-cased `text`: whole words for ASCII, substring for Thai. */
function find(text: string, term: string): number {
  const t = term.toLowerCase();
  if (!/^[\x20-\x7e]+$/.test(t)) return text.indexOf(t);
  const esc = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = new RegExp(`(^|[^a-z0-9])${esc}(?![a-z0-9])`).exec(text);
  return m ? m.index + m[1].length : -1;
}

type Found = { at: number; end: number; kind: string; value: string };

/** Every live name in the text, in text order. */
export function scanLiveNames(text: string, live: LiveNames): Found[] {
  const t = text.toLowerCase();
  const out: Found[] = [];
  const add = (kind: string, value: string, terms: string[]) => {
    const hits = terms.map((x) => ({ at: find(t, x), end: find(t, x) + x.length }));
    const first = hits.filter((h) => h.at >= 0).sort((a, b) => a.at - b.at || b.end - a.end)[0];
    if (first) out.push({ ...first, kind, value });
  };
  // A model is named by its code or its last word ("Raptor" → P703 DBL RAPTOR).
  for (const m of live.models) add("model", m, [m, m.trim().split(/\s+/).at(-1)!]);
  for (const c of live.colours) add("colour", c, [c]);
  for (const [code, words] of Object.entries(LAYER_WORDS))
    if (live.layers.includes(code) || live.metrics.includes(code)) add("layer", code, words);
  // "we" and "b" are ordinary English: only "We band", "band We" or "B value" name the metric.
  for (const m of live.metrics)
    if (!(m in LAYER_WORDS))
      add("metric", m, PLAIN_WORDS.has(m) ? [`${m} band`, `band ${m}`, `${m} value`] : [m]);
  for (const [side, words] of Object.entries(SIDE_WORDS)) add("side", side, words);
  for (const month of live.months) {
    const i = Number(month.slice(5, 7)) - 1;
    // "may" is ordinary English: May counts with a capital (below) or followed by its year.
    const qualified = [
      ...t.matchAll(
        new RegExp(`\\b(?:${MONTHS_EN[i]}|${MONTHS_EN[i].slice(0, 3)})[,\\s]+(\\d{4})\\b`, "g"),
      ),
    ];
    const en = qualified.length
      ? qualified.filter((m) => m[1] === month.slice(0, 4)).map((m) => m[0])
      : i === 4
        ? [`may ${month.slice(0, 4)}`]
        : [MONTHS_EN[i], MONTHS_EN[i].slice(0, 3)];
    add("month", month, [month, ...en, MONTHS_TH[i]]);
  }
  // After the loop, so a "May 2025" found above wins over the newest May at the same place.
  const may = /(^|[^A-Za-z0-9])May(?![A-Za-z0-9])/.exec(text);
  if (may && !/\bmay[,\s]+\d{4}\b/i.test(text))
    for (const month of live.months)
      if (month.slice(5, 7) === "05")
        out.push({
          at: may.index + may[1].length,
          end: may.index + may[1].length + 3,
          kind: "month",
          value: month,
        });
  // A colour or model inside a longer match is part of that name ("Oxford White" is not also "White").
  const inside = (f: Found) =>
    (f.kind === "colour" || f.kind === "model") &&
    out.some((g) => g !== f && g.at <= f.at && f.end <= g.end && g.end - g.at > f.end - f.at);
  // Live months are newest first: a month name keeps its newest month only.
  return out
    .filter((f) => !inside(f))
    .sort((a, b) => a.at - b.at)
    .filter((f, i, all) =>
      f.kind === "month"
        ? all.findIndex((g) => g.kind === f.kind && g.at === f.at) === i
        : !all.some(
            (g) =>
              g !== f &&
              g.kind === f.kind &&
              g.at === f.at &&
              g.end === f.end &&
              g.value !== f.value,
          ),
    );
}

/** The question's details found in the text, in text order → its slots in their order. */
export function fillSlots(
  text: string,
  question: AssistantQuestion,
  live: LiveNames,
): Record<string, string> {
  const found = scanLiveNames(text, live);
  const slots: Record<string, string> = {};
  for (const s of question.slots) {
    const i = found.findIndex(
      (f) =>
        (TAKES[s.kind] ?? []).includes(f.kind) &&
        (s.kind !== "metric" || live.metrics.includes(f.value)) &&
        (s.kind !== "band" || BANDS.includes(f.value)) &&
        (s.kind !== "layer" || live.layers.includes(f.value)),
    );
    if (i >= 0) slots[s.name] = found.splice(i, 1)[0].value;
  }
  return slots;
}
