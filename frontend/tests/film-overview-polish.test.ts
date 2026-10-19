import assert from "node:assert/strict";
import test from "node:test";
import { polishFixture } from "./film-overview-polish-fixtures";
import { filmBox } from "./film-overview-fixtures";
import {
  groupFilmBoxes,
  filmDomain,
  integerTicks,
  displayMean,
  statusPresentation,
  specSegments,
  panelLegend,
  pointKey,
} from "../src/features/filmthickness/film-overview-display";

test("T69 stable partition preserves first models, supplied slots, actual orientation order and null family", () => {
  const original = JSON.stringify(polishFixture);
  const groups = groupFilmBoxes(polishFixture, "ECOAT");
  assert.deepEqual(
    groups.map((group) => group.model),
    ["U704", "P703 DBL RANGER"],
  );
  assert.deepEqual(
    groups[0].colours.map((colour) => colour.name),
    ["Zulu White", "Aqua", "Absolute / Shadow Black", "Unassigned", "Fallback colour"],
  );
  assert.deepEqual(
    groups[0].horizontal.map((box) => box.color_name),
    groups[0].colours.map((colour) => colour.name),
  );
  assert.deepEqual(
    groups[0].vertical.map((box) => box.color_name),
    ["Zulu White", "Absolute / Shadow Black"],
  );
  assert.equal(groups[0].colours[3].family_name, null);
  const otherPlant = {
    ...polishFixture,
    color_sequence: [
      { ...polishFixture.color_sequence[2], family_code: "MM", family_name: "Other plant family" },
    ],
    boxes: [filmBox({ family_code: "MM", family_name: "Other plant family" })],
  };
  assert.equal(groupFilmBoxes(otherPlant, "ECOAT")[0].colours[0].family_name, "Other plant family");
  assert.equal(JSON.stringify(polishFixture), original);
});

test("T69 explicit API status survives integral mean formatting and outside-limit points", () => {
  const boxes = polishFixture.boxes;
  assert.equal(displayMean(boxes[0].mean), "9");
  assert.equal(statusPresentation(boxes[0]).text, "Fail");
  assert.equal(displayMean(boxes[1].mean), "25");
  assert.equal(statusPresentation(boxes[1]).text, "Over");
  assert.equal(statusPresentation(boxes[2]).text, "Pass");
  assert.equal(statusPresentation(boxes[3]).text, "No standard");
  // T112: owner 2026-10-11 — WARNING reads Acceptable
  assert.equal(statusPresentation(boxes[4]).text, "Acceptable");
  assert.equal(
    statusPresentation(filmBox({ layer_code: "CLEAR", status: "WARNING" })).text,
    "For Improvement",
  );
  assert.equal(
    statusPresentation(filmBox({ layer_code: "BASE", status: "WARNING" })).text,
    "Acceptable",
  );
  assert.equal(statusPresentation(boxes[8]).text, "Not graded");
  assert.equal(
    new Set(boxes[2].out_of_spec.map((point, index) => pointKey(boxes[2], point, index))).size,
    3,
  );
});

test("T69 specs preserve authoritative labels, scope, zero, partial rules and per-slot attribution", () => {
  const partial = polishFixture.boxes[8];
  assert.equal(specSegments(partial, 60, 120)[0].label, "No point below");
  assert.equal(specSegments(partial, 60, 120).length, 1);
  assert.deepEqual(
    panelLegend([partial, polishFixture.boxes[9]]).map((spec) => spec.label),
    ["No point below", "Minimum requirement"],
  );
  assert.equal(specSegments(polishFixture.boxes[3], 60, 120).length, 0);
  const coincident = specSegments(polishFixture.boxes[4], 60, 120);
  assert.equal(coincident.length, 3);
  assert.ok(coincident.every((spec) => spec.value === 0));
  assert.ok(
    specSegments(polishFixture.boxes[0], 60, 120).every((spec) => spec.x1 >= 0 && spec.x2 <= 120),
  );
});

test("T69 common domain retains true statistics, means, extreme returned points and target with unique whole ticks", () => {
  const domain = filmDomain(polishFixture.boxes);
  assert.ok(domain[1] > 900 && domain[0] < 0);
  const ticks = integerTicks(domain);
  assert.ok(ticks.every(Number.isInteger));
  assert.equal(new Set(ticks.map(String)).size, ticks.length);
  assert.ok(ticks.length >= 2);
  assert.equal(displayMean("0.4999999999"), "0");
  assert.equal(displayMean("0.5"), "1");
  assert.ok(filmDomain([filmBox({ mean: "100", out_of_spec: [], lo: null })])[1] > 100);
});
