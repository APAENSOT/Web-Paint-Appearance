import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  allChosen,
  calendarYearMonth,
  defaultDataMonth,
  displayMean,
  groupBoxesByModel,
  integerDomain,
  integerTicks,
  isFilterOn,
  modelsToRender,
  monthTitle,
  statusLabel,
  targetRuns,
  toggleFilterValue,
} from "../src/features/measurements/overview-display.ts";
import { overviewBox } from "./overview-fixtures.ts";

test("display mean is one decimal from the API string", () => {
  assert.equal(displayMean("61.24"), "61.2");
  assert.equal(displayMean("80"), "80.0");
});

test("status words include No standard when the API status is null", () => {
  assert.equal(statusLabel("PASS"), "Pass");
  // T112: owner 2026-10-11 — WARNING reads Acceptable
  assert.equal(statusLabel("WARNING"), "Acceptable");
  assert.equal(statusLabel("FAIL"), "Fail");
  assert.equal(statusLabel(null), "No standard");
});

test("boxes stack by API model order, Horizontal then Vertical", () => {
  const rangerH = { ...overviewBox, model_code: "P703 DBL RANGER", orient: "Horizontal" as const };
  const rangerV = { ...overviewBox, model_code: "P703 DBL RANGER", orient: "Vertical" as const };
  const raptorV = { ...overviewBox, orient: "Vertical" as const };
  const groups = groupBoxesByModel([overviewBox, rangerH, raptorV, rangerV]);
  assert.deepEqual(
    groups.map((group) => group.model),
    ["P703 DBL RAPTOR", "P703 DBL RANGER"],
  );
  assert.equal(groups[0].horizontal[0].orient, "Horizontal");
  assert.equal(groups[0].vertical[0].orient, "Vertical");
});

test("unselected models mean every model that has a box", () => {
  const ranger = { ...overviewBox, model_code: "P703 DBL RANGER" };
  assert.deepEqual(
    modelsToRender([], [overviewBox, ranger], ["P703 DBL RAPTOR", "P703 DBL RANGER"]),
    ["P703 DBL RAPTOR", "P703 DBL RANGER"],
  );
  assert.deepEqual(
    modelsToRender(
      ["P703 DBL RANGER"],
      [overviewBox, ranger],
      ["P703 DBL RAPTOR", "P703 DBL RANGER"],
    ),
    ["P703 DBL RANGER"],
  );
});

test("empty filter selection means every option is on", () => {
  const options = ["P703 DBL RAPTOR", "P703 DBL RANGER"];
  assert.equal(allChosen([], options), true);
  assert.equal(isFilterOn([], options, "P703 DBL RAPTOR"), true);
  assert.deepEqual(toggleFilterValue([], options, "P703 DBL RANGER"), ["P703 DBL RAPTOR"]);
  assert.deepEqual(toggleFilterValue(["P703 DBL RAPTOR"], options, "P703 DBL RANGER"), []);
});

test("the data month prefers the calendar month then the latest available month", () => {
  assert.equal(defaultDataMonth("2026-09", ["2026-09", "2026-06"]), "2026-09");
  assert.equal(defaultDataMonth("2026-09", ["2026-08", "2026-06"]), "2026-08");
  assert.equal(defaultDataMonth("2026-09", []), "2026-09");
});

test("target lines span consecutive colours that share a standard", () => {
  const second = { ...overviewBox, color_name: "Command Grey", ford: "62.0", minimum: "55" };
  const other = {
    ...overviewBox,
    color_name: "Meteor Grey",
    family_code: "MM",
    ford: "65",
    minimum: "58",
  };
  assert.deepEqual(targetRuns([overviewBox, second, other], "ford"), [
    { value: 62, start: "Arctic White", end: "Command Grey" },
    { value: 65, start: "Meteor Grey", end: "Meteor Grey" },
  ]);
});

test("Y ticks are integers", () => {
  assert.deepEqual(integerDomain(54.2, 71.8), [54, 72]);
  assert.deepEqual(integerTicks([50, 70]), [50, 55, 60, 65, 70]);
});

test("calendar month is YYYY-MM", () => {
  assert.equal(calendarYearMonth(new Date(2026, 8, 22)), "2026-09");
});

test("month title is the selected data month", () => {
  assert.equal(monthTitle("2026-09"), "September 2026");
  assert.equal(monthTitle("2026-06"), "June 2026");
});

test("the overview pane never imports status_of or averages preview points", () => {
  const files = [
    "src/features/measurements/PlantOverview.tsx",
    "src/features/measurements/overview-display.ts",
    "src/features/measurements/PlantMeasurements.tsx",
    "src/components/ct/FilterPanel.tsx",
  ];
  const root = fileURLToPath(new URL("..", import.meta.url));
  for (const file of files) {
    const source = readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
    assert.equal(source.includes("status_of"), false, file);
    assert.equal(source.includes("statusOf"), false, file);
    assert.equal(source.includes("/dashboard/preview"), false, file);
  }
  assert.ok(root);
});
