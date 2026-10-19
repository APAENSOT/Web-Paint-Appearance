import assert from "node:assert/strict";
import { test } from "node:test";
import type { components } from "../src/api/types";
import { carLine, vehicleTitle } from "../src/features/measurements/review-copy";

const car: components["schemas"]["VehicleSetOut"] = {
  vehicle_id: "b188b711",
  load_id: 235150,
  plant_code: "FVL",
  measured_date: "2004-08-04",
  date_is_month_only: false,
  model: "CX743",
  color: "Absolute / Shadow Black",
  serial_no: null,
  identity_complete: true,
  point_count: 32,
  expected_point_count: 32,
  incomplete_set: false,
  dispositions: { load: 32, duplicate: 0, reject: 0, quarantine: 0 },
  car_label: "car 2 of 5 that day · from row 34",
};

test("D-RO17-17: a same-day car with no serial is titled by its car label", () => {
  assert.equal(vehicleTitle(car), "car 2 of 5 that day · from row 34");
  assert.equal(carLine(car, vehicleTitle(car)), null);
});

test("D-RO17-17: a serial still wins; the car label becomes its own line", () => {
  const serial = { ...car, serial_no: "2497809" };
  assert.equal(vehicleTitle(serial), "2497809");
  assert.equal(carLine(serial, vehicleTitle(serial)), "car 2 of 5 that day · from row 34");
  const incomplete = { ...car, identity_complete: false };
  assert.equal(vehicleTitle(incomplete), "Identity incomplete");
  assert.equal(carLine(incomplete, "Identity incomplete"), "car 2 of 5 that day · from row 34");
});

test("D-RO17-17: every other card is unchanged", () => {
  const other = { ...car, car_label: null };
  assert.equal(vehicleTitle(other), "CX743 · Absolute / Shadow Black · 2004-08-04");
  assert.equal(carLine(other, vehicleTitle(other)), null);
});
