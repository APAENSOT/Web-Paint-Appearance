import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  PREPARED_BODIES,
  PREPARED_BODY_VERSION,
  CX743_BODY_VERSION,
} from "../src/features/measurements/model-studio/body-assets";
const root = new URL("../public/models/prepared/", import.meta.url);
const entries = JSON.parse(readFileSync(new URL("manifest.json", root), "utf8"));
test("Studio uses exact Standard model identities and the current packaged asset version", () => {
  assert.equal(PREPARED_BODIES["P703"], undefined);
  assert.equal(
    PREPARED_BODIES["P703 DBL RANGER"],
    undefined,
    "accepted Ranger keeps its original surface registration",
  );
  assert.equal(PREPARED_BODIES["P703 SGL"].id, "ranger-sgl");
  assert.equal(PREPARED_BODIES["P703 RAPCAP"].id, "ranger-rapcap");
  assert.equal(PREPARED_BODIES["P703 DBL SUPER DUTY"].id, "super-duty");
  for (const asset of Object.values(PREPARED_BODIES)) {
    const entry = entries.find((item: { id: string }) => item.id === asset.id);
    assert.ok(entry);
    assert.equal(
      entry.version,
      asset.id === "territory" ? CX743_BODY_VERSION : PREPARED_BODY_VERSION,
    );
    assert.equal(asset.url, `${entry.url}?v=${entry.version}`);
  }
});
for (const entry of entries) {
  test(`${entry.id}: registered surface has stable, local, finite geometry and exact model identity`, () => {
    const registered = Object.entries(PREPARED_BODIES).find(([, asset]) => asset.id === entry.id)!;
    assert.equal(entry.inspectionReady, true);
    assert.equal(entry.canonicalModelCode, registered[0]);
    assert.equal(entry.assetVersion, registered[1].assetVersion);
    assert.equal(entry.status, "registered");
    const data = readFileSync(new URL(entry.url.split("/").pop(), root));
    assert.equal(data.length, entry.bytes);
    assert.equal(createHash("sha256").update(data).digest("hex"), entry.sha256);
    assert.equal(data.readUInt32LE(0), 0x46546c67);
    assert.equal(data.readUInt32LE(4), 2);
    assert.equal(data.readUInt32LE(8), data.length);
    const length = data.readUInt32LE(12);
    const gltf = JSON.parse(data.subarray(20, 20 + length).toString());
    assert.ok(
      !gltf.images?.length && !gltf.textures?.length,
      "shells ship without original textures",
    );
    assert.equal(gltf.meshes.length, entry.meshes);
    assert.equal(
      new Set(gltf.nodes.map((node: { name: string }) => node.name)).size,
      gltf.nodes.length,
    );
    assert.ok(entry.bytes < 5_000_000 && entry.meshes <= 16);
    let triangles = 0;
    for (const mesh of gltf.meshes)
      for (const primitive of mesh.primitives) {
        const accessor = gltf.accessors[primitive.attributes.POSITION];
        assert.ok(accessor.min.every(Number.isFinite) && accessor.max.every(Number.isFinite));
        assert.ok(accessor.min.every((value: number) => Math.abs(value) < 10));
        assert.ok(accessor.max.every((value: number) => Math.abs(value) < 10));
        const view = gltf.bufferViews[accessor.bufferView];
        const start = 28 + length + (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
        for (let i = 0; i < accessor.count; i++)
          for (let axis = 0; axis < 3; axis++) {
            assert.ok(
              Number.isFinite(data.readFloatLE(start + i * (view.byteStride ?? 12) + axis * 4)),
            );
          }
        triangles += gltf.accessors[primitive.indices].count / 3;
      }
    assert.equal(triangles, entry.triangles);
  });
}
