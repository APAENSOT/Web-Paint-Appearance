import test from "node:test";
import assert from "node:assert/strict";
import { monthlyEntries } from "../src/features/measurements/studio-series";
import { studioPreview } from "./studio-fixtures";

test("T85 distribution adapter preserves every Overview field and reference, including API status and per-month limits", () => {
  const data = studioPreview({
    domain: "WAVESCAN",
    model: "P703",
    metric: "cf",
    months: ["2026-07", "2026-06"],
  });
  data.month_boxes[0].wavescan_boxes[0].outliers = ["78.1234567890123456789"];
  data.month_boxes[1].wavescan_boxes[0].ford = "65.7500";
  const entries = monthlyEntries(
    data,
    { id: "g", kind: "group", name: "Group", months: data.months },
    () => true,
  );
  for (const month of data.month_boxes)
    for (const box of month.wavescan_boxes) {
      const entry = entries.find(
        (entry) =>
          entry.month === month.month && entry.color === box.color_name && entry.box === box,
      );
      assert.ok(entry);
      assert.strictEqual(entry.box, box);
      assert.equal(entry.n, box.n);
      assert.equal(entry.orientation, box.orient === "Horizontal" ? "H" : "V");
    }
  for (const group of data.group_means) {
    const entry = entries.find((entry) => entry.group === group)!;
    assert.ok(entry);
    assert.equal(entry.box, undefined);
    assert.equal(entry.n, undefined);
    assert.equal(entry.itemId, "g");
  }
});

test("T85 absent whole-month and colour/orientation series occupy board slots, with no fabricated measurement", () => {
  const data = studioPreview({
    domain: "WAVESCAN",
    model: "P703",
    metric: "cf",
    months: ["2026-08"],
  });
  data.group_means = [];
  const entries = monthlyEntries(
    data,
    { id: "a", kind: "month", name: "Aug", months: data.months },
    () => true,
    ["Meteor Grey", "Arctic White"],
  );
  assert.deepEqual(
    entries.map((entry) => [entry.color, entry.orientation, entry.month]),
    [
      ["Meteor Grey", "H", "2026-08"],
      ["Meteor Grey", "V", "2026-08"],
      ["Arctic White", "H", "2026-08"],
      ["Arctic White", "V", "2026-08"],
    ],
  );
  assert.ok(entries.every((entry) => entry.box === undefined && entry.group === undefined));
  assert.deepEqual(
    monthlyEntries(
      data,
      { id: "a", kind: "month", name: "Aug", months: data.months },
      () => false,
      ["Meteor Grey"],
    ),
    [],
  );
});
