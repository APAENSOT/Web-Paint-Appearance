import assert from "node:assert/strict";
import test from "node:test";
import {
  filterProfiles,
  profilePhoto,
  sampleRows,
} from "../src/features/measurements/monthly-detail/display.ts";

test("profile search and filters preserve exact model and colour combinations", () => {
  const items = [
    {
      profile_id: "a",
      model_code: "P703 DBL RANGER",
      color_name: "Blue Lightning",
      family_name: "Dark Metallics",
      sample_count: 3,
      domain: "wavescan",
      is_offered: true,
    },
    {
      profile_id: "b",
      model_code: "P703 DBL RAPTOR",
      color_name: "Blue Lightning",
      family_name: "Dark Metallics",
      sample_count: 0,
      domain: "wavescan",
      is_offered: true,
    },
  ] as const;
  assert.deepEqual(
    filterProfiles([...items], {
      query: "blue",
      models: ["P703 DBL RANGER"],
      colors: [],
      family: "",
      measuredOnly: false,
    }).map((p) => p.profile_id),
    ["a"],
  );
  assert.equal(
    filterProfiles([...items], {
      query: "",
      models: [],
      colors: [],
      family: "",
      measuredOnly: false,
    }).length,
    2,
  );
  assert.equal(
    filterProfiles([...items], {
      query: "",
      models: [],
      colors: [],
      family: "",
      measuredOnly: true,
    }).length,
    1,
  );
  assert.equal(profilePhoto("CX743")?.src, "territory.png"); // owner's CX743 photo, never Escape
  assert.equal(profilePhoto("CX482"), null);
  assert.equal(profilePhoto("P703 SGL")!.src, "ranger.png");
  assert.equal(profilePhoto("P703 RAPCAP")!.src, "ranger.png");
});

test("progression keeps duplicates and zero, with explicit missing sample slots", () => {
  const samples = [
    {
      vehicle_id: "one",
      measured_date: "2026-09-01",
      serial_no: null,
      readings: [
        { value: "0.000", source_row: 1, load_id: 2 },
        { value: "61.123456789", source_row: 2, load_id: 2 },
      ],
    },
    { vehicle_id: "two", measured_date: "2026-09-01", serial_no: "ABC", readings: [] },
  ];
  const rows = sampleRows(samples);
  assert.equal(rows.length, 3);
  assert.deepEqual(
    rows.map((r) => r.value),
    ["0.000", "61.123456789", null],
  );
  assert.equal(rows[2].sample, 2);
  assert.equal(rows[0].vehicleId, "one");
});
