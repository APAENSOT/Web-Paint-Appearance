import assert from "node:assert/strict";
import { test } from "node:test";
import type { components } from "../src/api/types";
import {
  blockedFor,
  canConfirm,
  carriedDecisions,
  carryOverLabel,
  choosableFor,
  confirmedPairs,
  filteredOut,
  isExhaustion,
  signalLabel,
  confirmBlocker,
  type Decisions,
  duplicateTargets,
  mappablePanels,
  matchedPairs,
  panelMatchProposal,
  scoreLabel,
  suggestionFor,
  undecided,
  acceptAllYellow,
  attentionLabel,
  attentionOf,
  bulkAcceptSummary,
  effectiveDecisions,
  redRows,
  roughSpellings,
  perBatchSpellings,
  bindingReasons,
  ruleDisagreement,
  walkMatch,
  walkPrefills,
  yellowRows,
} from "../src/features/measurements/panel-match";

type PanelMatch = components["schemas"]["PanelMatchOut"];

const candidate = (
  zone_code: string,
  point_no: number,
  score: number,
  basis = "similar name",
): components["schemas"]["PanelCandidateOut"] => ({
  zone_code,
  point_no,
  tolerance_group: zone_code.toUpperCase().includes("ROOF") ? "Horizontal" : "Vertical",
  score,
  basis,
});

const view: PanelMatch = {
  plant_code: "FTM",
  model_code: "P703 DBL RANGER",
  load_id: 123,
  source_sheet: "Sep26",
  batch_status: "PENDING_REVIEW",
  min_score: 0.55,
  operator_message: "Match each name on the left to the panel it is.",
  held_panels: [
    {
      raw_zone_text: "07lffender",
      raw_position: 7,
      count: 24,
      reasons: ["UNKNOWN_CHECKZONE"],
      signal: "name",
      signal_reason: "closest name",
      orientation_conflict: false,
      candidates: [
        candidate("LFFENDER", 6, 1, "same name, different number"),
        candidate("LCFENDER", 7, 0.875),
      ],
    },
    {
      raw_zone_text: "14roof",
      raw_position: 14,
      count: 24,
      reasons: ["UNKNOWN_CHECKZONE"],
      signal: "name",
      signal_reason: "closest name",
      orientation_conflict: false,
      candidates: [candidate("LCROOF", 11, 0.8)],
    },
    {
      raw_zone_text: "12lcpillar",
      raw_position: 12,
      count: 24,
      reasons: ["ZONE_NOT_VALID_FOR_MODEL"],
      signal: "name",
      signal_reason: "closest name",
      orientation_conflict: false,
      candidates: [],
    },
  ],
  live_panels: [
    {
      zone_code: "LFFENDER",
      point_no: 6,
      tolerance_group: "Vertical",
      mappable: true,
      already_used: false,
      note: null,
    },
    {
      zone_code: "LCFENDER",
      point_no: 7,
      tolerance_group: "Vertical",
      mappable: true,
      already_used: false,
      note: null,
    },
    {
      zone_code: "LCROOF",
      point_no: 11,
      tolerance_group: "Horizontal",
      mappable: true,
      already_used: false,
      note: null,
    },
    {
      zone_code: "LCPILLAR",
      point_no: 13,
      tolerance_group: "Vertical",
      mappable: true,
      already_used: false,
      note: null,
    },
    {
      zone_code: "14LFBOXSD",
      point_no: 46,
      tolerance_group: "Vertical",
      mappable: false,
      already_used: false,
      not_mappable_reason: "live at FTM but not a position on P703 DBL RANGER's own catalogue",
      note: "T58 owner lock 2026-10-05",
    },
  ],
};

const all: Decisions = {
  "07lffender": { kind: "match", zoneCode: "LFFENDER" },
  "14roof": { kind: "match", zoneCode: "LCROOF" },
  "12lcpillar": { kind: "match", zoneCode: "LCPILLAR" },
};
const decided = (over: Decisions = {}): Decisions => ({ ...all, ...over });

