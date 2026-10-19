import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { cleanReview } from "../fixtures";
import { fileHash, workbookFixture } from "../workbook-fixtures";

/**
 * T86 -- the held-panel group reaches the guided match screen, and the
 * screen proposes one atomic ZONE set.
 *
 * What this spec is actually pinning:
 *
 * - a panel name that cannot be taught one row at a time offers "Match the
 *   panel list" instead of a sentence promising a pick that is not there;
 * - the screen shows each file name's own number and labels it as not being
 *   the match, and FTM's panel 14 (`14LFBOXSD`) is nowhere in `14ROOF`'s
 *   options even though they share the number (D-86-3);
 * - Confirm stays disabled until every held name is answered;
 * - Confirm posts **one** proposal carrying every pair, and nothing is
 *   applied -- an Admin approves it (D-86-4).
 */

type PanelMatch = components["schemas"]["PanelMatchOut"];
type Held = components["schemas"]["HeldLabelGroup"];

const MODEL = "P703 DBL RANGER";

const heldPanels: Held[] = [
  {
    reason: "ZONE_NOT_VALID_FOR_MODEL",
    column: "checkzone",
    raw_value: "06LFFENDER",
    count: 24,
    teachable_kind: null,
    candidates: [],
    display_group: "zone",
    operator_message:
      'The panel name "06LFFENDER" is not on this model\'s panel list at FTM, and we cannot' +
      ' offer a single panel to pick for it here. Use "Match the panel list" on this tab to' +
      " match this file's panel names to FTM's own panels, name by name.",
    model_code: MODEL,
  },
  {
    reason: "UNKNOWN_CHECKZONE",
    column: "checkzone",
    raw_value: "14ROOF",
    count: 24,
    teachable_kind: null,
    candidates: [],
    display_group: "zone",
    operator_message: "We cannot offer a single panel to pick for 14ROOF here.",
    model_code: MODEL,
  },
];

const panelMatch: PanelMatch = {
  plant_code: "FTM",
  model_code: MODEL,
  load_id: 123,
  source_sheet: "Sep26",
  batch_status: "PENDING_REVIEW",
  min_score: 0.55,
  // T88 / G-88-2: shown BEFORE any exhaustion claim, naming both numbers.
  catalogue_warning:
    "FTM's list for P703 DBL RANGER holds 64 live panels and this file walks 32. The catalogue" +
    " may be carrying the same physical panel under two names.",
  orientation_conflicts: [],
  operator_message:
    "This file writes panel names this model's list at FTM does not have. Match each name on" +
    " the left to the panel it is, from FTM's own list on the right.",
  held_panels: [
    {
      raw_zone_text: "06LFFENDER",
      raw_position: 6,
      count: 24,
      reasons: ["ZONE_NOT_VALID_FOR_MODEL"],
      // T88: the server says which signal argued for the pair, in words.
      signal: "number",
      signal_reason: "the file's own number 6 is this panel's number",
      orientation_conflict: false,
      proposed_zone_code: "LFFENDER",
      orientations: ["Vertical"],
      // T89 (D-89-6): THE list, from the server, in the server's order.
      // `14LFBOXSD` is not in it -- it is live at FTM and not a position on
      // the model's own catalogue, so the approval path would refuse it.
      choosable: ["LFFENDER", "LCFENDER"],
      blocked: [],
      candidates: [
        {
          zone_code: "LFFENDER",
          point_no: 6,
          tolerance_group: "Vertical",
          score: 1,
          // T87 / D-87-2: this panel's walk number is the file's own 6, so
          // the server listed it first and says the number ordered it.
          basis: "the file's own number is this panel's number",
        },
        {
          zone_code: "LCFENDER",
          point_no: 7,
          tolerance_group: "Vertical",
          score: 0.875,
          basis: "similar name",
        },
      ],
    },
    {
      raw_zone_text: "14ROOF",
      raw_position: 14,
      count: 24,
      reasons: ["UNKNOWN_CHECKZONE"],
      // T88: the exhaustion case, with the counts it rests on (G-88-3).
      signal: "exhaustion",
      signal_reason:
        "every other horizontal panel of this model is taken, so this is the only one left" +
        " (1 unmatched name(s), 1 unmatched panel(s))",
      orientation_conflict: false,
      proposed_zone_code: "LCROOF",
      orientations: ["Horizontal"],
      choosable: ["LCROOF"],
      // D-89-6: a panel this file already used is shown, disabled, named.
      blocked: [
        {
          zone_code: "RCROOF",
          point_no: 27,
          tolerance_group: "Horizontal",
          taken_by: "11ROOF",
          label: "already matched to 11ROOF",
        },
      ],
      candidates: [
        {
          zone_code: "LCROOF",
          point_no: 11,
          tolerance_group: "Horizontal",
          score: 0.8,
          basis: "similar name",
        },
      ],
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
      // D-87-3 in the browser: this panel carries the very number 14ROOF
      // writes, and it is still neither a candidate nor choosable.
      zone_code: "14LFBOXSD",
      point_no: 14,
      tolerance_group: "Vertical",
      already_used: false,
      mappable: false,
      not_mappable_reason:
        "This panel is live at FTM but is not a position on P703 DBL RANGER's own catalogue.",
      note: "T58 owner lock 2026-10-05",
    },
  ],
};

