import type { components } from "@/api/types";
import { panelMatchPayload } from "@/api/mapping-state";

type PanelMatch = components["schemas"]["PanelMatchOut"];
type HeldPanel = components["schemas"]["HeldPanelOut"];
type LivePanel = components["schemas"]["LivePanelOut"];
type Candidate = components["schemas"]["PanelCandidateOut"];
type Blocked = components["schemas"]["BlockedPanelOut"];

/**
 * T86 guided panel match: the screen's own rules, with no React in them.
 *
 * Two things live here because they are the rules and not the rendering:
 *
 * - **every row is decided before Confirm is enabled** (task section 3.6).
 *   "Decided" means the person either chose a panel or said out loud that
 *   this name stays unmatched. Leaving a row untouched is not a decision,
 *   and a half-answered set is the thing the atomic backend refuses anyway;
 * - **the number is shown and never used.** Nothing in this file reads
 *   `raw_position` or `point_no` except to put it on the screen, and the
 *   candidate order is the server's (score, then name). D-86-3.
 *
 * Scores come from the server. This file never computes one -- a second
 * scorer in the client would be a second opinion about which panel a name
 * is, and there is only supposed to be one.
 */

/** What the person has said about one held spelling. */
export type Decision = { kind: "match"; zoneCode: string } | { kind: "unmatched" };

export type Decisions = Record<string, Decision>;

/** The key a decision is held under: the spelling, as the server spells it. */
export function panelKey(held: HeldPanel) {
  return held.raw_zone_text;
}

/** Live panels a confirmed pair may point at. The rest are shown, not offered. */
export function mappablePanels(view: PanelMatch): LivePanel[] {
  return view.live_panels.filter((panel) => panel.mappable);
}

/**
 * T89 (D-89-6): **the** list this held name may be answered with.
 *
 * It is the server's `choosable`, in the server's order -- suggestions
 * first, then the rest in walk order -- and the per-row picker in the
 * held-label list is handed the same array by the same backend call. The
 * screen does not build a list of its own any more: it used to offer every
 * mappable panel, which left an already-used panel choosable and could put
 * two of this file's names onto one panel.
 */
export function choosableFor(held: HeldPanel): string[] {
  return held.choosable ?? [];
}

/** Panels of the right orientation this file already used: shown, never offered. */
export function blockedFor(held: HeldPanel): Blocked[] {
  return held.blocked ?? [];
}

/**
 * T89 (D-89-9): the decisions the server says were already made.
 *
 * A carried-over row arrives **pre-selected** with the panel that spelling
 * was mapped to before. It is a pre-fill and not an answer: it is merged
 * UNDER what the person has said, it is not sent to the server as a
 * confirmed pair (so it never pins the solver), and nothing is applied
 * until the person presses Confirm.
 */
export function carriedDecisions(view: PanelMatch): Decisions {
  const out: Decisions = {};
  for (const held of view.held_panels) {
    const carried = held.carried_over;
    if (carried) out[panelKey(held)] = { kind: "match", zoneCode: carried.zone_code };
  }
  return out;
}

/**
 * T90 (D-90-5 / D-90-12): the answers an unchanged walk brings back.
 *
 * Only **yellow** rows, and only from `prefilled_zone_code` -- what was
 * confirmed last under this same fingerprint. A red row is never filled in
 * for somebody: the whole reason the two colours exist is that a red is a
 * decision nobody has made yet. Like T89's carry-over this is merged *under*
 * the person's own answers and nothing is applied until Confirm.
 */
export function walkPrefills(view: PanelMatch): Decisions {
  const out: Decisions = {};
  for (const held of view.held_panels) {
    const row = held.walk;
    if (!row || row.attention !== "yellow" || !row.prefilled_zone_code) continue;
    out[panelKey(held)] = { kind: "match", zoneCode: row.prefilled_zone_code };
  }
  return out;
}

/** What the screen is working with: the person's answers over the pre-fills. */
export function effectiveDecisions(view: PanelMatch, decisions: Decisions): Decisions {
  return { ...carriedDecisions(view), ...walkPrefills(view), ...decisions };
}

/** Why a row is pre-filled, in the owner's words, or null. */
export function carryOverLabel(held: HeldPanel): string | null {
  const carried = held.carried_over;
  if (!carried) return null;
  return `Carried over from an earlier decision: ${carried.reason}`;
}

/** How strong a match is, in words, for a screen reader and for a person. */
export function scoreLabel(candidate: Candidate) {
  return `${Math.round(candidate.score * 100)}% name match - ${candidate.basis}`;
}