const confirmInput = (decisions: Decisions, over = {}) => ({
  view,
  decisions,
  retireZoneCodes: [] as string[],
  retireReason: "",
  decidedBy: "FTM quality owner",
  method: "walked the vehicle with the uploader",
  note: "September convention change",
  ...over,
});

// ------------------------------------------------- the disabled-confirm rule
test("confirm stays disabled until every held name has an answer", () => {
  assert.equal(canConfirm(view, {}), false);
  assert.equal(undecided(view, {}).length, 3);
  assert.match(confirmBlocker(view, {}) ?? "", /3 panel names have no answer yet/);

  const partial: Decisions = { "07lffender": { kind: "match", zoneCode: "LFFENDER" } };
  assert.equal(canConfirm(view, partial), false);
  assert.match(confirmBlocker(view, partial) ?? "", /2 panel names have no answer/);

  assert.equal(canConfirm(view, decided()), true);
  assert.equal(confirmBlocker(view, decided()), null);
});

test("leaving a name unmatched is an answer, but not every name may be unmatched", () => {
  const mostlyUnmatched = decided({
    "14roof": { kind: "unmatched" },
    "12lcpillar": { kind: "unmatched" },
  });
  assert.equal(canConfirm(view, mostlyUnmatched), true);
  assert.equal(matchedPairs(view, mostlyUnmatched).length, 1);

  const none: Decisions = {
    "07lffender": { kind: "unmatched" },
    "14roof": { kind: "unmatched" },
    "12lcpillar": { kind: "unmatched" },
  };
  assert.equal(canConfirm(view, none), false);
  assert.match(confirmBlocker(view, none) ?? "", /nothing to confirm/);
});

test("a screen with nothing held cannot be confirmed", () => {
  const empty: PanelMatch = { ...view, held_panels: [] };
  assert.equal(canConfirm(empty, {}), false);
  assert.match(confirmBlocker(empty, {}) ?? "", /No panel names are held/);
});

// --------------------------------------------- scores, suggestions, numbers
test("the suggestion is the server's first candidate and nothing is scored here", () => {
  assert.equal(suggestionFor(view.held_panels[0])?.zone_code, "LFFENDER");
  // No candidate is an answer, not a reason to reach for the nearest number.
  assert.equal(suggestionFor(view.held_panels[2]), null);
  assert.equal(
    scoreLabel(view.held_panels[0].candidates![0]),
    "100% name match - same name, different number",
  );
  assert.equal(scoreLabel(view.held_panels[1].candidates![0]), "80% name match - similar name");
});

test("the number is carried on every pair and never creates a candidate", () => {
  const pairs = matchedPairs(view, decided());
  assert.deepEqual(
    pairs.map((p) => [p.raw_zone_text, p.raw_position, p.zone_code]),
    [
      ["07lffender", 7, "LFFENDER"],
      ["14roof", 14, "LCROOF"],
      ["12lcpillar", 12, "LCPILLAR"],
    ],
  );
  // 14ROOF's own number is 14 and FTM's panel 14 is 14LFBOXSD. It is not
  // offered as a candidate and it is not even choosable -- D-86-3, which
  // T87 keeps whole (D-87-3): the family gate refuses it, so the shared 14
  // never gets a chance to order anything.
  assert.equal(
    view.held_panels[1].candidates!.some((c) => c.zone_code === "14LFBOXSD"),
    false,
  );
  assert.equal(
    mappablePanels(view).some((p) => p.zone_code === "14LFBOXSD"),
    false,
  );
});

test("a panel a panel map cannot reference is shown but not offered", () => {
  const offered = mappablePanels(view).map((p) => p.zone_code);
  assert.deepEqual(offered, ["LFFENDER", "LCFENDER", "LCROOF", "LCPILLAR"]);
  const hidden = view.live_panels.find((p) => !p.mappable);
  assert.match(hidden?.not_mappable_reason ?? "", /not a position on/);
});

