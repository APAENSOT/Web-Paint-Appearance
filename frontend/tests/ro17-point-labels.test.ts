import assert from "node:assert/strict";
import { test } from "node:test";
import { makeLabelOf, pointText } from "../src/features/measurements/point-labels";

const labelOf = makeLabelOf([
  { domain: "wavescan", model_code: "CX743", code: "11ROOF", label: "Roof centre", live: true },
  { domain: "film", model_code: "CX743", code: "11ROOF", label: "Roof (film)", live: true },
  { domain: "film", model_code: "CX743", code: "022LTFTDOOR", label: "LF door", live: true },
  { domain: "wavescan", model_code: "J73", code: "01HOOD", label: "01HOOD", live: false },
]);

test("D-RO17-16: a point reads by its plant's label for that model and domain", () => {
  assert.equal(labelOf("wavescan", "CX743", "11ROOF"), "Roof centre");
  assert.equal(labelOf("film", "CX743", "11ROOF"), "Roof (film)");
  // A retired point keeps its label: History still shows its readings.
  assert.equal(labelOf("wavescan", "J73", "01HOOD"), "01HOOD");
});

test("D-RO17-16: no label, another model or another domain falls back to the code", () => {
  assert.equal(labelOf("wavescan", "CX743", "99NONE"), "99NONE");
  assert.equal(labelOf("wavescan", "J73", "11ROOF"), "11ROOF");
  assert.equal(labelOf("wavescan", "CX743", "022LTFTDOOR"), "022LTFTDOOR");
  assert.equal(labelOf("wavescan", null, "11ROOF"), "11ROOF");
  assert.equal(makeLabelOf([])("film", "CX743", "022LTFTDOOR"), "022LTFTDOOR");
});

test("D-RO17-16: with no domain, only one domain's label is used; two give the code", () => {
  assert.equal(labelOf(null, "CX743", "022LTFTDOOR"), "LF door");
  assert.equal(labelOf(null, "CX743", "11ROOF"), "11ROOF");
});

test("D-RO17-16: label first, code secondary, and the code once when they are equal", () => {
  assert.equal(pointText("Roof centre", "11ROOF"), "Roof centre · code 11ROOF");
  // RO17-FIX (D-RO17F-3): SAP's shifted numbering never reads as one name.
  assert.equal(pointText("036LBOXSIDE", "039LBOXSIDE"), "036LBOXSIDE · code 039LBOXSIDE");
  assert.equal(pointText("11ROOF", "11ROOF"), "11ROOF");
});