/**
 * T88 (D-88-3): which signal argued for a pair, in the owner's words.
 *
 * The signal is shown beside every proposal so nobody has to guess whether
 * a suggestion came from the name, the walk number, or from there being
 * nothing else left. `exhaustion` is the one that can be confidently wrong,
 * so it says so loudest and carries the counts it rests on (G-88-3).
 */
export function signalLabel(held: HeldPanel): string {
  switch (held.signal) {
    case "exhaustion":
      return "Only one left";
    case "number":
      return "Matched on the number";
    case "name":
      return "Matched on the name";
    default:
      return "";
  }
}

/** True for the one signal that can be confidently wrong (G-88-3). */
export function isExhaustion(held: HeldPanel) {
  return held.signal === "exhaustion";
}

/** Panels the orientation filter hid from the proposals but not from the list. */
export function filteredOut(held: HeldPanel): string[] {
  return held.filtered_out ?? [];
}

/* ------------------------------------------------------------------ */
/* T90 -- the walk is the identity, the name is only a label           */
/* ------------------------------------------------------------------ */

type WalkRow = components["schemas"]["WalkRowOut"];
type WalkMatch = components["schemas"]["WalkMatchOut"];

/** The structural verdict for one held row, or null when there is none. */
export function walkOf(held: HeldPanel): WalkRow | null {
  return held.walk ?? null;
}

/**
 * T90 (D-90-6): `yellow`, `red`, or null when the walk says nothing.
 *
 * Read from the server and never computed here. There is no green: a rule
 * that applied cleanly is still confirmed by a person (D-90-5), so the best
 * a row can be is "looks right, still confirm".
 */
export function attentionOf(held: HeldPanel): "yellow" | "red" | null {
  const row = walkOf(held);
  if (!row) return null;
  return row.attention === "yellow" ? "yellow" : "red";
}

/** What the row says about itself, in the server's plain words. */
export function attentionLabel(row: WalkRow): string {
  return row.attention === "yellow" ? "Looks right - still confirm" : "Needs attention";
}

/**
 * T90 (D-90-2): the two answers, when the rules disagree and neither was
 * proposed. Empty for every other row, because there is nothing to show.
 */
export function ruleDisagreement(
  row: WalkRow,
): { groupOrdinal: string; walkNumber: string } | null {
  const a = row.rule_group_ordinal_zone_code;
  const b = row.rule_walk_number_zone_code;
  if (!a || !b || a === b) return null;
  return { groupOrdinal: a, walkNumber: b };
}

/** Held rows the walk marks yellow, which is what bulk accept confirms (D-90-14). */
export function yellowRows(view: PanelMatch): HeldPanel[] {
  return view.held_panels.filter((held) => attentionOf(held) === "yellow");
}

/** Held rows the walk marks red. These stay open; nothing sweeps them along. */
export function redRows(view: PanelMatch): HeldPanel[] {
  return view.held_panels.filter((held) => attentionOf(held) === "red");
}

/**
 * T90 (D-90-14): what one bulk click would do, in both numbers.
 *
 * Null when there is nothing yellow to accept. The counts are of the **held**
 * rows the screen can answer, not of `walk.rows` -- the walk covers every
 * name the file writes, including the ones that already resolve and are not
 * on this screen to be confirmed.
 */
export function bulkAcceptSummary(view: PanelMatch): {
  yellow: number;
  red: number;
  words: string;
} | null {
  const yellow = yellowRows(view).length;
  if (!yellow) return null;
  const red = redRows(view).length;
  return {
    yellow,
    red,
    words:
      red === 0
        ? `Accept all ${yellow} - every name matches the walk you confirmed before`
        : `Accept the ${yellow} that look right - ${red} still need you`,
  };
}

/**
 * T90 (D-90-14): the yellow rows' own answers, as decisions.
 *
 * Only yellow, and only rows with a proposal. A red is never confirmed by
 * this: the whole point of the two colours is that one click may not sweep
 * a row somebody has to look at.
 */
export function acceptAllYellow(view: PanelMatch): Decisions {
  const out: Decisions = {};
  for (const held of yellowRows(view)) {
    const row = walkOf(held);
    const zone = row?.prefilled_zone_code ?? row?.proposed_zone_code;
    if (zone) out[panelKey(held)] = { kind: "match", zoneCode: zone };
  }
  return out;
}

