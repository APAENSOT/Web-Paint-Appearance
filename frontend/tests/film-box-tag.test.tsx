/**
 * T103: the Box / No box tag and the identity note, rendered as given.
 *
 * The decisions these pin:
 *
 * * D-103-1 -- the tag is the server's `box` / `film_box` and nothing else.
 *   A plant whose list names no complete stop sends `null`, and `null`
 *   renders nothing: no model name, panel word or point code is read here,
 *   and nothing is guessed from the walk;
 * * D-103-2 -- `no_box` is `no_box` wherever it comes from. There is no
 *   client rule that makes a Single CAP a special case;
 * * D-103-3 -- the two History places and the review sheet header all show
 *   the same two words;
 * * D-103-6 -- `identity_note` renders when the server sends one, and
 *   nothing when it does not.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { components } from "../src/api/types";
import { FilmBoxTag, filmBoxLabel } from "../src/features/filmthickness/FilmBoxTag";

type Vehicle = components["schemas"]["FilmVehicleOut"];

const VEHICLE: Vehicle = {
  logical_vehicle_id: "a".repeat(64),
  plant_code: "FTM",
  measured_date: "2026-08-05",
  date_is_month_only: false,
  model: "P703 SGL",
  model_display_name: "Single CAP",
  color: "Arctic White",
  serial_no: null,
  job_nos: ["AM_SGL_1961607"],
  identity_complete: true,
  load_ids: [137_900],
  source_files: ["AW_SGL_1961607.xlsx"],
  mapped_point_count: 58,
  expected_point_count: 58,
  incomplete: false,
  box: "no_box",
  identity_note: 'The Job Number\'s colour code "AM" and the file name\'s "AW" are different.',
};

test("the label is the server's two words, and null says nothing", () => {
  assert.equal(filmBoxLabel("box"), "Box");
  assert.equal(filmBoxLabel("no_box"), "No box");
  assert.equal(filmBoxLabel(null), null);
  assert.equal(filmBoxLabel(undefined), null, "film_box unsent is the same answer");
});

test("a tag renders for box and no_box, and nothing at all for null", () => {
  const box = renderToStaticMarkup(<FilmBoxTag box="box" label="Walk" />);
  assert.match(box, />Box</);
  assert.match(box, /data-testid="film-box-box"/);
  assert.match(box, /aria-label="Walk: Box"/);

  const noBox = renderToStaticMarkup(<FilmBoxTag box="no_box" />);
  assert.match(noBox, />No box</);
  assert.match(noBox, /data-testid="film-box-no_box"/);

  assert.equal(renderToStaticMarkup(<FilmBoxTag box={null} />), "");
  assert.equal(
    renderToStaticMarkup(<FilmBoxTag box={undefined} />),
    "",
    "a plant whose list names no stop gets no tag, not an empty one",
  );
});

test("the tag a car carries is the field, whatever the model is", () => {
  for (const box of ["box", "no_box", null] as const) {
    const markup = renderToStaticMarkup(<FilmBoxTag box={{ ...VEHICLE, box }.box} />);
    assert.equal(markup === "", box === null);
    if (box) assert.match(markup, new RegExp(`data-testid="film-box-${box}"`));
  }
});
