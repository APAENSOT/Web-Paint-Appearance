import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import * as T from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { acceleratedRaycast, computeBoundsTree } from "three-mesh-bvh";

test("accelerated Ranger picking preserves source geometry and nearest surface hits", async () => {
  const bytes = readFileSync(new URL("../public/models/ranger/ranger-body.glb", import.meta.url));
  const gltf = await new GLTFLoader().parseAsync(
    bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    "",
  );
  gltf.scene.updateMatrixWorld(true);
  const meshes: T.Mesh[] = [];
  gltf.scene.traverse((node) => {
    if (node instanceof T.Mesh) {
      node.material = new T.MeshBasicMaterial({ side: T.DoubleSide });
      meshes.push(node);
    }
  });
  const indices = meshes.map((mesh) => Array.from(mesh.geometry.index?.array ?? []));
  const rays = Array.from({ length: 196 }, (_, i) => {
    const angle = (i / 196) * Math.PI * 2;
    const origin = new T.Vector3(Math.cos(angle) * 8, 2 + (i % 7) * 0.3, Math.sin(angle) * 8);
    return new T.Raycaster(
      origin,
      new T.Vector3((i % 5) * 0.3 - 0.6, 1, 0).sub(origin).normalize(),
    );
  });
  const start = performance.now();
  const baseline = rays.map((ray) => ray.intersectObjects(meshes, false)[0]?.distance ?? null);
  const baselineMs = performance.now() - start;
  meshes.forEach((mesh) => {
    computeBoundsTree.call(mesh.geometry, { indirect: true });
    mesh.raycast = acceleratedRaycast;
  });
  rays.forEach((ray) => {
    ray.firstHitOnly = true;
  });
  const acceleratedStart = performance.now();
  const accelerated = rays.map((ray) => ray.intersectObjects(meshes, false)[0]?.distance ?? null);
  const acceleratedMs = performance.now() - acceleratedStart;
  baseline.forEach((distance, i) => {
    if (distance === null) assert.equal(accelerated[i], null);
    else assert.ok(Math.abs(distance - accelerated[i]!) < 1e-6);
  });
  meshes.forEach((mesh, i) =>
    assert.deepEqual(Array.from(mesh.geometry.index?.array ?? []), indices[i]),
  );
  console.log(
    `Ranger 196 surface rays: original ${baselineMs.toFixed(1)} ms; accelerated ${acceleratedMs.toFixed(1)} ms`,
  );
});