/** The walk block, or null when this sheet produced no structural reading. */
export function walkMatch(view: PanelMatch): WalkMatch | null {
  return view.walk ?? null;
}

/**
 * T90 (D-90-11): the confirmed walk this set records on its batch.
 *
 * Every pair the person answered that the walk knows about, rough **and**
 * specific, with the server's own classification. `matches` carries only the
 * specific ones (D-90-3); this carries the whole walk, so the next upload of
 * the same fingerprint can be pre-filled from it.
 */
export function walkPairs(
  view: PanelMatch,
  decisions: Decisions,
): { fingerprint: string; pairs: WalkConfirmedPair[] } | null {
  const walk = walkMatch(view);
  if (!walk) return null;
  const answered = effectiveDecisions(view, decisions);
  const bySpelling = new Map(walk.rows.map((row) => [row.raw_zone_text, row]));
  const pairs: WalkConfirmedPair[] = [];
  for (const held of view.held_panels) {
    const decision = answered[panelKey(held)];
    const row = bySpelling.get(held.raw_zone_text);
    if (!row || !decision || decision.kind !== "match") continue;
    pairs.push({
      raw_zone_text: row.raw_zone_text,
      zone_code: decision.zoneCode,
      specificity: row.specificity === "specific" ? "specific" : "rough",
      rule: walkRule(row),
      attention: row.attention === "yellow" ? "yellow" : "red",
    });
  }
  return pairs.length ? { fingerprint: walk.fingerprint, pairs } : null;
}

export type WalkConfirmedPair = {
  raw_zone_text: string;
  zone_code: string;
  specificity: "rough" | "specific";
  rule: "group_ordinal" | "walk_number" | "none";
  attention: "yellow" | "red";
};

function walkRule(row: WalkRow): "group_ordinal" | "walk_number" | "none" {
  if (row.rule === "group_ordinal") return "group_ordinal";
  if (row.rule === "walk_number") return "walk_number";
  return "none";
}

/** Spellings the walk calls rough, which may never become permanent aliases. */
export function roughSpellings(view: PanelMatch): Set<string> {
  const walk = walkMatch(view);
  return new Set(
    (walk?.rows ?? []).filter((row) => row.specificity === "rough").map((row) => row.raw_zone_text),
  );
}

/**
 * T91 (D-91-3): spellings that may only be confirmed for THIS upload.
 *
 * The server says so per row, in `binding`, and it says it for two
 * different reasons: the sheet's own (`rough`, D-90-3) and the plant's
 * history (a name another sheet here confirmed as a different panel,
 * D-91-2). The second one catches what `specificity` alone cannot --
 * `13LFRDOOR` is specific in September and is still a pillar in August --
 * so this, not `roughSpellings`, is what keeps a pair out of `matches`.
 */
export function perBatchSpellings(view: PanelMatch): Set<string> {
  const walk = walkMatch(view);
  return new Set(
    (walk?.rows ?? [])
      .filter((row) => row.binding === "batch" || row.specificity === "rough")
      .map((row) => row.raw_zone_text),
  );
}

/** Why a spelling is per-batch, by spelling, for the row that shows it. */
export function bindingReasons(view: PanelMatch): Map<string, string> {
  const walk = walkMatch(view);
  return new Map(
    (walk?.rows ?? [])
      .filter((row) => row.binding_reason)
      .map((row) => [row.raw_zone_text, row.binding_reason as string]),
  );
}

/** The pairs the owner has confirmed, as the read model's `confirmed` query. */
export function confirmedPairs(decisions: Decisions): string[] {
  return Object.entries(decisions)
    .filter(([, decision]) => decision.kind === "match")
    .map(([spelling, decision]) => `${spelling}=${(decision as { zoneCode: string }).zoneCode}`)
    .sort();
}

/**
 * The candidate the screen shows first, or null when the server offered none.
 * It is a suggestion on a row nobody has answered yet, never an answer.
 */
export function suggestionFor(held: HeldPanel): Candidate | null {
  return held.candidates?.[0] ?? null;
}

/** Rows the person still has to answer, in the order they are shown. */
export function undecided(view: PanelMatch, decisions: Decisions): HeldPanel[] {
  const effective = effectiveDecisions(view, decisions);
  return view.held_panels.filter((held) => !effective[panelKey(held)]);
}

/** Confirm is enabled only when every row is decided and at least one is a match. */
export function canConfirm(view: PanelMatch, decisions: Decisions) {
  if (!view.held_panels.length) return false;
  if (undecided(view, decisions).length) return false;
  return matchedPairs(view, decisions).length > 0;
}

