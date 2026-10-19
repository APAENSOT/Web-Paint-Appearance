import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HeldIdentityList } from "../src/features/measurements/HeldIdentityList";
import type { components } from "../src/api/types";
import { cleanReview, identity } from "./fixtures";

const colourMessage =
  '"Arctic White" is not a catalogue colour yet. Pick the existing name it already is, or wait for a new colour to be added.';
const emptyMessage =
  "This cell is blank/None — it will not load. Fix the spreadsheet; we will not invent a serial, model, or colour.";

const colourLabel: components["schemas"]["HeldLabelGroup"] = {
  reason: "UNKNOWN_COLOR",
  column: "color",
  raw_value: "Arctic White",
  count: 4,
  teachable_kind: "ALIAS_COLOR",
  candidates: ["Oxford White"],
  display_group: "colour",
  operator_message: colourMessage,
};

const emptyLabel: components["schemas"]["HeldLabelGroup"] = {
  reason: "UNKNOWN_MODEL",
  column: "model",
  raw_value: "(None)",
  count: 2,
  teachable_kind: null,
  candidates: ["P703 DBL RANGER"],
  display_group: "empty_identity",
  operator_message: emptyMessage,
};

function renderList(
  status: string,
  roles: string[],
  labels: components["schemas"]["HeldLabelGroup"][],
) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], {
    ...identity,
    principal: { ...identity.principal, roles },
  });
  client.setQueryData(["batch", 123], { ...cleanReview, held_labels: labels });
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <HeldIdentityList loadId={123} plant="FTM" status={status} />
    </QueryClientProvider>,
  );
  client.clear();
  return html;
}

test("engineer sees colour teach control and empty identity without pick", () => {
  const html = renderList("PENDING_REVIEW", ["engineer"], [emptyLabel, colourLabel]);
  const colourAt = html.indexOf(">Colour<");
  const emptyAt = html.indexOf(">Empty identity<");
  assert.ok(colourAt >= 0, html);
  assert.ok(emptyAt > colourAt, html);
  assert.match(html, /is not a catalogue colour yet/);
  assert.match(html, /Arctic White/);
  assert.match(html, /Oxford White/);
  assert.match(html, /blank\/None/);
  assert.match(html, /\(None\)/);
  assert.equal((html.match(/Pick catalogue colour/g) ?? []).length, 1);
  assert.doesNotMatch(html, />Model<|>Zone<|>Date<|>Header</);
});

test("viewer does not see a pick control", () => {
  const html = renderList("PENDING_REVIEW", ["viewer"], [colourLabel, emptyLabel]);
  assert.match(html, />Colour</);
  assert.match(html, /is not a catalogue colour yet/);
  assert.match(html, />Empty identity</);
  assert.doesNotMatch(html, /Pick catalogue name/);
});

test("committed remainder can teach an existing colour without replaying the committed batch", () => {
  const html = renderList("COMMITTED", ["engineer"], [colourLabel]);
  assert.match(html, />Colour</);
  assert.match(html, /Pick catalogue colour/);
});

test("unknown panel offers only its model's existing panel candidates", () => {
  const panel: components["schemas"]["HeldLabelGroup"] = {
    reason: "UNKNOWN_CHECKZONE",
    column: "checkzone",
    raw_value: "Front hood",
    count: 1,
    teachable_kind: "ALIAS_CHECKZONE",
    candidates: ["Hood", "Fender"],
    display_group: "zone",
    operator_message: "Choose this model's existing panel.",
    model_code: "P703 DBL RANGER",
  };
  const html = renderList("PENDING_REVIEW", ["engineer"], [panel]);
  assert.match(html, /Existing panel for P703 DBL RANGER/);
  assert.match(html, /Hood/);
  assert.match(html, /Fender/);
});

const plantOfferLabel: components["schemas"]["HeldLabelGroup"] = {
  reason: "COLOR_NOT_OFFERED",
  column: "color",
  raw_value: "Black",
  count: 2,
  teachable_kind: "ALIAS_COLOR",
  candidates: ["Absolute / Shadow Black", "Agate Black"],
  display_group: "plant_offer",
  operator_message: '"Black" is not on this plant\'s list. Choose the official colour name.',
};

test("plant-list colour offers both official names without preselecting either", () => {
  const html = renderList("PENDING_REVIEW", ["engineer"], [plantOfferLabel]);
  assert.match(html, />Plant list</);
  assert.match(html, /not on this plant/);
  assert.match(html, /Pick catalogue colour/);
  assert.match(html, /Absolute \/ Shadow Black/);
  assert.match(html, /Agate Black/);
  assert.match(html, /<option value="" selected="">Pick catalogue colour/);
  assert.doesNotMatch(html, /<option value="(?:Absolute \/ Shadow Black|Agate Black)" selected/);
});

test("model not offered stays unteachable", () => {
  const html = renderList(
    "PENDING_REVIEW",
    ["engineer"],
    [
      {
        ...plantOfferLabel,
        reason: "MODEL_NOT_OFFERED",
        column: "model",
        raw_value: "Ranger",
        teachable_kind: null,
        candidates: ["P703 DBL RANGER"],
      },
    ],
  );
  assert.doesNotMatch(html, /Pick catalogue colour|Pick model/);
});

