import test from "node:test";
import assert from "node:assert/strict";
import * as T from "three";
import { readFileSync } from "node:fs";
import { splitBodyPanels } from "../src/features/measurements/model-studio/panel-geometry";
import { BODY_ZONES, bodyZone } from "../src/features/measurements/model-studio/body-zones";
import {
  filmStudioPoints,
  waveStudioPoints,
  isPlacementClick,
} from "../src/features/measurements/model-studio/point-placement";
import { pickBodySurface } from "../src/features/measurements/model-studio/point-layer";
import type { components } from "../src/api/types";

test("Standard identities stay exact and domain-separated, including uncounted points", () => {
  const wave: components["schemas"]["WsPointItem"] = {
    point_no: 1,
    zone_code: "Exact / Hood",
    label: "Exact / Hood",
    counted: false,
    tolerance_group: "Horizontal",
    is_extra: false,
    note: null,
    created_at: "2026-10-12T00:00:00Z",
    reason: null,
    changed_at: null,
    changed_by: null,
  };
  const film: components["schemas"]["FilmPointSettingItem"] = {
    point_no: 1,
    point_code: "Exact / Hood",
    label: "Exact / Hood",
    counted: false,
    orientation: "H",
    is_complete_stop: false,
    is_extra: false,
    reason: null,
    changed_at: null,
    changed_by: null,
  };
  const w = waveStudioPoints([wave])[0];
  const f = filmStudioPoints([film])[0];
  assert.equal(w.code, wave.zone_code);
  assert.equal(f.code, film.point_code);
  assert.notEqual(w.key, f.key);
  assert.equal(w.counted, false);
  assert.equal(f.counted, false);
  assert.equal(
    waveStudioPoints([{ ...wave, point_no: 12 }])[0].key,
    w.key,
    "Wave Scan identity is zone_code, not walk order",
  );
});

test("surface picking returns mesh-local coordinates, nearest panel, and misses empty space", () => {
  const camera = new T.PerspectiveCamera(40, 1, 0.1, 50);
  camera.position.set(0, 0, 10);
  camera.lookAt(0, 0, 0);
  const front = new T.Mesh(
    new T.PlaneGeometry(2, 2),
    new T.MeshBasicMaterial({ side: T.DoubleSide }),
  );
  front.name = "front-panel";
  front.position.z = 2;
  front.scale.set(2, 2, 2);
  const rear = new T.Mesh(new T.PlaneGeometry(2, 2), new T.MeshBasicMaterial());
  rear.name = "rear-panel";
  const hit = pickBodySurface(camera, [rear, front], new T.Vector2(0, 0));
  assert.equal(hit?.mesh, "front-panel");
  assert.deepEqual(hit?.position, [0, 0, 0]);
  assert.deepEqual(hit?.normal, [0, 0, 1]);
  assert.equal(pickBodySurface(camera, [front, rear], new T.Vector2(0.99, 0.99)), null);
  assert.equal(pickBodySurface(camera, [], new T.Vector2()), null, "no workshop fallback");
  front.geometry.dispose();
  rear.geometry.dispose();
  front.material.dispose();
  rear.material.dispose();
});

test("orbit drags are not placement clicks", () => {
  assert.equal(isPlacementClick({ x: 100, y: 100 }, { x: 102, y: 102 }), true);
  assert.equal(isPlacementClick({ x: 100, y: 100 }, { x: 120, y: 100 }), false);
});

test("every source triangle belongs to one focus region without altering asset-local anchors", () => {
  const bytes = readFileSync(new URL("../public/models/ranger/ranger-body.glb", import.meta.url));
  const jsonLength = bytes.readUInt32LE(12);
  const gltf = JSON.parse(bytes.subarray(20, 20 + jsonLength).toString());
  const binary = 28 + jsonLength;
  const material = new T.MeshBasicMaterial({ side: T.DoubleSide });
  const meshes: T.Mesh[] = gltf.meshes.map(
    (entry: {
      name: string;
      primitives: { attributes: { POSITION: number }; indices: number }[];
    }) => {
      const primitive = entry.primitives[0];
      const position = gltf.accessors[primitive.attributes.POSITION];
      const indices = gltf.accessors[primitive.indices];
      const positionOffset = binary + gltf.bufferViews[position.bufferView].byteOffset;
      const indexOffset = binary + gltf.bufferViews[indices.bufferView].byteOffset;
      const geometry = new T.BufferGeometry();
      geometry.setAttribute(
        "position",
        new T.Float32BufferAttribute(
          Array.from({ length: position.count * 3 }, (_, i) =>
            bytes.readFloatLE(positionOffset + i * 4),
          ),
          3,
        ),
      );
      geometry.setIndex(
        Array.from({ length: indices.count }, (_, i) => bytes.readUInt32LE(indexOffset + i * 4)),
      );
      const mesh = new T.Mesh(geometry, material);
      mesh.name = entry.name;
      return mesh;
    },
  );
  const groups = splitBodyPanels(meshes);
  assert.deepEqual([...groups.keys()].sort(), BODY_ZONES.map((zone) => zone.id).sort());
  const originalCount = meshes.reduce((sum, mesh) => sum + mesh.geometry.index!.count, 0);
  const subsetMeshes = [...groups.values()].flatMap((group) => group.children as T.Mesh[]);
  assert.equal(
    subsetMeshes.reduce((sum, mesh) => sum + mesh.geometry.getAttribute("position").count, 0),
    originalCount,
  );
  assert.ok(subsetMeshes.every((mesh) => meshes.some((original) => original.name === mesh.name)));
  const hood = groups.get("hood")!.children as T.Mesh[];
  const camera = new T.PerspectiveCamera(40, 1, 0.05, 50);
  camera.position.set(-1.7, 5, 0.001);
  camera.lookAt(-1.7, 1.3, 0);
  const hit = pickBodySurface(camera, hood, new T.Vector2());
  assert.equal(hit?.zone, "hood");
  assert.equal(hit?.mesh, "ranger-panel-5-Object006");
  assert.ok(hit && hit.position[0] < -1 && hit.position[1] > 1.2);
  camera.position.x = 0;
  camera.lookAt(0, 1.3, 0);
  assert.equal(
    pickBodySurface(camera, hood, new T.Vector2()),
    null,
    "isolated hood cannot hit cab geometry",
  );
  assert.equal(bodyZone("unregistered-mesh", [0, 0, 0]), null, "no guessed fallback zone");
  [...meshes, ...subsetMeshes].forEach((mesh) => mesh.geometry.dispose());
  material.dispose();
});
