import assert from "node:assert/strict";
import { test } from "node:test";
import {
  axisTicks,
  chartGroups,
  displayMean,
  effectiveMonth,
  emptyReason,
  exclusionsOf,
  type ImgOverview,
  type ImgSeries,
} from "../src/features/overview/img-overview-display.ts";

const none = {
  SETTING_EXCLUDED: 0,
  INCOMPLETE_TOTAL: 0,
  UNKNOWN_ORIENTATION: 0,
  INVALID_VALUE: 0,
  DUPLICATE_LAYER: 0,
};
const s = (over: Partial<ImgSeries>): ImgSeries => ({
  id: "x",
  plant_code: "FTM",
  family_key: "P703",
  family_name: "P703",
  orient: "H",
  metric: "CF",
  unit: "CF",
  film_measure: null,
  mean: "60",
  included_count: 3,
  count_unit: "CF_READING",
  availability: "AVAILABLE",
  member_models: [],
  models: [],
  colors: [],
  locations: [],
  exclusions: none,
  ...over,
});

test("groups follow FTM/FVL/SAP/AAT, keep visible plants without slots, never invent one", () => {
  const data = {
    month: "2026-09",
    film_measure: "CALCULATED_TOTAL",
    plants: ["AAT", "FTM", "SAP"],
    source: "",
    aggregation: "",
    series: [
      s({ id: "a", plant_code: "AAT", family_key: "U704" }),
      s({ id: "b", plant_code: "FTM" }),
      s({ id: "c", plant_code: "FTM", orient: "V" }),
      s({ id: "d", plant_code: "AAT", family_key: "P703" }),
    ],
  } as ImgOverview;
  const groups = chartGroups(data, "CF", "H");
  assert.deepEqual(
    groups.map((g) => g.plant),
    ["FTM", "SAP", "AAT"],
  );
  assert.deepEqual(
    groups.map((g) => g.slots.map((x) => x.id)),
    [["b"], [], ["a", "d"]],
  );
});

test("axis starts at zero and covers the largest returned mean", () => {
  assert.deepEqual(axisTicks([s({ mean: "66.07" }), s({ mean: "50.2" })]), [0, 20, 40, 60, 80]);
  assert.deepEqual(axisTicks([s({ mean: "112.58" })]), [0, 50, 100, 150]);
  assert.deepEqual(axisTicks([s({ mean: null })]), [0, 25, 50, 75, 100]);
});

test("null means read as a reason, never a zero; labels keep the returned value", () => {
  assert.equal(emptyReason(s({ mean: null, availability: "NO_ELIGIBLE_READINGS" })), "No readings");
  const excluded = s({
    mean: null,
    availability: "EXCLUDED_OR_INCOMPLETE",
    exclusions: { ...none, SETTING_EXCLUDED: 2, INCOMPLETE_TOTAL: 5 },
  });
  assert.equal(emptyReason(excluded), "Excluded · 7");
  assert.deepEqual(
    exclusionsOf(excluded).map((e) => e.count),
    [2, 5],
  );
  assert.equal(displayMean("63.87679551522943037974683544"), "63.88");
  assert.equal(displayMean("0"), "0.00");
});

test("a kept month survives reopen while listed, else the newest", () => {
  assert.equal(effectiveMonth(["2026-10", "2026-09"], "2026-09"), "2026-09");
  assert.equal(effectiveMonth(["2026-10", "2026-09"], "2025-01"), "2026-10");
  assert.equal(effectiveMonth([], null), null);
});

test("Overview IMG axis crops like the reference but always covers every bar", async () => {
  const { croppedTicks, displayMean1 } =
    await import("../src/features/overview/img-overview-display.ts");
  const ticks = croppedTicks(
    ["63.5", "60.8", "51.4", "64.9", "58.6", "61.3", "65.3", "64.1"].map((mean) => ({ mean })),
  );
  assert.equal(ticks[0], 45);
  assert.equal(ticks.at(-1), 70);
  assert.ok(ticks[0] < 51.4 && ticks.at(-1)! > 65.3);
  assert.deepEqual(croppedTicks([{ mean: null }]), [0, 25, 50, 75, 100]);
  assert.ok(croppedTicks([{ mean: "100" }])[0] < 100);
  assert.equal(displayMean1("63.87679551522943037974683544"), "63.9");
});