/** Why Confirm is disabled, in the uploader's words, or null when it is not. */
export function confirmBlocker(view: PanelMatch, decisions: Decisions) {
  if (!view.held_panels.length) return "No panel names are held on this tab.";
  const left = undecided(view, decisions).length;
  if (left)
    return `${left} panel ${left === 1 ? "name has" : "names have"} no answer yet. Choose a panel, or mark it unmatched.`;
  if (!matchedPairs(view, decisions).length)
    return "Every name is marked unmatched, so there is nothing to confirm.";
  return null;
}

/** Two spellings sent onto one panel, which the backend refuses as a set. */
export function duplicateTargets(view: PanelMatch, decisions: Decisions): string[] {
  const codes = matchedPairs(view, decisions).map((pair) => pair.zone_code);
  return [...new Set(codes.filter((code) => codes.indexOf(code) !== codes.lastIndexOf(code)))];
}

/** The pairs the person actually decided, in the screen's own order. */
export function matchedPairs(view: PanelMatch, decisions: Decisions) {
  const effective = effectiveDecisions(view, decisions);
  return view.held_panels.flatMap((held) => {
    const decision = effective[panelKey(held)];
    if (!decision || decision.kind !== "match") return [];
    return [
      {
        raw_zone_text: held.raw_zone_text,
        // Carried because the file wrote it, not because anything read it.
        raw_position: held.raw_position ?? null,
        zone_code: decision.zoneCode,
      },
    ];
  });
}

export type ConfirmInput = {
  view: PanelMatch;
  decisions: Decisions;
  retireZoneCodes: string[];
  retireReason: string;
  decidedBy: string;
  method: string;
  note: string;
};

/**
 * The ZONE proposal body for this screen, or a thrown error naming what is
 * missing. Validated against the same strict shape the backend parses.
 */
export function panelMatchProposal(input: ConfirmInput): components["schemas"]["ProposalCreate"] {
  const { view, decisions } = input;
  const blocker = confirmBlocker(view, decisions);
  if (blocker) throw new Error(blocker);
  const repeated = duplicateTargets(view, decisions);
  if (repeated.length)
    throw new Error(
      `Two names are matched onto ${repeated.join(", ")}. One panel is one panel: change one of them.`,
    );
  const retire = input.retireZoneCodes.length
    ? { zone_codes: input.retireZoneCodes, reason: input.retireReason.trim() }
    : null;
  if (retire && !retire.reason)
    throw new Error("Say why those panels are superseded; it is stored on every row.");
  const overlap = input.retireZoneCodes.filter((code) =>
    matchedPairs(view, decisions).some((pair) => pair.zone_code === code),
  );
  if (overlap.length)
    throw new Error(
      `${overlap.join(", ")} cannot be both matched onto and retired: the match would be stored and never read.`,
    );
  // T90 (D-90-3): only a SPECIFIC name may become a permanent alias. A
  // rough one -- `01HOOD`, one of five, where the number is what identifies
  // it -- is confirmed on this batch instead, so the month the plant
  // reshuffles its walk it cannot file a hood as the wrong hood. The server
  // refuses a rough name in `matches` by name; the screen does not send one.
  //
  // T91 (D-91-2) widens that: a name is also per-batch when another sheet
  // of this plant confirmed it as a DIFFERENT panel, however specific it
  // looks here. The server says which, per row, in `binding`.
  const perBatch = perBatchSpellings(view);
  const walk = walkPairs(view, decisions);
  const permanent = matchedPairs(view, decisions).filter(
    (pair) => !perBatch.has(pair.raw_zone_text),
  );
  // A set records the permanent aliases, the walk, or both. One that
  // records neither is a no-op, which the backend refuses in the same words.
  if (!permanent.length && !walk)
    throw new Error(
      "Nothing would be recorded: no name here can become a permanent alias and " +
        "this sheet has no confirmed walk to record either.",
    );
  const parsed = panelMatchPayload.safeParse({
    plant_code: view.plant_code,
    model_code: view.model_code,
    load_id: view.load_id,
    matches: permanent,
    ...(retire ? { retire } : {}),
    ...(walk ? { walk } : {}),
    decided_by: input.decidedBy.trim(),
    method: input.method.trim(),
    note: input.note.trim(),
  });
  if (!parsed.success)
    throw new Error(
      parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; "),
    );
  return { kind: "ZONE", load_id: view.load_id, payload: parsed.data };
}