test("T115 a held model says Attach loads it, and offers no control", () => {
  // T115 (D-115-5): the server's model sentence; the colour's "confirming adds
  // it to the list" is not said, and nothing to pick or confirm is rendered.
  const sentence =
    "P703 DBL RANGER is not on FTM's list (it was removed, or never attached), so these rows " +
    "will not load. An Admin attaches it on Standard → Model; this file then loads by itself.";
  const html = renderList(
    "PENDING_REVIEW",
    ["engineer", "admin"],
    [
      {
        ...plantOfferLabel,
        reason: "MODEL_NOT_OFFERED",
        column: "model",
        raw_value: "P703 DBL RANGER",
        teachable_kind: null,
        candidates: [],
        operator_message: sentence,
      },
    ],
  );
  assert.ok(html.includes("An Admin attaches it on Standard"), html);
  assert.doesNotMatch(html, /confirming adds it/);
  assert.doesNotMatch(html, /<select|<button/);
});

// T86: the panel question that cannot be answered one row at a time.
const notValidForModel: components["schemas"]["HeldLabelGroup"] = {
  reason: "ZONE_NOT_VALID_FOR_MODEL",
  column: "checkzone",
  raw_value: "06LFFENDER",
  count: 24,
  teachable_kind: null,
  candidates: [],
  display_group: "zone",
  operator_message:
    'The panel name "06LFFENDER" is not on this model\'s panel list at FTM, and we cannot offer a' +
    ' single panel to pick for it here. Use "Match the panel list" on this tab to match this' +
    " file's panel names to FTM's own panels, name by name.",
  model_code: "P703 DBL RANGER",
};

test("a panel with no pick on offer gets the set flow and no pick control", () => {
  const html = renderList("PENDING_REVIEW", ["engineer"], [notValidForModel]);
  assert.match(html, />Panel</);
  // The control the copy names is actually rendered, as a button.
  assert.match(html, /<button[^>]*>Match the panel list<\/button>/);
  // The copy no longer promises a control that is not there (T86 3.8), and
  // no per-row panel picker is rendered for a zone another model owns.
  assert.doesNotMatch(html, /Existing panel for/);
  assert.doesNotMatch(html, />Pick panel</);
});

test("a viewer is not offered the panel set flow", () => {
  const html = renderList("PENDING_REVIEW", ["viewer"], [notValidForModel]);
  assert.match(html, />Panel</);
  // The sentence still explains the flow; the button is an Engineer's.
  assert.match(html, /Match the panel list/);
  assert.doesNotMatch(html, /<button[^>]*>Match the panel list<\/button>/);
});

// =====================================================================
// T89 -- the per-row picker is the match screen's list (D-89-6, D-89-9)
// =====================================================================
const t89Panel: components["schemas"]["HeldLabelGroup"] = {
  reason: "UNKNOWN_CHECKZONE",
  column: "checkzone",
  raw_value: "07LFFENDER",
  count: 21,
  teachable_kind: "ALIAS_CHECKZONE",
  candidates: ["LCFENDER", "LRFENDER"],
  blocked_candidates: [
    {
      zone_code: "LFFENDER",
      point_no: 6,
      tolerance_group: "Vertical",
      taken_by: "06LFFENDER",
      label: "already matched to 06LFFENDER",
    },
  ],
  display_group: "zone",
  operator_message: "Pick the panel it is from P703 DBL RANGER's own list.",
  model_code: "P703 DBL RANGER",
  orientations: ["Vertical"],
};

test("T89 a taken panel is offered as a disabled option naming what took it", () => {
  const html = renderList("PENDING_REVIEW", ["engineer"], [t89Panel]);
  assert.match(html, /LCFENDER/);
  // D-89-6: shown, last, disabled, labelled -- the owner's choice over
  // hiding it, because an absence is a puzzle.
  assert.match(html, /already matched to 06LFFENDER/);
  assert.match(html, /disabled=""/);
  assert.ok(
    html.indexOf("already matched to 06LFFENDER") > html.indexOf("LCFENDER"),
    "the taken panel must come last",
  );
});

test("T89 a carried-over decision arrives pre-selected with its own confirm", () => {
  const html = renderList(
    "PENDING_REVIEW",
    ["engineer"],
    [
      {
        ...t89Panel,
        carried_over: {
          zone_code: "LCFENDER",
          kind: "other_model",
          reason:
            "This plant already reads '07LFFENDER' as LCFENDER on P703 DBL RAPTOR on 2026-10-08.",
          source_raw_zone_text: "07LFFENDER",
          source_model_code: "P703 DBL RAPTOR",
          decided_at: "2026-10-08T14:37:00+07:00",
          load_id: null,
        },
      },
    ],
  );
  assert.match(html, /Carried over from an earlier decision/);
  assert.match(html, /P703 DBL RAPTOR/);
  // D-89-9: a person still confirms it. The pre-fill is a starting point.
  assert.match(html, /Confirm LCFENDER for 07LFFENDER/);
  assert.match(html, /data-carried="other_model"/);
});
