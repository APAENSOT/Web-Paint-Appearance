import test from "node:test";
import assert from "node:assert/strict";
import { candidatesFor, reading } from "./comparison-fixtures";
import {
  addCard,
  blockReason,
  emptyBench,
  moveSlot,
  panelOf,
  parseShared,
  presetMonths,
  locationStyles,
  profileRows,
  spectrumRows,
  traces,
  removeSlot,
  retargetMonths,
  monthModel,
  monthValue,
  toShared,
  type Points,
} from "../src/features/measurements/comparison-bench";
import { toCsv } from "../src/features/measurements/chart-export";

const cars = candidatesFor("WAVESCAN");
const month = (m: string, model = "P703") => ({
  kind: "month" as const,
  month: m,
  model,
  domain: "WAVESCAN" as const,
});

test("bench keeps domain boundaries and accepts model-qualified months, refusing repeats and overflow", () => {
  let bench = addCard(emptyBench(), month("2026-07"));
  assert.equal(bench.model, "P703");
  assert.equal(blockReason(bench, month("2026-06", "U704")), null);
  assert.match(blockReason(bench, month("2026-07"))!, /already/);
  for (const m of ["2026-06", "2026-05", "2026-04"]) bench = addCard(bench, month(m));
  assert.match(blockReason(bench, month("2026-03"))!, /4 months/);
  for (const car of cars.slice(0, 9)) bench = addCard(bench, { kind: "car", car });
  assert.equal(bench.cars.length, 8);
});

test("removing the last slot unlocks the model; moveSlot places a slot at the target", () => {
  let bench = ["2026-07", "2026-06", "2026-05"].reduce(
    (b, m) => addCard(b, month(m)),
    emptyBench(),
  );
  bench = moveSlot(bench, "month", "2026-05", "2026-07");
  assert.deepEqual(bench.months, ["2026-05", "2026-07", "2026-06"]);
  for (const m of [...bench.months]) bench = removeSlot(bench, "month", m);
  assert.deepEqual(bench, emptyBench());
});

test("traces join raw readings across metrics by measurement row, with no averaging", () => {
  const [a, b] = cars;
  const loc = (point_no: number, code: string, orientation: string, cells: unknown[]) => ({
    point_no,
    code,
    orientation,
    cells,
  });
  const points = (du: string, wa: string) =>
    ({
      columns: [a, b],
      locations: [
        loc(1, "RRHOOD", "H", [
          { vehicle_id: a.vehicle_id, missing: false, readings: [reading(du, 7), reading("1", 8)] },
          { vehicle_id: b.vehicle_id, missing: true, readings: [] },
        ]),
        loc(2, "LFFENDER", "V", [
          { vehicle_id: a.vehicle_id, missing: true, readings: [] },
          { vehicle_id: b.vehicle_id, missing: true, readings: [] },
        ]),
        loc(3, "LCROOF", "H", [
          { vehicle_id: a.vehicle_id, missing: true, readings: [] },
          { vehicle_id: b.vehicle_id, missing: false, readings: [reading(wa, 9)] },
        ]),
      ],
    }) as unknown as Points;
  const list = traces([
    { metric: "du", points: points("10", "x") },
    { metric: "wa", points: points("x", "30") },
  ]);
  assert.deepEqual(
    list.map((t) => [t.key, t.locationLabel, t.orient, t.values]),
    [
      ["m7", "01 RRHOOD", "Horizontal", { du: 10 }],
      ["m8", "01 RRHOOD", "Horizontal", { du: 1, wa: 1 }],
      ["m9", "03 LCROOF", "Horizontal", { wa: 30 }],
    ],
  );
  assert.deepEqual(spectrumRows(list, ["du", "wa"])[1], { metric: "Wa", m7: null, m8: 1, m9: 30 });
  // LFFENDER has no reading for anyone, so it never becomes a blank column.
  const profile = profileRows(list, "du", [a.vehicle_id, b.vehicle_id]);
  assert.deepEqual(
    profile.rows.map((r) => r.location),
    ["01 RRHOOD"],
  );
  assert.deepEqual(profile.keys, [`${a.vehicle_id}#0`, `${a.vehicle_id}#1`]);
});

test("panelOf reads the body panel from FTM checkzone codes", () => {
  const codes = [
    "RRHOOD",
    "LCROOF",
    "LFFENDER",
    "LTFDOOR",
    "LCPILLAR",
    "LFBOX",
    "LTTAILGATE",
    "X1",
  ];
  assert.deepEqual(codes.map(panelOf), [
    "Hood",
    "Roof",
    "Fender",
    "Door",
    "Pillar",
    "Box",
    "Gate",
    "Other",
  ]);
});