test("a number-ordered suggestion says so, and the score still reads the name", () => {
  // T87 / D-87-2. The server sends the order; this file never re-sorts.
  const numbered: components["schemas"]["HeldPanelOut"] = {
    raw_zone_text: "08lffender",
    raw_position: 8,
    count: 24,
    reasons: ["UNKNOWN_CHECKZONE"],
    signal: "number",
    signal_reason: "the file's own number 8 is this panel's number",
    orientation_conflict: false,
    proposed_zone_code: "LRFENDER",
    candidates: [
      candidate("LRFENDER", 8, 0.875, "the file's own number is this panel's number"),
      candidate("LFFENDER", 6, 1, "same name, different number"),
    ],
  };
  const first = suggestionFor(numbered)!;
  assert.equal(first.zone_code, "LRFENDER");
  assert.equal(first.point_no, numbered.raw_position);
  // The percentage is still the NAME closeness, and the basis says what put
  // this one on top -- never presented as if the name had won it.
  assert.equal(scoreLabel(first), "88% name match - the file's own number is this panel's number");
  // The better name match is still offered, just not first.
  assert.equal(numbered.candidates![1].score, 1);
});

// ------------------------------------------------------------ the proposal
test("confirming builds one atomic ZONE proposal for the whole set", () => {
  const body = panelMatchProposal(confirmInput(decided()));
  assert.equal(body.kind, "ZONE");
  assert.equal(body.load_id, 123);
  const payload = body.payload as Record<string, unknown>;
  assert.equal(payload.plant_code, "FTM");
  assert.equal(payload.model_code, "P703 DBL RANGER");
  assert.equal((payload.matches as unknown[]).length, 3);
  assert.equal(payload.decided_by, "FTM quality owner");
  // No proof hash: a match set proves nothing and mints nothing.
  assert.equal("proof_hash" in payload, false);
  assert.equal("retire" in payload, false);
});

test("retiring a block needs a reason and may not name a panel just matched onto", () => {
  assert.throws(
    () =>
      panelMatchProposal(
        confirmInput(decided(), { retireZoneCodes: ["14LFBOXSD"], retireReason: "  " }),
      ),
    /Say why those panels are superseded/,
  );
  assert.throws(
    () =>
      panelMatchProposal(
        confirmInput(decided(), { retireZoneCodes: ["LFFENDER"], retireReason: "old block" }),
      ),
    /both matched onto and retired/,
  );
  const body = panelMatchProposal(
    confirmInput(decided(), {
      retireZoneCodes: ["14LFBOXSD"],
      retireReason: "FTM renamed its panels",
    }),
  );
  const retire = (body.payload as Record<string, { zone_codes: string[]; reason: string }>).retire;
  assert.deepEqual(retire.zone_codes, ["14LFBOXSD"]);
  assert.equal(retire.reason, "FTM renamed its panels");
});

test("two names onto one panel is refused before anything is sent", () => {
  const clash = decided({ "14roof": { kind: "match", zoneCode: "LFFENDER" } });
  assert.deepEqual(duplicateTargets(view, clash), ["LFFENDER"]);
  assert.throws(() => panelMatchProposal(confirmInput(clash)), /One panel is one panel/);
});

test("a half-answered set and a missing decider are both refused", () => {
  assert.throws(() => panelMatchProposal(confirmInput({})), /no answer yet/);
  assert.throws(
    () => panelMatchProposal(confirmInput(decided(), { decidedBy: "   " })),
    /decided_by/,
  );
});