const sheet: components["schemas"]["WorksheetSheetOut"] = {
  load_id: 123,
  sheet: "Sep26",
  status: "PENDING_REVIEW",
  state: "ready",
  commit_blockers: [],
  rows_ready: 340,
  rows_loaded: 0,
  rows_held: 48,
  rows_already_in_history: 0,
  rows_need_confirmation: 0,
  rows: [],
  held: heldPanels,
  extra_columns: [],
  missing_optional: [],
  hole_rows: [],
  plant_texts: [],
  vehicle_count: 1,
  short_vehicles: [],
  operator_message: "340 readings ready to add, 48 held out.",
};

const worksheet: components["schemas"]["WorksheetOut"] = {
  plant_code: "FTM",
  file_hash: fileHash,
  source_file: "09 Sep'26 CF data FTM.xlsx",
  sheets: [sheet],
  plant_question: null,
  extra_columns: [],
  missing_optional: [],
  missing_optional_message: null,
  ready_sheet_count: 1,
  rows_ready: 340,
  rows_held: 48,
  rows_already_in_history: 0,
  rows_need_confirmation: 0,
  summary_message: sheet.operator_message,
  checklist: [],
  load_button_label: "Yes, load these rows",
};

const book = {
  ...workbookFixture,
  plant_code: "FTM",
  source_file: worksheet.source_file,
  measured_date_min: "2026-09-01",
  measured_date_max: "2026-09-25",
  measured_dates_span_months: false,
};

async function setup(
  page: Page,
  role = "engineer",
  view: components["schemas"]["PanelMatchOut"] = panelMatch,
) {
  await mockHistory(page, role);
  const proposals: Record<string, unknown>[] = [];
  let panelMatchReads = 0;
  await page.route("**/api/v1/plants/FTM/workbooks?*", (route) =>
    route.fulfill({
      json: {
        plant_code: "FTM",
        plant_is_active: true,
        inbox: "all",
        uploaded_month: null,
        items: [book],
        page: { offset: 0, limit: 200, total: 1, returned: 1 },
      },
    }),
  );
  await page.route(`**/workbooks/${fileHash}`, (route) =>
    route.fulfill({
      json: { workbook: book, profiles: [], possible_replacements: [], acknowledgements: [] },
    }),
  );
  await page.route(`**/workbooks/${fileHash}/worksheet`, (route) =>
    route.fulfill({ json: worksheet }),
  );
  await page.route("**/api/v1/batches/123", (route) =>
    route.fulfill({ json: { ...cleanReview, held_labels: heldPanels } }),
  );
  await page.route("**/api/v1/mappings/panel-match?*", (route) => {
    panelMatchReads++;
    return route.fulfill({ json: view });
  });
  await page.route("**/api/v1/mappings/proposals", (route) => {
    const body = route.request().postDataJSON();
    proposals.push(body);
    return route.fulfill({
      status: 201,
      json: {
        id: "panel-set-1",
        kind: body.kind,
        payload: body.payload,
        load_id: body.load_id,
        status: "PROPOSED",
        similarity: null,
        proposed_by: "dev",
        decided_by: null,
        created_at: "2026-10-07T12:00:00Z",
        decided_at: null,
      },
    });
  });
  await page.goto(`/plant/ftm?file=${fileHash}`);
  return { proposals, reads: () => panelMatchReads };
}

