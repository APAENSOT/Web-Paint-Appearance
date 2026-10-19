import * as T from "three";
import { bodyZone, type BodyZoneId } from "./body-zones";

// Retain original mesh names and local vertices for durable surface anchors.
// These display-only subsets never replace or renumber the source GLB.
export function splitBodyPanels(meshes: T.Mesh[]) {
  const groups = new Map<BodyZoneId, T.Group>();
  for (const source of meshes) {
    const index = source.geometry.index;
    if (!index) continue;
    const positions = source.geometry.getAttribute("position");
    const indices = new Map<BodyZoneId, number[]>();
    for (let i = 0; i < index.count; i += 3) {
      const face = [index.getX(i), index.getX(i + 1), index.getX(i + 2)];
      const center = [0, 0, 0];
      for (const vertex of face) {
        center[0] += positions.getX(vertex) / 3;
        center[1] += positions.getY(vertex) / 3;
        center[2] += positions.getZ(vertex) / 3;
      }
      const zone = bodyZone(source.name, center);
      if (!zone) continue;
      if (!indices.has(zone)) indices.set(zone, []);
      indices.get(zone)!.push(...face);
    }
    for (const [zone, triangles] of indices) {
      const geometry = new T.BufferGeometry();
      // Clone attributes so subset bounds include only referenced vertices and
      // disposal never frees GPU buffers still owned by the original geometry.
      for (const name of Object.keys(source.geometry.attributes)) {
        const attribute = source.geometry.getAttribute(name);
        const values = new Float32Array(triangles.length * attribute.itemSize);
        triangles.forEach((vertex, i) => {
          for (let c = 0; c < attribute.itemSize; c++)
            values[i * attribute.itemSize + c] = attribute.getComponent(vertex, c);
        });
        geometry.setAttribute(name, new T.BufferAttribute(values, attribute.itemSize));
      }
      geometry.computeBoundingBox();
      geometry.computeBoundingSphere();
      const panel = new T.Mesh(geometry, source.material);
      panel.name = source.name;
      panel.userData.bodyZone = zone;
      source.updateWorldMatrix(true, false);
      panel.applyMatrix4(source.matrixWorld);
      panel.castShadow = true;
      panel.receiveShadow = true;
      if (!groups.has(zone)) groups.set(zone, new T.Group());
      groups.get(zone)!.add(panel);
    }
  }
  return groups;
}