// ------------------------------------------------- T88: signals and warnings
const t88Held = (over: Partial<components["schemas"]["HeldPanelOut"]> = {}) =>
  ({
    raw_zone_text: "14roof",
    raw_position: 14,
    count: 33,
    reasons: ["UNKNOWN_CHECKZONE"],
    orientations: ["Horizontal"],
    signal: "exhaustion",
    signal_reason:
      "every other horizontal panel of this model is taken, so this is the only one left (1 unmatched name(s), 1 unmatched panel(s))",
    orientation_conflict: false,
    proposed_zone_code: "RCROOF",
    filtered_out: [],
    candidates: [candidate("RCROOF", 27, 0.8)],
    ...over,
  }) as components["schemas"]["HeldPanelOut"];

test("T88 names the signal that argued for a pair, and flags exhaustion", () => {
  const exhausted = t88Held();
  assert.equal(signalLabel(exhausted), "Only one left");
  assert.equal(isExhaustion(exhausted), true);
  // The counts it rests on travel with it (G-88-3).
  assert.match(exhausted.signal_reason, /1 unmatched name\(s\), 1 unmatched panel\(s\)/);

  assert.equal(signalLabel(t88Held({ signal: "name" })), "Matched on the name");
  assert.equal(signalLabel(t88Held({ signal: "number" })), "Matched on the number");
  assert.equal(isExhaustion(t88Held({ signal: "number" })), false);
  // No proposal has no label to shout about.
  assert.equal(signalLabel(t88Held({ signal: "none" })), "");
});

test("T88 keeps orientation-filtered panels choosable (G-88-5)", () => {
  const held = t88Held({ filtered_out: ["LFFENDER", "LCFENDER"] });
  assert.deepEqual(filteredOut(held), ["LFFENDER", "LCFENDER"]);
  // The filter narrows the suggestion; the full list is what `mappablePanels`
  // returns and it is untouched by it.
  assert.deepEqual(
    mappablePanels(view).map((p) => p.zone_code),
    ["LFFENDER", "LCFENDER", "LCROOF", "LCPILLAR"],
  );
});

test("T88 sends the confirmed pairs back so the rest re-solves around them", () => {
  // D-88-2 / G-88-4: the pinned pairs are part of the next question.
  assert.deepEqual(confirmedPairs({}), []);
  assert.deepEqual(
    confirmedPairs({
      "07lffender": { kind: "match", zoneCode: "LCFENDER" },
      "14roof": { kind: "unmatched" },
      "12lcpillar": { kind: "match", zoneCode: "LCPILLAR" },
    }),
    ["07lffender=LCFENDER", "12lcpillar=LCPILLAR"],
  );
});

// =====================================================================
// T89 -- one picker (D-89-6) and the carried-over pre-fill (D-89-9)
// =====================================================================
const t89View: PanelMatch = {
  ...view,
  held_panels: [
    {
      ...view.held_panels[0],
      // The server's one list, in the server's order: suggestions first,
      // then the rest. LFFENDER is taken by another spelling of this very
      // file, so it is NOT here.
      choosable: ["LCFENDER", "LCPILLAR"],
      blocked: [
        {
          zone_code: "LFFENDER",
          point_no: 6,
          tolerance_group: "Vertical",
          taken_by: "06LFFENDER",
          label: "already matched to 06LFFENDER",
        },
      ],
    },
    {
      ...view.held_panels[1],
      choosable: ["LCROOF"],
      carried_over: {
        zone_code: "LCROOF",
        kind: "pending",
        reason:
          "You already matched '14ROOF' to LCROOF for P703 DBL RANGER on 2026-10-08, from batch 66219, and that pair is still waiting for an Admin to approve it.",
        source_raw_zone_text: "14ROOF",
        source_model_code: "P703 DBL RANGER",
        decided_at: "2026-10-08T14:37:00+07:00",
        load_id: 66219,
      },
    },
    { ...view.held_panels[2], choosable: ["LCPILLAR", "LCFENDER"] },
  ],
};