test("T86 a held panel name reaches the guided match screen instead of a missing pick", async ({
  page,
}) => {
  await setup(page);
  const review = page.getByRole("dialog").first();
  // The copy stops telling the user to pick a panel, and names the control
  // that is actually there.
  await expect(review.getByText(/we cannot offer a single panel to pick/i)).toHaveCount(2);
  await expect(review.getByText("Pick the panel it is from that list")).toHaveCount(0);
  const open = review.getByRole("button", { name: "Match the panel list" }).first();
  await expect(open).toBeVisible();
  await open.click();

  const match = page.getByRole("dialog", { name: "Match the panel list" });
  await expect(match.getByText("Match each name on the left")).toBeVisible();
  await expect(match.getByRole("listitem")).toHaveCount(2);

  // Each name shows its own number, said out loud not to be the match.
  await expect(
    match.getByText("Number 6 in the file - only orders the suggestions, never adds one"),
  ).toBeVisible();
  await expect(
    match.getByText("Number 14 in the file - only orders the suggestions, never adds one"),
  ).toBeVisible();

  // T88: the proposal names the signal that argued for it, keeps the name
  // score beside it, and still asks to be checked.
  await expect(
    match.getByText(
      /Matched on the number: LFFENDER \(100% name match - the file's own number is this panel's number\)/,
    ),
  ).toBeVisible();
  await expect(match.getByText(/Only one left/)).toBeVisible();
  await expect(match.getByText(/Check it yourself before you confirm/).first()).toBeVisible();

  // 14ROOF and FTM's panel 14 share a number and nothing else: 14LFBOXSD
  // sits at walk number 14 in this fixture and is still not an option for
  // it, and not an option anywhere (D-86-3, kept whole by D-87-3).
  //
  // T89 (D-89-6): the options ARE the server's one list -- the same array
  // the per-row picker in the held-label list is handed -- so the
  // orientation filter and the already-used exclusion apply to the picker
  // too, and a panel this file has already used is last and disabled.
  const roof = match.getByLabel('Which panel is "14ROOF"?');
  await expect(roof.locator("option")).toHaveText([
    "Choose a panel",
    "LCROOF - 80% name match - similar name (number 11)",
    "RCROOF - already matched to 11ROOF",
    "Leave this name unmatched",
  ]);
  await expect(roof.locator("option[disabled]")).toHaveText(["RCROOF - already matched to 11ROOF"]);

  await page.screenshot({
    path: "test-results/screenshots/T86-panel-match-desktop.png",
    animations: "disabled",
  });
});

test("T86 confirm is disabled until every name is answered, then posts one set", async ({
  page,
}) => {
  const state = await setup(page);
  await page
    .getByRole("dialog")
    .first()
    .getByRole("button", { name: "Match the panel list" })
    .first()
    .click();
  const match = page.getByRole("dialog", { name: "Match the panel list" });
  const confirm = match.getByRole("button", { name: "Confirm this panel set" });

  await expect(confirm).toBeDisabled();
  await expect(match.getByText("2 panel names have no answer yet")).toBeVisible();

  await match.getByLabel('Which panel is "06LFFENDER"?').selectOption("LFFENDER");
  await expect(confirm).toBeDisabled();
  await expect(match.getByText("1 panel name has no answer yet")).toBeVisible();

  // An explicit "unmatched" is an answer, and says what happens to the rows.
  await match.getByLabel('Which panel is "14ROOF"?').selectOption("__unmatched__");
  await expect(match.getByText("Left unmatched. These 24 readings stay held.")).toBeVisible();

  // Who decided is typed by a person, never taken from the signed-in user.
  await match.getByLabel("Who decided", { exact: true }).fill("FTM quality owner");
  await match
    .getByLabel("How they decided", { exact: true })
    .fill("walked the vehicle with the uploader");
  await match.getByLabel("Note", { exact: true }).fill("September convention change");

  // The owner names the superseded block, and then why.
  await match.getByLabel("Panels this set supersedes").selectOption(["14LFBOXSD"]);
  await match.getByLabel("Why are they superseded?").fill("FTM renamed its panels");

  await expect(confirm).toBeEnabled();
  await confirm.click();

  await expect(match.getByText("Panel set proposed")).toBeVisible();
  // One proposal, one set, nothing applied.
  expect(state.proposals).toHaveLength(1);
  const [body] = state.proposals;
  expect(body.kind).toBe("ZONE");
  expect(body.load_id).toBe(123);
  const payload = body.payload as Record<string, unknown>;
  expect(payload.matches).toEqual([
    { raw_zone_text: "06LFFENDER", raw_position: 6, zone_code: "LFFENDER" },
  ]);
  expect(payload.retire).toEqual({
    zone_codes: ["14LFBOXSD"],
    reason: "FTM renamed its panels",
  });
  expect(payload.decided_by).toBe("FTM quality owner");
  expect("proof_hash" in payload).toBe(false);
  await expect(confirm).toBeDisabled();

  await page.screenshot({
    path: "test-results/screenshots/T86-panel-match-proposed-desktop.png",
    animations: "disabled",
  });
});

