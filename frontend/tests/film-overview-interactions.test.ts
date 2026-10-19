import assert from "node:assert/strict";
import test from "node:test";
import {
  measuredDate,
  readingSide,
  boxDescription,
  filmDomain,
} from "../src/features/filmthickness/film-overview-display";
import { filmBox } from "./film-overview-fixtures";
test("T70 calendar date display is date-only and nullable", () => {
  assert.equal(measuredDate("2026-08-25"), "25 Aug 2026");
  assert.equal(measuredDate("2026-01-01"), "1 Jan 2026");
  assert.equal(measuredDate(null), "Date unavailable");
});
test("T70 readable sides and descriptions keep exact values without hashes or implementation codes", () => {
  const box = filmBox({
    out_of_spec: [
      {
        value: "14.12345678901234567",
        side: "LOW",
        point_code: "HOOD",
        logical_vehicle_id: "a".repeat(64),
        measured_date: "2026-08-25",
      },
    ],
  });
  assert.equal(readingSide(box, box.out_of_spec[0]), "Below minimum");
  assert.equal(
    readingSide({ ...box, lo_label: "No point below" }, box.out_of_spec[0]),
    "Below No point below",
  );
  assert.equal(readingSide(box, { ...box.out_of_spec[0], side: "HIGH" }), "Above maximum");
  const description = boxDescription(box);
  assert.ok(description.includes("25 Aug 2026"));
  assert.ok(description.includes("14.12345678901234567"));
  assert.ok(!description.includes("a".repeat(64)));
  assert.ok(!description.includes("PLANT"));
});
test("T70 unplotted reading values do not expand the statistical domain", () => {
  const box = filmBox({
    out_of_spec: [
      {
        value: "9000",
        side: "HIGH",
        point_code: "A",
        logical_vehicle_id: "a",
        measured_date: null,
      },
    ],
  });
  assert.deepEqual(filmDomain([box]), filmDomain([{ ...box, out_of_spec: [] }]));
  assert.ok(filmDomain([filmBox({ target: "900" })])[1] > 900);
});