test("T89 the picker is the server's one list, and a taken panel is not in it", () => {
  // D-89-6: the screen stopped building a list of its own. The old one was
  // every mappable panel, which left a panel this file had already used
  // choosable -- two names onto one panel, which is the defect.
  assert.deepEqual(choosableFor(t89View.held_panels[0]), ["LCFENDER", "LCPILLAR"]);
  assert.equal(choosableFor(t89View.held_panels[0]).includes("LFFENDER"), false);
});

test("T89 a taken panel is still shown, and says which name took it", () => {
  const [taken] = blockedFor(t89View.held_panels[0]);
  assert.equal(taken.zone_code, "LFFENDER");
  assert.equal(taken.label, "already matched to 06LFFENDER");
});

test("T89 a carried-over row arrives pre-selected and labelled", () => {
  // D-89-9. The pre-fill counts as an answer for "is every row decided",
  // so the person can read it and press Confirm -- and it is still their
  // click that sends it.
  assert.deepEqual(carriedDecisions(t89View), {
    "14roof": { kind: "match", zoneCode: "LCROOF" },
  });
  assert.match(carryOverLabel(t89View.held_panels[1]) ?? "", /Carried over/);
  assert.equal(carryOverLabel(t89View.held_panels[0]), null);
  assert.deepEqual(
    undecided(t89View, {}).map((h) => h.raw_zone_text),
    ["07lffender", "12lcpillar"],
  );
});

test("T89 what the person says beats what was carried over", () => {
  const mine: Decisions = { "14roof": { kind: "unmatched" } };
  assert.deepEqual(
    matchedPairs(t89View, mine).map((p) => p.zone_code),
    [],
  );
  assert.deepEqual(
    matchedPairs(t89View, {}).map((p) => p.zone_code),
    ["LCROOF"],
  );
});

test("T89 a pre-fill is never sent as a pair the owner confirmed", () => {
  // It must not pin the solver: nobody has confirmed it yet.
  assert.deepEqual(confirmedPairs({}), []);
});

// ------------------------------------------------------------------ T90
// The walk is the identity, the name is only a label.

type WalkRow = components["schemas"]["WalkRowOut"];

const walkRow = (raw_zone_text: string, over: Partial<WalkRow> = {}): WalkRow => ({
  raw_zone_text,
  panel_group: "FENDER",
  side: "L",
  specificity: "rough",
  binding: "alias",
  binding_reason: null,
  attention: "red",
  reason: "this is the first time this walk has been seen",
  rule: "group_ordinal",
  proposed_zone_code: "LFFENDER",
  rule_group_ordinal_zone_code: "LFFENDER",
  rule_walk_number_zone_code: null,
  side_hint_checked: true,
  prefilled_zone_code: null,
  ...over,
});

const withWalk = (rows: Record<string, Partial<WalkRow>>, over = {}): PanelMatch => ({
  ...view,
  held_panels: view.held_panels.map((held) => ({
    ...held,
    walk: walkRow(held.raw_zone_text, rows[held.raw_zone_text] ?? {}),
  })),
  walk: {
    model_code: view.model_code,
    fingerprint: "FENDER|ROOF|PILLAR",
    fingerprint_display: "F R P",
    canonical_fingerprint: "FENDER|ROOF|PILLAR",
    canonical_fingerprint_display: "F R P",
    group_counts: [
      { panel_group: "FENDER", file: 1, canonical: 1 },
      { panel_group: "PILLAR", file: 1, canonical: 1 },
      { panel_group: "ROOF", file: 1, canonical: 1 },
    ],
    multiset_matches: true,
    walk_order_verified: true,
    walk_order_reason: "the leading numbers ascend within every vehicle (1 vehicle, 1 pass)",
    rule_group_ordinal_available: true,
    rule_group_ordinal_reason: "the file walks the canonical groups",
    rule_walk_number_available: false,
    rule_walk_number_reason: "does not apply: the numbering is not the canonical walk",
    disagreements: [],
    fingerprint_moved: false,
    confirmed_before: false,
    confirmed_source_file: null,
    confirmed_at: null,
    confirmed_load_id: null,
    yellow_count: 0,
    red_count: 3,
    operator_message: "This walk has not been confirmed before, so every name is open.",
    rows: view.held_panels.map((held) =>
      walkRow(held.raw_zone_text, rows[held.raw_zone_text] ?? {}),
    ),
    ...over,
  },
});

