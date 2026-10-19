import assert from "node:assert/strict";
import { test } from "node:test";
import type { components } from "../src/api/types";
import { emptyIdentityCopy } from "../src/features/measurements/review-copy";

type Held = components["schemas"]["HeldLabelGroup"];
// RO15's row sentence, as backend held_label_copy._date_disagrees_message writes it.
const MONTH =
  'These rows are dated 24 Feb 2026 and 10 May 2026, but their Month cell says "September". ' +
  "They will not load. Fix the date or the month in the file and upload it again. We never choose one for you.";
const held = (over: Partial<Held>): Held => ({
  reason: "BAD_DATE",
  column: "month",
  raw_value: "September",
  count: 64,
  teachable_kind: null,
  display_group: "date",
  operator_message: MONTH,
  ...over,
});

test("D-RO17-18: a month hold's banner says RO15's sentence, never 'no date'", () => {
  const copy = emptyIdentityCopy([held({})]);
  assert.equal(copy, MONTH);
  assert.doesNotMatch(copy, /no date/);
});

test("D-RO17-18: a year hold says its own sentence too", () => {
  const year = MONTH.replace("Month cell", "Year cell").replace("the month in", "the year in");
  assert.equal(emptyIdentityCopy([held({ column: "year", operator_message: year })]), year);
});

test("D-RO17-18: a real blank date still says 'no date'; both together say both", () => {
  const blank = held({ column: "date", raw_value: "", operator_message: "No date." });
  assert.match(emptyIdentityCopy([blank]), /^These rows have no date\. We will not guess/);
  const both = emptyIdentityCopy([held({}), held({}), blank]);
  assert.ok(both.startsWith(MONTH));
  assert.equal(both.split(MONTH).length, 2, "the same sentence is said once");
  assert.match(both, /These rows have no date\./);
});