test("T86 the screen refuses two names onto one panel before it posts", async ({ page }) => {
  // T89 (D-89-6): the picker is the server's orientation-filtered list, so
  // a Horizontal name can no longer be pointed at a Vertical panel at all
  // -- the clash has to be built where it can really happen, between two
  // names of the SAME orientation. This view is the fixture with 14ROOF
  // written as Vertical, which is how a file produces two names that can
  // both reach LFFENDER.
  const sameOrientation: components["schemas"]["PanelMatchOut"] = {
    ...panelMatch,
    held_panels: panelMatch.held_panels.map((held) =>
      held.raw_zone_text === "14ROOF"
        ? {
            ...held,
            orientations: ["Vertical"],
            choosable: ["LFFENDER", "LCFENDER"],
            blocked: [],
          }
        : held,
    ),
  };
  const state = await setup(page, "engineer", sameOrientation);
  await page
    .getByRole("dialog")
    .first()
    .getByRole("button", { name: "Match the panel list" })
    .first()
    .click();
  const match = page.getByRole("dialog", { name: "Match the panel list" });
  await match.getByLabel('Which panel is "06LFFENDER"?').selectOption("LFFENDER");
  await match.getByLabel('Which panel is "14ROOF"?').selectOption("LFFENDER");
  await match.getByLabel("Who decided", { exact: true }).fill("FTM quality owner");
  await match.getByLabel("How they decided", { exact: true }).fill("walked the vehicle");
  await match.getByLabel("Note", { exact: true }).fill("clash");
  await match.getByRole("button", { name: "Confirm this panel set" }).click();
  await expect(match.getByText(/One panel is one panel/)).toBeVisible();
  expect(state.proposals).toHaveLength(0);
});

test("T88 shows the catalogue warning and names the signal behind each pair", async ({ page }) => {
  await setup(page);
  await page
    .getByRole("dialog")
    .first()
    .getByRole("button", { name: "Match the panel list" })
    .first()
    .click();
  const match = page.getByRole("dialog", { name: "Match the panel list" });

  // G-88-2: the 64-vs-32 warning, naming both numbers, before anything else.
  const warning = match.getByRole("alert").filter({ hasText: "64 live panels" });
  await expect(warning).toBeVisible();
  await expect(warning).toContainText("this file walks 32");

  // D-88-3: every proposal says which signal argued for it.
  const roof = match.getByRole("listitem").filter({ hasText: "14ROOF" });
  await expect(roof.locator('[data-signal="exhaustion"]')).toBeVisible();
  await expect(roof).toContainText("Only one left");
  // G-88-3: in its own words, with the counts it rests on.
  await expect(roof).toContainText("1 unmatched name(s), 1 unmatched panel(s)");
  await expect(roof).toContainText("check this one especially");

  const fender = match.getByRole("listitem").filter({ hasText: "06LFFENDER" });
  await expect(fender.locator('[data-signal="number"]')).toBeVisible();
  await expect(fender).toContainText("Matched on the number");

  await page.screenshot({
    path: "test-results/screenshots/T88-panel-match-signals-desktop.png",
    animations: "disabled",
  });
});

