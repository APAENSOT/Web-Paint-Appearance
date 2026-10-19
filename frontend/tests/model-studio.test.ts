import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { displayShade, studioColors } from "../src/features/measurements/model-studio/catalogue";
import { catalogueFixture } from "./fixtures";

test("studio offers only this plant's Standard colours, preserving exact identities", () => {
  const colors = studioColors(
    {
      ...catalogueFixture,
      colors: [
        {
          color_name: "Exact / Canonical",
          color_group: "BLUE",
          plants: [{ plant_code: "FTM", is_offered: true, family_code: "MM" }],
        },
        {
          color_name: "Other plant",
          color_group: "RED",
          plants: [{ plant_code: "AAT", is_offered: true }],
        },
        {
          color_name: "Retired",
          color_group: "WHITE",
          plants: [{ plant_code: "FTM", is_offered: false }],
        },
      ],
    },
    "FTM",
  );
  assert.deepEqual(
    colors.map((c) => c.color_name),
    ["Exact / Canonical"],
  );
  assert.equal(colors[0].plants[0].family_code, "MM");
});

test("unknown display groups stay unassigned; grading families are not paint colours", () => {
  assert.equal(displayShade(null), null);
  assert.equal(displayShade("UNRECOGNISED"), null);
  assert.equal(displayShade("DM"), null);
  assert.match(displayShade("BLUE") ?? "", /^#[a-f0-9]{6}$/);
});

test("shipping asset is bounded GLB geometry with panels and no external resources", () => {
  const bytes = readFileSync(new URL("../public/models/ranger/ranger-body.glb", import.meta.url));
  assert.equal(bytes.readUInt32LE(0), 0x46546c67);
  assert.equal(bytes.readUInt32LE(8), bytes.length);
  assert.ok(bytes.length < 2_000_000);
  const json = JSON.parse(bytes.subarray(20, 20 + bytes.readUInt32LE(12)).toString());
  assert.equal(json.meshes.length, 11);
  assert.equal(json.images, undefined);
  assert.equal(json.buffers[0].uri, undefined);
  assert.ok(
    json.meshes.every(
      (m: { name: string }) => m.name.startsWith("ranger-") && !m.name.includes("Object007"),
    ),
  );
  const triangles = json.meshes.reduce(
    (sum: number, m: { primitives: { indices: number }[] }) =>
      sum + json.accessors[m.primitives[0].indices].count / 3,
    0,
  );
  assert.ok(triangles > 50_000 && triangles < 60_000);
  const pillars = json.meshes.filter((m: { name: string }) =>
    m.name.startsWith("ranger-b-pillar-"),
  );
  assert.equal(pillars.length, 2);
  for (const pillar of pillars) {
    const a = json.accessors[pillar.primitives[0].attributes.POSITION];
    assert.ok(a.min[0] > 0.09 && a.max[0] < 0.32);
    assert.ok(a.min[1] < 1.4 && a.max[1] > 1.79);
    assert.ok(a.min[2] * a.max[2] > 0, "each pillar stays on its own side of the cab");
    const positionView = json.bufferViews[a.bufferView];
    const binOffset = 28 + bytes.readUInt32LE(12);
    const normals = json.accessors[pillar.primitives[0].attributes.NORMAL];
    const normalView = json.bufferViews[normals.bufferView];
    assert.equal(a.count, normals.count);
    for (let i = 0; i < a.count * 3; i++) {
      assert.ok(Number.isFinite(bytes.readFloatLE(binOffset + positionView.byteOffset + i * 4)));
      assert.ok(Number.isFinite(bytes.readFloatLE(binOffset + normalView.byteOffset + i * 4)));
    }
  }
  assert.ok(pillars.some((m: { name: string }) => m.name.endsWith("positive-z")));
  assert.ok(pillars.some((m: { name: string }) => m.name.endsWith("negative-z")));
  for (const a of json.accessors.filter((a: { min?: number[] }) => a.min)) {
    assert.ok(a.min.every(Number.isFinite) && a.max.every(Number.isFinite));
    assert.ok(a.min[0] >= -3 && a.max[0] <= 3);
  }
});
