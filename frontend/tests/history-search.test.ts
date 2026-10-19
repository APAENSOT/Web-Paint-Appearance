import { strict as assert } from "node:assert";
import { test } from "node:test";
import { parsePlantSearch } from "../src/features/measurements/history-search.ts";

test("Model Detail views are validated; legacy model and point links remain readable", () => {
  for (const modelView of ["model", "point-check", "colours", "inspection"] as const)
    assert.equal(parsePlantSearch({ modelView }).modelView, modelView);
  assert.equal(parsePlantSearch({ modelView: "notes" }).modelView, undefined);
  assert.equal(parsePlantSearch({ standardView: "points" }).standardView, "points");
  assert.equal(parsePlantSearch({ standardView: "model" }).standardView, "model");
});

test("History search preserves upload aliases and valid drill state", () => {
  const hash = "a".repeat(64);
  assert.deepEqual(
    parsePlantSearch({
      dataView: "measurements",
      file: hash,
      sheet: "12",
      month: "2026-09",
      model: "P703",
      color: "White",
      week: "5",
      vehicle: hash,
    }),
    {
      dataView: "history",
      standardView: undefined,
      file: hash,
      sheet: 12,
      month: "2026-09",
      model: "P703",
      color: "White",
      cardModel: undefined,
      cardColor: undefined,
      week: 5,
      vehicle: hash,
      dataDomain: undefined,
      paint: undefined,
      filmMonth: undefined,
      filmModel: undefined,
      filmColor: undefined,
      filmColors: undefined,
      filmWeek: undefined,
      filmCardModel: undefined,
      filmCardColor: undefined,
      filmVehicle: undefined,
      compare: undefined,
    },
  );
});
test("Film search keeps its own month, model, color and logical vehicle", () => {
  const hash = "d".repeat(64);
  const search = parsePlantSearch({
    paint: "film",
    filmMonth: "2026-08",
    filmModel: "P703 DBL RANGER",
    filmColor: "Blue",
    filmVehicle: hash,
    month: "2026-09",
    vehicle: "a".repeat(64),
  });
  assert.equal(search.paint, "film");
  assert.equal(search.filmMonth, "2026-08");
  assert.equal(search.filmModel, "P703 DBL RANGER");
  assert.equal(search.filmColor, "Blue");
  assert.equal(search.filmVehicle, hash);
  assert.equal(search.month, "2026-09");
  assert.equal(search.vehicle, "a".repeat(64));
  assert.equal(parsePlantSearch({ filmMonth: "2026-13", filmVehicle: "bad" }).filmMonth, undefined);
});
test("Data domain is independent of History and overview search keys", () => {
  const hash = "a".repeat(64);
  const search = parsePlantSearch({
    dataDomain: "film",
    paint: "film",
    filmMonth: "2026-08",
    month: "2026-09",
    vehicle: hash,
  });
  assert.equal(search.dataDomain, "film");
  assert.equal(search.paint, "film");
  assert.equal(search.filmMonth, "2026-08");
  assert.equal(search.month, "2026-09");
  assert.equal(search.vehicle, hash);
  assert.equal(parsePlantSearch({ dataDomain: "unknown" }).dataDomain, undefined);
});
test("History search rejects malformed drill state without inventing filters", () => {
  const search = parsePlantSearch({
    month: "bad",
    model: [],
    color: "",
    week: 6,
    vehicle: "fake",
    file: "fake",
    sheet: -1,
  });
  assert.equal(search.month, undefined);
  assert.equal(search.week, undefined);
  assert.equal(search.vehicle, undefined);
  assert.equal(search.model, undefined);
  assert.equal(search.color, undefined);
});
test("Calendar-shaped invalid month reaches API validation envelope", () => {
  assert.equal(parsePlantSearch({ month: "2026-13" }).month, "2026-13");
  assert.equal(parsePlantSearch({ dataView: "files" }).dataView, "upload");
});
test("Plant search keeps Color Family and Model as Standard children", () => {
  assert.equal(parsePlantSearch({ standardView: "family" }).standardView, "family");
  assert.equal(parsePlantSearch({ standardView: "model" }).standardView, "model");
  assert.equal(parsePlantSearch({ standardView: "upload" }).standardView, undefined);
});

test("T70 Film multi-colour arrays take precedence, ignore invalid items and retain canonical identities", () => {
  const parsed = parsePlantSearch({
    filmColors: ["Blue", "Absolute / Shadow Black", "Blue", null, 4, "", "   "],
    filmColor: "Legacy",
    color: "History",
    model: "Other",
  });
  assert.deepEqual(parsed.filmColors, ["Blue", "Absolute / Shadow Black"]);
  assert.equal(parsed.color, "History");
  assert.equal(parsed.model, "Other");
  assert.equal(parsed.filmColor, "Legacy");
  assert.equal(
    parsePlantSearch({ filmColors: [null, ""], filmColor: "Blue" }).filmColors,
    undefined,
  );
  assert.equal(parsePlantSearch({ filmColors: "Blue,Red" }).filmColors, undefined);
});

test("T105 card params are their own search keys and never fall back to the filters", () => {
  const search = parsePlantSearch({
    month: "2026-09",
    model: "P703",
    color: "White",
    cardModel: "U704",
    cardColor: "Blue",
    week: "3",
  });
  assert.equal(search.model, "P703");
  assert.equal(search.color, "White");
  assert.equal(search.cardModel, "U704");
  assert.equal(search.cardColor, "Blue");
  assert.equal(search.week, 3);
  const bare = parsePlantSearch({ cardModel: "", cardColor: [] });
  assert.equal(bare.cardModel, undefined);
  assert.equal(bare.cardColor, undefined);
  assert.equal(bare.model, undefined);
  assert.equal(bare.color, undefined);
});

test("T108 Film card params are Film's own keys, independent of every filter", () => {
  const search = parsePlantSearch({
    month: "2026-08",
    model: "P703",
    color: "White",
    week: "2",
    cardModel: "U704",
    cardColor: "Blue",
    filmWeek: "4",
    filmCardModel: "P703 DBL RANGER",
    filmCardColor: "Arctic White",
  });
  // Wave Scan's card, Film's card and the two filters are four separate
  // things: opening one card may not move any of the others (D-108-3).
  assert.equal(search.model, "P703");
  assert.equal(search.color, "White");
  assert.equal(search.week, 2);
  assert.equal(search.cardModel, "U704");
  assert.equal(search.cardColor, "Blue");
  assert.equal(search.filmWeek, 4);
  assert.equal(search.filmCardModel, "P703 DBL RANGER");
  assert.equal(search.filmCardColor, "Arctic White");
  // The same rules as T105's: a week is 0..5 (RO18), and empty or non-string is
  // nothing. Film's card never falls back to a filter -- before T108 there
  // were no Film cards, so there are no old links to keep working.
  const bad = parsePlantSearch({
    model: "P703",
    color: "White",
    filmWeek: "6",
    filmCardModel: "",
    filmCardColor: [],
  });
  assert.equal(bad.filmWeek, undefined);
  assert.equal(bad.filmCardModel, undefined);
  assert.equal(bad.filmCardColor, undefined);
  // RO18 (B4): week 0 is the "Day not recorded" group, a real card.
  assert.equal(parsePlantSearch({ filmWeek: "0" }).filmWeek, 0);
  assert.equal(parsePlantSearch({ week: "" }).week, undefined);
  assert.equal(parsePlantSearch({ filmWeek: 5 }).filmWeek, 5);
});