test("T89 a carried-over decision arrives pre-selected, labelled, and still confirmed by a person", async ({
  page,
}) => {
  // D-89-9. The pair was decided and is still waiting for an Admin, so the
  // row comes back -- and it comes back filled in, saying where the answer
  // came from. Nothing is applied until the person presses Confirm.
  const carried: components["schemas"]["PanelMatchOut"] = {
    ...panelMatch,
    held_panels: panelMatch.held_panels.map((held) =>
      held.raw_zone_text === "06LFFENDER"
        ? {
            ...held,
            carried_over: {
              zone_code: "LCFENDER",
              kind: "pending",
              reason:
                "You already matched '06LFFENDER' to LCFENDER for P703 DBL RANGER on 2026-10-08, from batch 66219, and that pair is still waiting for an Admin to approve it.",
              source_raw_zone_text: "06LFFENDER",
              source_model_code: "P703 DBL RANGER",
              decided_at: "2026-10-08T14:37:00+07:00",
              load_id: 66219,
            },
          }
        : held,
    ),
  };
  const state = await setup(page, "engineer", carried);
  await page
    .getByRole("dialog")
    .first()
    .getByRole("button", { name: "Match the panel list" })
    .first()
    .click();
  const match = page.getByRole("dialog", { name: "Match the panel list" });

  await expect(match.getByText(/Carried over from an earlier decision/)).toBeVisible();
  await expect(match.getByText(/from batch 66219/)).toBeVisible();
  // Pre-selected: the person has touched nothing.
  await expect(match.getByLabel('Which panel is "06LFFENDER"?')).toHaveValue("LCFENDER");
  // And it is still their click that sends it: the other row is unanswered,
  // so Confirm is disabled until they answer that one too.
  const confirm = match.getByRole("button", { name: "Confirm this panel set" });
  await expect(confirm).toBeDisabled();
  await match.getByLabel('Which panel is "14ROOF"?').selectOption("LCROOF");
  await match.getByLabel("Who decided", { exact: true }).fill("FTM quality owner");
  await match.getByLabel("How they decided", { exact: true }).fill("walked the vehicle");
  await match.getByLabel("Note", { exact: true }).fill("carried over, checked");
  await expect(confirm).toBeEnabled();
  expect(state.proposals).toHaveLength(0);
  await confirm.click();
  // The carried pair is in the set the person confirmed -- not before.
  await expect.poll(() => state.proposals.length).toBe(1);
  expect(state.proposals[0]).toMatchObject({
    kind: "ZONE",
    payload: {
      matches: [
        { raw_zone_text: "06LFFENDER", zone_code: "LCFENDER" },
        { raw_zone_text: "14ROOF", zone_code: "LCROOF" },
      ],
    },
  });
  await page.screenshot({
    path: "test-results/screenshots/T89-panel-match-carried-over-desktop.png",
    animations: "disabled",
  });
});

/**
 * T90 -- the walk is the identity, the name is only a label.
 *
 * What these pin, in the browser:
 *
 * - the **whole-set view stays** (D-90-9): the group fingerprint, the file's
 *   against the model's own, and each rule with its reason in plain words;
 * - the control is **inline** (D-90-9): the colour, the reason and an
 *   answer button live in the row being reviewed;
 * - **bulk accept confirms the yellow rows only** and reports both counts
 *   (D-90-14) -- the red stays open and Confirm stays disabled;
 * - a **rough** name never reaches `matches`; the whole walk rides on the
 *   batch instead (D-90-3 / D-90-11);
 * - when the two rules **disagree**, both answers are shown, neither is
 *   filled in, and no row of the set is yellow (D-90-2).
 */

type WalkRow = components["schemas"]["WalkRowOut"];

const walkRowFor = (raw_zone_text: string, over: Partial<WalkRow>): WalkRow => ({
  raw_zone_text,
  panel_group: null,
  side: null,
  specificity: "rough",
  binding: "alias",
  binding_reason: null,
  attention: "red",
  reason: "this is the first time this walk has been seen for this plant and model",
  rule: "group_ordinal",
  proposed_zone_code: null,
  rule_group_ordinal_zone_code: null,
  rule_walk_number_zone_code: null,
  side_hint_checked: false,
  prefilled_zone_code: null,
  ...over,
});