test("T90 a walk's colour and reason come from the server and there is no green", () => {
  const first = withWalk({});
  assert.deepEqual(
    first.held_panels.map((held) => attentionOf(held)),
    ["red", "red", "red"],
  );
  assert.equal(attentionLabel(first.held_panels[0].walk!), "Needs attention");
  assert.equal(
    attentionLabel(walkRow("x", { attention: "yellow" })),
    "Looks right - still confirm",
  );
  // Nothing is pre-filled on a first sight: yellow is what brings a pre-fill.
  assert.deepEqual(walkPrefills(first), {});
  assert.equal(bulkAcceptSummary(first), null);
});

test("T90 bulk accept confirms the yellow rows only and reports both counts", () => {
  const mixed = withWalk(
    {
      "07lffender": {
        attention: "yellow",
        prefilled_zone_code: "LFFENDER",
        proposed_zone_code: "LFFENDER",
      },
      "14roof": {
        attention: "yellow",
        panel_group: "ROOF",
        side: null,
        side_hint_checked: false,
        prefilled_zone_code: "LCROOF",
        proposed_zone_code: "LCROOF",
      },
    },
    { yellow_count: 2, red_count: 1 },
  );
  assert.deepEqual(
    yellowRows(mixed).map((held) => held.raw_zone_text),
    ["07lffender", "14roof"],
  );
  assert.deepEqual(
    redRows(mixed).map((held) => held.raw_zone_text),
    ["12lcpillar"],
  );
  const summary = bulkAcceptSummary(mixed)!;
  assert.equal(summary.yellow, 2);
  assert.equal(summary.red, 1);
  assert.match(summary.words, /2 that look right - 1 still need/);

  // D-90-14: the red row is never swept along.
  const accepted = acceptAllYellow(mixed);
  assert.deepEqual(Object.keys(accepted).sort(), ["07lffender", "14roof"]);
  assert.equal(accepted["12lcpillar"], undefined);
  // And the set is still not confirmable until the red is answered.
  assert.equal(canConfirm(mixed, accepted), false);
  assert.match(confirmBlocker(mixed, accepted) ?? "", /1 panel name has no answer/);
});

test("T90 a yellow row arrives pre-filled and a red one never does", () => {
  const mixed = withWalk({
    "07lffender": { attention: "yellow", prefilled_zone_code: "LFFENDER" },
    "14roof": { attention: "red", prefilled_zone_code: "LCROOF" },
  });
  assert.deepEqual(walkPrefills(mixed), {
    "07lffender": { kind: "match", zoneCode: "LFFENDER" },
  });
  // Merged UNDER what the person said, and never sent as a confirmed pair.
  const mine: Decisions = { "07lffender": { kind: "unmatched" } };
  assert.deepEqual(effectiveDecisions(mixed, mine)["07lffender"], { kind: "unmatched" });
  assert.deepEqual(confirmedPairs({}), []);
});

test("T90 when the two rules disagree both answers are shown and neither is filled in", () => {
  const row = walkRow("07lffender", {
    proposed_zone_code: null,
    rule: "none",
    rule_group_ordinal_zone_code: "LFFENDER",
    rule_walk_number_zone_code: "LCFENDER",
    reason: "the two rules disagree",
  });
  assert.deepEqual(ruleDisagreement(row), {
    groupOrdinal: "LFFENDER",
    walkNumber: "LCFENDER",
  });
  // An agreeing row has nothing to show.
  assert.equal(
    ruleDisagreement(
      walkRow("x", {
        rule_group_ordinal_zone_code: "LFFENDER",
        rule_walk_number_zone_code: "LFFENDER",
      }),
    ),
    null,
  );
  assert.equal(ruleDisagreement(walkRow("x")), null);
});