test("shared links are validated and same-domain presets preserve selected cars", () => {
  const id = cars[0].vehicle_id;
  assert.deepEqual(
    parseShared({
      model: "P703",
      months: ["2026-08", "bad", "2026-09"],
      cars: [id, "x"],
      baseline: "2026-08",
    }),
    {
      domain: "WAVESCAN",
      model: "P703",
      months: ["2026-08", "2026-09"],
      cars: [id],
      baseline: "2026-08",
    },
  );
  assert.equal(parseShared({ model: "P703", months: [], cars: [] }), undefined);
  assert.equal(parseShared("nope"), undefined);
  const bench = addCard(emptyBench(), { kind: "car", car: cars[0] });
  const preset = presetMonths(bench, "WAVESCAN", "P703", ["2026-09", "2026-08", "2026-07"], 2);
  assert.deepEqual(preset.months, ["2026-08", "2026-09"]);
  assert.equal(preset.baseline, "2026-08");
  assert.equal(preset.cars.length, 1);
  assert.equal(presetMonths(bench, "WAVESCAN", "U704", ["2026-09"], 3).cars.length, 1);
  assert.equal(removeSlot(preset, "month", "2026-08").baseline, null);
});

test("cross-model cars and same-month distributions survive sharing and reordering", () => {
  let bench = addCard(emptyBench(), month("2026-07"));
  bench = addCard(bench, month("2026-07", "U704"));
  assert.deepEqual(bench.months, ["2026-07", "U704::2026-07"]);
  assert.equal(monthModel(bench, bench.months[1]), "U704");
  assert.equal(monthValue(bench.months[1]), "2026-07");
  bench = addCard(bench, { kind: "car", car: cars[0] });
  const other = { ...cars[1], model: "U704" };
  bench = addCard(bench, { kind: "car", car: other });
  const shared = toShared(bench)!;
  assert.equal(shared.carModels?.[other.vehicle_id], "U704");
  assert.deepEqual(parseShared(shared), shared);
  const moved = moveSlot(bench, "month", "U704::2026-07", "2026-07");
  assert.deepEqual(moved.months, ["U704::2026-07", "2026-07"]);
  assert.equal(blockReason(bench, month("2026-07", "U704")), "This month is already on the bench.");
  assert.match(
    blockReason(bench, { kind: "car", car: { ...other, domain: "FILMTHICKNESS" } })!,
    /WaveScan/,
  );
});

test("changing the deck model carries available months and baseline to that model", () => {
  let bench = addCard(emptyBench(), month("2026-07"));
  bench = addCard(bench, month("2026-06"));
  bench = { ...bench, baseline: "2026-06" };
  const changed = retargetMonths(bench, "U704", ["2026-06", "2026-07"]);
  assert.equal(changed.model, "U704");
  assert.deepEqual(changed.months, ["2026-07", "2026-06"]);
  assert.equal(changed.baseline, "2026-06");
  assert.deepEqual(retargetMonths(bench, "U704", ["2026-07"]).months, ["2026-07"]);
  assert.equal(retargetMonths(bench, "U704", ["2026-07"]).baseline, null);
  assert.deepEqual(retargetMonths(bench, "U704", []), emptyBench());
});

test("toCsv quotes commas, quotes and newlines", () => {
  assert.equal(
    toCsv({
      columns: ["a", "b"],
      rows: [
        ["x,y", 'say "hi"'],
        [1, null],
      ],
    }),
    'a,b\r\n"x,y","say ""hi"""\r\n1,',
  );
});

test("film readings without measurement_id join per car and location", () => {
  const [a] = candidatesFor("FILMTHICKNESS");
  const points = (v: string) =>
    ({
      columns: [a],
      locations: [
        {
          point_no: 1,
          code: "001HOOD",
          orientation: "H",
          cells: [
            {
              vehicle_id: a.vehicle_id,
              missing: false,
              readings: [{ value: v, source_row: null, load_id: null }],
            },
          ],
        },
      ],
    }) as unknown as Points;
  const list = traces([
    { metric: "ecoat", points: points("20") },
    { metric: "clear", points: points("45") },
  ]);
  assert.equal(list.length, 1);
  assert.deepEqual(list[0].values, { ecoat: 20, clear: 45 });
  assert.equal(list[0].panel, "Hood");
});

test("locationStyles gives every location its own colour, then a new line pattern past eight", () => {
  const t = (n: number) => ({ location: `${n}-L${n}`, point_no: n, panel: "Door" }) as never;
  const s = locationStyles(Array.from({ length: 18 }, (_, i) => t(i + 1)));
  assert.deepEqual(s.get("1-L1"), { slot: 1, dash: undefined });
  assert.deepEqual(s.get("8-L8"), { slot: 8, dash: undefined });
  assert.deepEqual(s.get("9-L9"), { slot: 1, dash: "6 4" });
  assert.deepEqual(s.get("17-L17"), { slot: 1, dash: "2 3" });
  const styles = [...s.values()].map((v) => `${v.slot}|${v.dash}`);
  assert.equal(new Set(styles).size, 18);
});