const fenderRow = walkRowFor("06LFFENDER", {
  panel_group: "FENDER",
  side: "L",
  specificity: "specific",
  attention: "yellow",
  reason:
    "the groups line up with the canonical groups, the side hint agrees, and it is what was" +
    " confirmed last under this same walk. Looks right -- still confirm it",
  proposed_zone_code: "LFFENDER",
  rule_group_ordinal_zone_code: "LFFENDER",
  side_hint_checked: true,
  prefilled_zone_code: "LFFENDER",
});

const roofRow = walkRowFor("14ROOF", {
  panel_group: "ROOF",
  specificity: "rough",
  attention: "red",
  reason:
    "nothing in this group carries a side, so there is no left-against-right check to make" +
    " -- and this is the first time this walk has been seen",
  proposed_zone_code: "LCROOF",
  rule_group_ordinal_zone_code: "LCROOF",
});

const walkBlock = (
  rows: WalkRow[],
  over: Partial<components["schemas"]["WalkMatchOut"]> = {},
): components["schemas"]["WalkMatchOut"] => ({
  model_code: MODEL,
  fingerprint: "FENDER|ROOF",
  fingerprint_display: "F R",
  canonical_fingerprint: "FENDER|ROOF",
  canonical_fingerprint_display: "F R",
  group_counts: [
    { panel_group: "FENDER", file: 1, canonical: 1 },
    { panel_group: "ROOF", file: 1, canonical: 1 },
  ],
  multiset_matches: true,
  walk_order_verified: true,
  walk_order_reason:
    "the leading numbers ascend within every vehicle (19 vehicles, 21 passes checked)",
  rule_group_ordinal_available: true,
  rule_group_ordinal_reason:
    "the file walks the canonical groups in the canonical numbers (32 names, 32 canonical points)",
  rule_walk_number_available: false,
  rule_walk_number_reason:
    "does not apply: by number '12LCPILLAR' would be LCRDOOR, which is a DOOR and not a PILLAR",
  disagreements: [],
  fingerprint_moved: false,
  confirmed_before: true,
  confirmed_source_file: "09 Sep'26 CF data FTM.xlsx",
  confirmed_at: "2026-10-09T03:00:00Z",
  confirmed_load_id: 70201,
  yellow_count: 1,
  red_count: 1,
  operator_message:
    "Same walk as 09 Sep'26 CF data FTM.xlsx, confirmed 2026-10-09. 1 of 2 name(s) match what" +
    " was confirmed then -- accept all 1 in one click. 1 still need you.",
  rows,
  ...over,
});

const walkView: PanelMatch = {
  ...panelMatch,
  held_panels: [
    { ...panelMatch.held_panels[0], walk: fenderRow },
    { ...panelMatch.held_panels[1], walk: roofRow },
  ],
  walk: walkBlock([fenderRow, roofRow]),
};

async function openMatch(page: Page, view: PanelMatch) {
  const result = await setup(page, "engineer", view);
  const review = page.getByRole("dialog").first();
  await review.getByRole("button", { name: "Match the panel list" }).first().click();
  return { ...result, match: page.getByRole("dialog", { name: "Match the panel list" }) };
}