test("T90 a rough name never goes into matches and the walk carries it instead", () => {
  const sheet = withWalk({
    "07lffender": { specificity: "rough", proposed_zone_code: "LFFENDER" },
    "14roof": { specificity: "rough", proposed_zone_code: "LCROOF", panel_group: "ROOF" },
    "12lcpillar": {
      specificity: "specific",
      proposed_zone_code: "LCPILLAR",
      panel_group: "PILLAR",
    },
  });
  assert.deepEqual([...roughSpellings(sheet)].sort(), ["07lffender", "14roof"]);

  const proposal = panelMatchProposal(confirmInput(decided(), { view: sheet }));
  const payload = proposal.payload as {
    matches: { raw_zone_text: string }[];
    walk: { fingerprint: string; pairs: { raw_zone_text: string; specificity: string }[] };
  };
  // D-90-3: only the specific name becomes a permanent alias.
  assert.deepEqual(
    payload.matches.map((m) => m.raw_zone_text),
    ["12lcpillar"],
  );
  // D-90-11: the whole walk, rough and specific, rides on the batch.
  assert.equal(payload.walk.fingerprint, "FENDER|ROOF|PILLAR");
  assert.deepEqual(
    payload.walk.pairs.map((p) => [p.raw_zone_text, p.specificity]),
    [
      ["07lffender", "rough"],
      ["14roof", "rough"],
      ["12lcpillar", "specific"],
    ],
  );
});

test("T91 a specific name the plant calls another panel stays off matches", () => {
  // D-91-2 / D-91-3: the row looks perfectly specific on THIS sheet, and
  // the server has still said `batch`, because another sheet of this plant
  // confirmed the same spelling as a different panel. Specificity alone
  // cannot see that, so the screen follows `binding` and not `specificity`.
  const sheet = withWalk({
    "07lffender": { specificity: "rough", proposed_zone_code: "LFFENDER" },
    "14roof": {
      specificity: "specific",
      proposed_zone_code: "LCROOF",
      panel_group: "ROOF",
      binding: "alias",
    },
    "12lcpillar": {
      specificity: "specific",
      proposed_zone_code: "LCPILLAR",
      panel_group: "PILLAR",
      binding: "batch",
      binding_reason: "this plant has already confirmed 12lcpillar as RCPILLAR on 08 Aug.xlsx",
    },
  });
  assert.deepEqual([...perBatchSpellings(sheet)].sort(), ["07lffender", "12lcpillar"]);
  assert.equal(
    bindingReasons(sheet).get("12lcpillar"),
    "this plant has already confirmed 12lcpillar as RCPILLAR on 08 Aug.xlsx",
  );
  // The specific name nobody has contradicted is still learned forever;
  // the contradicted one travels on the batch only.
  const proposal = panelMatchProposal(confirmInput(decided(), { view: sheet }));
  const payload = proposal.payload as {
    matches: { raw_zone_text: string }[];
    walk: { pairs: { raw_zone_text: string }[] };
  };
  assert.deepEqual(
    payload.matches.map((m) => m.raw_zone_text),
    ["14roof"],
  );
  assert.deepEqual(
    payload.walk.pairs.map((p) => p.raw_zone_text),
    ["07lffender", "14roof", "12lcpillar"],
  );
});

test("T90 a sheet with no walk block still proposes exactly as it did before", () => {
  const proposal = panelMatchProposal(confirmInput(decided()));
  const payload = proposal.payload as { matches: unknown[]; walk?: unknown };
  assert.equal(payload.matches.length, 3);
  assert.equal(payload.walk, undefined);
  assert.equal(walkMatch(view), null);
  assert.equal(attentionOf(view.held_panels[0]), null);
});
