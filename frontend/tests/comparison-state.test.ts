import { test } from "node:test";
import assert from "node:assert/strict";
import {
  initialComparison,
  comparisonReducer,
  visibleVehicles,
} from "../src/features/measurements/comparison-state.ts";
const vehicle = (id: string) => ({
  vehicle_id: id,
  domain: "WAVESCAN" as const,
  measured_date: "2026-06-22",
  date_is_month_only: false,
  week: 4,
  model: "P703",
  color: "White",
  serial_no: null,
  identity_complete: true,
  point_count: 1,
  expected_point_count: 31,
  incomplete: true,
});
test("T80 selection appends once, reorders, has no cap, and clamps eight-column pages", () => {
  let s = initialComparison();
  for (let i = 0; i < 9; i++)
    s = comparisonReducer(s, { type: "add", vehicle: vehicle(String(i)) });
  s = comparisonReducer(s, { type: "add", vehicle: vehicle("0") });
  assert.equal(s.selected.length, 9);
  s = comparisonReducer(s, { type: "move", index: 8, direction: -1 });
  assert.equal(s.selected[7].vehicle_id, "8");
  s = comparisonReducer(s, { type: "page", page: 1 });
  assert.deepEqual(
    visibleVehicles(s).map((v) => v.vehicle_id),
    ["7"],
  );
  s = comparisonReducer(s, { type: "remove", id: "0" });
  assert.equal(s.columnPage, 0);
});
test("T80 candidate filters retain selection, remove out-of-month weeks, and resets clear selection", () => {
  let s: ReturnType<typeof initialComparison> = {
    ...initialComparison(),
    months: ["2026-06", "2026-07"],
    periods: ["2026-06-W4", "2026-07-W1"],
    focused: "HOOD",
  };
  s = comparisonReducer(s, { type: "add", vehicle: vehicle("a") });
  s = comparisonReducer(s, { type: "filter", key: "months", value: ["2026-07"] });
  assert.deepEqual(s.periods, ["2026-07-W1"]);
  assert.equal(s.selected.length, 1);
  s = comparisonReducer(s, { type: "search", value: "blank" });
  assert.equal(s.selected.length, 1);
  s = comparisonReducer(s, { type: "mode", mode: "months" });
  assert.equal(s.selected.length, 1);
  s = comparisonReducer(s, { type: "domain", domain: "FILMTHICKNESS" });
  assert.equal(s.metric, "ecoat");
  assert.equal(s.selected.length, 0);
  assert.equal(s.focused, null);
  assert.equal(s.search, "");
  s = comparisonReducer(s, { type: "add", vehicle: vehicle("b") });
  s = comparisonReducer(s, { type: "model", model: "U704" });
  assert.equal(s.selected.length, 0);
  s = comparisonReducer(s, { type: "clear" });
  assert.equal(s.model, null);
  assert.equal(s.mode, "months");
  assert.equal(s.metric, "cf");
});