test("T90 the whole-set view names the walk, both rules and both counts", async ({ page }) => {
  const { match } = await openMatch(page, walkView);
  const walk = match.getByRole("region", { name: "The walk this file describes" });
  await expect(walk).toBeVisible();

  // D-90-4: the fingerprint is the groups, and both are shown side by side.
  await expect(walk.getByText("F R", { exact: true }).first()).toBeVisible();
  // D-90-7: the precondition is reported, not assumed.
  await expect(
    walk.getByText(/the leading numbers ascend within every vehicle \(19 vehicles/),
  ).toBeVisible();
  // D-90-1: each rule says whether it applies and why.
  await expect(walk.getByText(/By family and position:\s*applies/)).toBeVisible();
  await expect(walk.getByText(/By the file's own number:\s*does not apply/)).toBeVisible();
  await expect(walk.getByText(/would be LCRDOOR, which is a DOOR and not a PILLAR/)).toBeVisible();
  // D-90-6: both counts, and no green anywhere.
  await expect(walk.getByText(/1 look right, 1 need attention/)).toBeVisible();
  await expect(walk.getByText(/no "confirmed by itself"/)).toBeVisible();
});

test("T90 the control is inline: the colour, the reason and the answer are in the row", async ({
  page,
}) => {
  const { match } = await openMatch(page, walkView);
  const fender = match.locator('li[data-raw="06LFFENDER"]');
  const roof = match.locator('li[data-raw="14ROOF"]');

  await expect(fender).toHaveAttribute("data-attention", "yellow");
  await expect(roof).toHaveAttribute("data-attention", "red");
  await expect(fender.getByText("Looks right - still confirm").first()).toBeVisible();
  await expect(roof.getByText("Needs attention").first()).toBeVisible();

  // D-90-12: the group with nothing to cross-check says so, in its own words.
  await expect(roof.getByText(/no left-against-right check to make/)).toBeVisible();
  // D-90-3: a rough name says out loud that it is not learned forever.
  await expect(roof).toHaveAttribute("data-specificity", "rough");
  await expect(roof.getByText(/applies to this upload; it is not learned forever/)).toBeVisible();

  // D-90-5: the yellow row arrives pre-filled and is still not applied.
  await expect(fender.getByLabel(/Which panel is "06LFFENDER"\?/)).toHaveValue("LFFENDER");
  // D-90-9: the red row's own answer is one click away, in the row.
  const inline = roof.getByRole("button", { name: "It is LCROOF" });
  await expect(inline).toBeVisible();
  await inline.click();
  await expect(roof.getByLabel(/Which panel is "14ROOF"\?/)).toHaveValue("LCROOF");
});

test("T90 bulk accept confirms the yellow rows only and leaves the red open", async ({ page }) => {
  const twoRed = walkRowFor("14ROOF", { ...roofRow, attention: "red" });
  const { match, proposals } = await openMatch(page, {
    ...walkView,
    held_panels: [
      { ...panelMatch.held_panels[0], walk: { ...fenderRow, prefilled_zone_code: null } },
      { ...panelMatch.held_panels[1], walk: twoRed },
    ],
    walk: walkBlock([{ ...fenderRow, prefilled_zone_code: null }, twoRed]),
  });

  const accept = match.getByRole("button", {
    name: /Accept the 1 that look right - 1 still need you/,
  });
  await expect(accept).toBeVisible();
  await accept.click();

  // The yellow row is answered; the red one is not, so Confirm stays shut.
  await expect(match.getByLabel(/Which panel is "06LFFENDER"\?/)).toHaveValue("LFFENDER");
  await expect(match.getByLabel(/Which panel is "14ROOF"\?/)).toHaveValue("");
  await expect(match.getByRole("button", { name: "Confirm this panel set" })).toBeDisabled();
  await expect(match.getByText(/1 panel name has no answer yet/)).toBeVisible();
  expect(proposals).toHaveLength(0);
});

test("T90 a rough name is recorded on the batch and never as a permanent alias", async ({
  page,
}) => {
  const { match, proposals } = await openMatch(page, walkView);
  await match.getByRole("button", { name: "It is LCROOF" }).click();
  await match.getByRole("textbox", { name: "Who decided" }).fill("FTM quality owner");
  await match
    .getByRole("textbox", { name: "How they decided" })
    .fill("walked the vehicle with the operator");
  await match
    .getByRole("textbox", { name: "Note", exact: true })
    .fill("September walk, same as last month");
  await match.getByRole("button", { name: "Confirm this panel set" }).click();
  await expect(match.getByText(/Panel set proposed/)).toBeVisible();

  expect(proposals).toHaveLength(1);
  const payload = proposals[0].payload as {
    matches: { raw_zone_text: string; zone_code: string }[];
    walk: { fingerprint: string; pairs: { raw_zone_text: string; specificity: string }[] };
  };
  // D-90-3: only the specific name becomes a permanent alias.
  expect(payload.matches.map((m) => m.raw_zone_text)).toEqual(["06LFFENDER"]);
  // D-90-11: the whole walk, rough included, rides on this batch.
  expect(payload.walk.fingerprint).toBe("FENDER|ROOF");
  expect(payload.walk.pairs.map((p) => [p.raw_zone_text, p.specificity])).toEqual([
    ["06LFFENDER", "specific"],
    ["14ROOF", "rough"],
  ]);
});

test("T90 when the two rules disagree both answers are shown and neither is filled in", async ({
  page,
}) => {
  const split = walkRowFor("14ROOF", {
    panel_group: "ROOF",
    attention: "red",
    reason:
      "the two rules disagree: group+ordinal says LCROOF and the walk number says RCROOF." +
      " Neither is proposed -- a disagreement is information, so you choose (D-90-2)",
    rule: "none",
    proposed_zone_code: null,
    rule_group_ordinal_zone_code: "LCROOF",
    rule_walk_number_zone_code: "RCROOF",
  });
  const stillRed = { ...fenderRow, attention: "red" as const, prefilled_zone_code: null };
  const { match } = await openMatch(page, {
    ...walkView,
    held_panels: [
      { ...panelMatch.held_panels[0], walk: stillRed },
      { ...panelMatch.held_panels[1], walk: split },
    ],
    walk: walkBlock([stillRed, split], {
      disagreements: ["14ROOF"],
      rule_walk_number_available: true,
      rule_walk_number_reason: "the file's numbers span 1..32",
      yellow_count: 0,
      red_count: 2,
    }),
  });

  const walk = match.getByRole("region", { name: "The walk this file describes" });
  await expect(walk.getByText(/The two rules disagree about 14ROOF/)).toBeVisible();
  // Nothing else in the set is taken on trust either, so there is no bulk click.
  await expect(match.getByRole("button", { name: /Accept/ })).toHaveCount(0);

  const roof = match.locator('li[data-raw="14ROOF"]');
  await expect(roof.getByText(/the walk proposes nothing here/)).toBeVisible();
  await expect(
    roof.getByText(/By family and position it is LCROOF; by the file's own number it is RCROOF/),
  ).toBeVisible();
  // Neither answer is filled in, and there is no one-click answer for it.
  await expect(roof.getByLabel(/Which panel is "14ROOF"\?/)).toHaveValue("");
  await expect(roof.getByRole("button", { name: /^It is / })).toHaveCount(0);
});

test("T91 a spelling this plant calls another panel says so in the row and is never learned", async ({
  page,
}) => {
  // D-91-2 / D-91-3. The row is SPECIFIC on this sheet -- `specificity`
  // alone would let it become a permanent alias -- and the server has said
  // `batch` because another file of this plant confirmed the same spelling
  // as a different panel. The screen says which file, before the owner
  // presses Confirm, and sends the pair on the batch only.
  const contradicted = {
    ...fenderRow,
    binding: "batch" as const,
    binding_reason:
      "this plant has already confirmed 06LFFENDER as LCFENDER on 08 Aug2026 CF data FTM.xlsx." +
      " Both files are believed about themselves, so the name on its own no longer says which" +
      " panel it is here: it is confirmed for this upload and never learned forever (D-91-2)",
  };
  const { match, proposals } = await openMatch(page, {
    ...walkView,
    held_panels: [
      { ...panelMatch.held_panels[0], walk: contradicted },
      { ...panelMatch.held_panels[1], walk: roofRow },
    ],
    walk: walkBlock([contradicted, roofRow]),
  });

  const fender = match.locator('li[data-raw="06LFFENDER"]');
  await expect(fender).toHaveAttribute("data-binding", "batch");
  await expect(fender.getByText(/this upload only/)).toBeVisible();
  await expect(fender.getByText(/08 Aug2026 CF data FTM\.xlsx/)).toBeVisible();

  await match.getByRole("button", { name: "It is LCROOF" }).click();
  await match.getByRole("textbox", { name: "Who decided" }).fill("FTM quality owner");
  await match
    .getByRole("textbox", { name: "How they decided" })
    .fill("walked the vehicle with the operator");
  await match
    .getByRole("textbox", { name: "Note", exact: true })
    .fill("September walk; the August reading of 06LFFENDER stands");
  await match.getByRole("button", { name: "Confirm this panel set" }).click();
  await expect(match.getByText(/Panel set proposed/)).toBeVisible();

  const payload = proposals[0].payload as {
    matches: unknown[];
    walk: { pairs: { raw_zone_text: string }[] };
  };
  // Nothing may be learned forever here, and the walk is still recorded.
  expect(payload.matches).toEqual([]);
  expect(payload.walk.pairs.map((p) => p.raw_zone_text)).toEqual(["06LFFENDER", "14ROOF"]);
});
