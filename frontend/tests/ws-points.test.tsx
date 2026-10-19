/**
 * T114: Point Check's Wave Scan helpers, and the extra tag in review.
 *
 * * D-114-2 -- Save sends only the points whose tick moved;
 * * D-114-5 -- review's panel picker names an extra point as extra;
 * * D-114-6 -- Add shows an existing code's own H / V, and a new code's from
 *   its name by the server's words; H / V is shown, never chosen.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { components } from "../src/api/types";
import { RoughPanelCell } from "../src/features/measurements/RoughPanelCell";
import type { RoughPanels } from "../src/features/measurements/rough-panels";
import { addPreview, changedWsPoints, type WsPoint } from "../src/features/filmthickness/ws-points";

function point(no: number, code: string, counted = true): WsPoint {
  return {
    point_no: no,
    zone_code: code,
    label: code,
    tolerance_group: code.includes("HOOD") ? "Horizontal" : "Vertical",
    counted,
    is_extra: false,
    note: "T58 owner lock 2026-10-05",
    created_at: "2026-10-05T19:46:02+07:00",
    reason: null,
    changed_by: null,
    changed_at: null,
  };
}

const WORDS = ["HOOD", "ROOF", "FLOOR"];
const CHOICES = [
  { zone_code: "01RHS Hood Rr28", tolerance_group: "Horizontal" },
  { zone_code: "RTTAILGATE", tolerance_group: "Vertical" },
];

test("T114 Save sends nothing until a tick moves", () => {
  const points = [point(1, "RRHOOD"), point(2, "LFFENDER", false)];
  assert.deepEqual(changedWsPoints(points, {}), []);
  assert.deepEqual(changedWsPoints(points, { RRHOOD: true, LFFENDER: false }), []);
});

test("T114 Save sends exactly the points whose tick moved, both ways", () => {
  const points = [point(1, "RRHOOD"), point(2, "LFFENDER", false)];
  assert.deepEqual(changedWsPoints(points, { RRHOOD: false, LFFENDER: true }), [
    { zone_code: "RRHOOD", counted: false },
    { zone_code: "LFFENDER", counted: true },
  ]);
});

test("T114 Add shows nothing for a blank box and an existing code's own H / V", () => {
  assert.equal(addPreview("   ", CHOICES, WORDS), null);
  assert.deepEqual(addPreview("RTTAILGATE", CHOICES, WORDS), {
    code: "RTTAILGATE",
    isNew: false,
    tolerance: "Vertical",
  });
  assert.equal(addPreview(" 01RHS Hood Rr28 ", CHOICES, WORDS)?.tolerance, "Horizontal");
});

test("T114 Add reads a new code's H / V off its name, any case", () => {
  assert.deepEqual(addPreview("33 Rr Roof", CHOICES, WORDS), {
    code: "33 Rr Roof",
    isNew: true,
    tolerance: "Horizontal",
  });
  assert.equal(addPreview("33boxfloor", CHOICES, WORDS)?.tolerance, "Horizontal");
  assert.equal(addPreview("33LFDOOR", CHOICES, WORDS)?.tolerance, "Vertical");
  // A twin spelling is "new" here; the server refuses it with the sentence.
  assert.equal(addPreview("rttailgate", CHOICES, WORDS)?.isNew, true);
});

test("T114 review's panel picker names an extra point as extra and no other", () => {
  const panel: components["schemas"]["RoughPanelOut"] = {
    raw_zone_text: "33LFDOOR",
    model_code: "P703 DBL RAPTOR",
    rows: 1,
    proposed_zone_code: null,
    prefilled_zone_code: null,
    confirmed_zone_code: null,
    fits_canonical: [],
    shares_name_with: [],
    rule: null,
    attention: "red",
    reason: "no structural rule applies",
    choosable: ["LTFDOOR", "T114 Mark Door"],
    extra_choices: ["T114 Mark Door"],
    operator_message: "Which panel is 33LFDOOR?",
  };
  const rough = {
    loadId: 7,
    selected: () => "",
    choose: () => undefined,
    confirm: { isPending: false, isError: false, error: null, mutate: () => undefined },
  } as unknown as RoughPanels;
  const html = renderToStaticMarkup(
    <RoughPanelCell
      panel={panel}
      row={{ source_row: 2 } as components["schemas"]["WorksheetRowOut"]}
      rough={rough}
    />,
  );
  assert.match(html, /T114 Mark Door(<!-- -->)? · extra/);
  assert.doesNotMatch(html, /LTFDOOR(<!-- -->)? · extra/);
});
