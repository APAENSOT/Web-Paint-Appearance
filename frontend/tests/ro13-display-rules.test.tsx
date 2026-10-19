/**
 * RO13 Part B: the small display faults, each fixed as a rule (never a plant
 * code). Stored values are unchanged; only what is shown changes.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { components } from "../src/api/types";
import { FilmCardButton } from "../src/features/filmthickness/FilmThickness";
import {
  boxDescription,
  noOutsideLimitText,
} from "../src/features/filmthickness/film-overview-display";
import { FilmBoxSummary } from "../src/features/filmthickness/FilmBoxSummary";
import { modelVocabularyNote } from "../src/features/measurements/history-search";
import { UploadedAt } from "../src/features/measurements/files-shared";
import { vehicleTitle } from "../src/features/measurements/review-copy";
import {
  wavescanDescription,
  wavescanMeasure,
  wavescanPrimary,
} from "../src/features/measurements/wavescan-inspection";
import { filmBox } from "./film-overview-fixtures";
import { wavescanClickFixture } from "./wavescan-click-fixtures";

test("F6: a float32 artefact shows as the shortest decimal that reads back to it", () => {
  assert.equal(wavescanMeasure("63.9000015258789"), "63.9");
  assert.equal(wavescanMeasure("4.40000009536743"), "4.4");
  assert.equal(wavescanMeasure("57"), "57");
});

test("F6: any other value shows exactly as stored", () => {
  // 51.3 written as decimal is not float32's 51.29999923706055: shown as stored.
  assert.equal(wavescanMeasure("51.3"), "51.3");
  assert.equal(wavescanMeasure("63.90"), "63.90");
  assert.equal(wavescanMeasure("62.123456789012345"), "62.123456789012345");
  assert.equal(wavescanMeasure("2.000000000000000000001"), "2.000000000000000000001");
  assert.equal(wavescanMeasure("not a number"), "not a number");
});

test("F6: a box's aria text says exactly what its visible numbers say", () => {
  const box = { ...wavescanClickFixture.boxes[0], mean: "60.69997914632162380952380952" };
  const description = wavescanDescription(box);
  for (const field of wavescanPrimary(box)) {
    if (field.raw != null) assert.ok(description.includes(`${field.label}: ${field.display} CF`));
  }
  assert.match(description, /Average: 60\.7 CF/);
  assert.doesNotMatch(description, /60\.6999/);
});

const card: components["schemas"]["FilmCardOut"] = {
  model: "P703 DBL RANGER",
  model_display_name: null,
  color: "Command Grey",
  vehicle_count: 1,
  point_count: 376,
  box_count: 0,
  no_box_count: 0,
  incomplete_count: 0,
  measured_date_min: "2026-09-01",
  measured_date_max: "2026-09-01",
};

test("F7: a Film card hides Box / No box when the list names no stop", () => {
  const html = renderToStaticMarkup(<FilmCardButton card={card} onOpen={() => {}} />);
  assert.doesNotMatch(html, /Box 0|No box 0/);
  assert.match(html, /Incomplete 0/);
  const tagged = renderToStaticMarkup(
    <FilmCardButton card={{ ...card, box_count: 1, no_box_count: 0 }} onOpen={() => {}} />,
  );
  assert.match(tagged, /Box 1/);
  assert.match(tagged, /No box 0/);
});

test("F8: the vocabulary note appears only when a Film model is not a Wave Scan model, naming them", () => {
  // AAT's shape: every Film model is also a Wave Scan model.
  assert.equal(
    modelVocabularyNote(
      ["P703 DBL RANGER", "P703 DBL SUPER DUTY", "U704"],
      ["P703 DBL RANGER", "U704"],
    ),
    null,
  );
  // FTM's shape: the domains name the same truck differently.
  const note = modelVocabularyNote(["P703"], ["P703 DBL RANGER", "P703 DBL RAPTOR"]);
  assert.ok(note);
  assert.match(note, /Film: P703 DBL RANGER, P703 DBL RAPTOR; Wave Scan: P703/);
  assert.equal(modelVocabularyNote([], ["U704"]), null);
  assert.equal(modelVocabularyNote(undefined, undefined), null);
});

test("F9: a No standard box says there is no limit check, in its summary and aria text", () => {
  const none = filmBox({ standard_scope: "NONE", lo: null, status: null, out_of_spec: [] });
  assert.equal(noOutsideLimitText(none), "No standard, so no limit check");
  assert.match(boxDescription(none), /Outside-limit readings: No standard, so no limit check\./);
  const html = renderToStaticMarkup(<FilmBoxSummary box={none} close={() => {}} />);
  assert.match(html, /No standard, so no limit check\./);
  assert.doesNotMatch(html, /No readings outside the published limits/);
  const ruled = filmBox();
  assert.equal(noOutsideLimitText(ruled), "No readings outside the published limits");
});

test("F10: the upload line is a readable date and time, with no raw timestamp or id", () => {
  const html = renderToStaticMarkup(<UploadedAt uploadedAt="2026-10-12T19:58:23.456518+07:00" />);
  assert.match(html, /Uploaded <time dateTime="2026-10-12T19:58:23.456518\+07:00">/);
  assert.match(html, /Oct 2026/);
  assert.doesNotMatch(html, />[^<]*T19:58:23/);
  assert.doesNotMatch(html, /0a295830|fixture-admin/);
});

test("F13: shared plant workspace excludes plant-specific prototype cards", () => {
  const source = readFileSync(
    new URL("../src/features/measurements/PlantMeasurements.tsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(source, /label === "FTM"|liveContent|ModelPicker|BlankPlantContent/);
});

const filmSet: components["schemas"]["VehicleSetOut"] = {
  vehicle_id: "a".repeat(64),
  load_id: 123,
  plant_code: "AAT",
  measured_date: "2026-08-20",
  date_is_month_only: false,
  model: "P703 DBL RANGER",
  color: "Command Grey",
  serial_no: null,
  identity_complete: true,
  point_count: 94,
  expected_point_count: 94,
  incomplete_set: false,
  dispositions: { load: 94, duplicate: 0, reject: 0, quarantine: 0 },
};

test("R11a: a set with no serial is titled model · colour · date; a serial still wins", () => {
  assert.equal(vehicleTitle(filmSet), "P703 DBL RANGER · Command Grey · 2026-08-20");
  assert.equal(vehicleTitle({ ...filmSet, serial_no: "2497809" }), "2497809");
  assert.equal(vehicleTitle({ ...filmSet, identity_complete: false }), "Identity incomplete");
});
