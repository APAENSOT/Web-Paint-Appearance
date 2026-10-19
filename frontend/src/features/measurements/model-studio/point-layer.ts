import * as T from "three";
import { bodyZone, type BodyZoneId } from "./body-zones";
import {
  isPlacementClick,
  RANGER_ASSET_VERSION,
  type PointDraft,
  type StudioPoint,
  type SurfaceLocation,
} from "./point-placement";

// Raycast only the verified vehicle meshes, never the workshop or marker overlays.
export function pickBodySurface(
  camera: T.Camera,
  meshes: T.Mesh[],
  ndc: T.Vector2,
): SurfaceLocation | null {
  camera.updateMatrixWorld();
  meshes.forEach((mesh) => mesh.updateWorldMatrix(true, false));
  const ray = new T.Raycaster();
  ray.firstHitOnly = true;
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObjects(meshes, false)[0];
  if (!hit?.face || !(hit.object instanceof T.Mesh)) return null;
  const mesh = hit.object;
  const normal = hit.face.normal.clone();
  const worldNormal = normal
    .clone()
    .applyNormalMatrix(new T.Matrix3().getNormalMatrix(mesh.matrixWorld));
  if (worldNormal.dot(ray.ray.direction) > 0) normal.negate();
  const position = mesh.worldToLocal(hit.point.clone()).toArray();
  const zone = mesh.userData.bodyZone as BodyZoneId | undefined;
  return {
    zone: zone ?? bodyZone(mesh.name, position) ?? undefined,
    assetVersion: mesh.userData.assetVersion ?? RANGER_ASSET_VERSION,
    mesh: mesh.name,
    position,
    normal: normal.toArray(),
  };
}

export type PointLayerConfig = {
  readOnly?: boolean;
  points: StudioPoint[];
  draft: PointDraft;
  selected: string | null;
  armed: boolean;
  zone: BodyZoneId | null;
  visuals?: Record<
    string,
    { status: "PASS" | "WARNING" | "FAIL" | "OVER" | null; mean: string | null; unit: string }
  >;
  onZone: (zone: BodyZoneId) => void;
  onSelect: (key: string) => void;
  onPlace: (location: SurfaceLocation | null) => void;
  onMove: (key: string, location: SurfaceLocation) => void;
  onDragCancel: () => void;
};

export function createPointLayer(
  stage: HTMLDivElement,
  canvas: HTMLCanvasElement,
  camera: T.Camera,
  meshes: T.Mesh[],
  requestFrame: () => void,
  onManipulate: (dragging: boolean) => void = () => {},
  assetVersion: string = RANGER_ASSET_VERSION,
) {
  const overlay = document.createElement("div");
  overlay.className = "studio-point-overlay";
  stage.append(overlay);
  let config: PointLayerConfig | null = null;
  let markers: {
    point: StudioPoint;
    location: SurfaceLocation;
    button: HTMLButtonElement;
    localPosition: T.Vector3;
    localNormal: T.Vector3;
    world: T.Vector3;
    normal: T.Vector3;
    projected: T.Vector3;
    toCamera: T.Vector3;
    normalMatrix: T.Matrix3;
  }[] = [];
  let drag: {
    marker: (typeof markers)[number];
    original: SurfaceLocation;
    hit: SurfaceLocation | null;
    pointerId: number;
    start: { x: number; y: number };
    moved: boolean;
  } | null = null;
  function endDrag(commit: boolean) {
    const ended = drag;
    if (!ended) return;
    drag = null;
    ended.marker.button.classList.remove("is-dragging");
    if (ended.marker.button.hasPointerCapture(ended.pointerId))
      ended.marker.button.releasePointerCapture(ended.pointerId);
    onManipulate(false);
    if (commit && ended.moved && ended.hit) config?.onMove(ended.marker.point.key, ended.hit);
    else {
      ended.marker.location = ended.original;
      ended.marker.localPosition.fromArray(ended.original.position);
      ended.marker.localNormal.fromArray(ended.original.normal);
      if (ended.moved) config?.onDragCancel();
    }
    configure(config);
  }
  let down: { x: number; y: number; id: number } | null = null;
  let dragged = false;
  const active = new Set<number>();
  const occlusionRay = new T.Raycaster();
  occlusionRay.firstHitOnly = true;
  const rayDirection = new T.Vector3();
  const onDown = (event: PointerEvent) => {
    active.add(event.pointerId);
    if (active.size > 1) {
      dragged = true;
      return;
    }
    if (event.button !== 0) return;
    down = { x: event.clientX, y: event.clientY, id: event.pointerId };
    dragged = false;
  };
  const onMove = (event: PointerEvent) => {
    if (down && !isPlacementClick(down, { x: event.clientX, y: event.clientY })) dragged = true;
  };
  function pick(x: number, y: number) {
    if (!config) return;
    const location = pickBodySurface(camera, meshes, new T.Vector2(x * 2 - 1, 1 - y * 2));
    if (!config.armed) {
      if (location?.zone) config.onZone(location.zone);
      return;
    }
    config.onPlace(location && (!config.zone || location.zone === config.zone) ? location : null);
  }
  const onUp = (event: PointerEvent) => {
    active.delete(event.pointerId);
    const start = down;
    down = null;
    if (!start || start.id !== event.pointerId || dragged || !config) return;
    if (!isPlacementClick(start, { x: event.clientX, y: event.clientY })) return;
    const rect = canvas.getBoundingClientRect();
    pick((event.clientX - rect.left) / rect.width, (event.clientY - rect.top) / rect.height);
  };
  const cancel = (event: PointerEvent) => {
    active.delete(event.pointerId);
    down = null;
  };
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointercancel", cancel);
  function configure(next: PointLayerConfig | null) {
    if (
      drag &&
      (!next ||
        next.zone !== config?.zone ||
        !next.points.some((point) => point.key === drag?.marker.point.key))
    )
      endDrag(false);
    config = next;
    if (drag) return;
    overlay.replaceChildren();
    canvas.style.cursor = next?.armed ? "crosshair" : "grab";
    markers = [];
    for (const point of next?.points ?? []) {
      const location = next?.draft[point.key];
      if (!location || location.assetVersion !== assetVersion) continue;
      if (next?.zone && (location.zone ?? bodyZone(location.mesh, location.position)) !== next.zone)
        continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "studio-point-marker";
      const visual = next?.visuals?.[point.key];
      const statusText = visual?.status ? ` · ${visual.status}` : "";
      const meanText = visual?.mean ? ` · average ${visual.mean} ${visual.unit}` : "";
      button.setAttribute(
        "aria-label",
        `Select point ${point.number} · ${point.code}${meanText}${statusText}`,
      );
      button.setAttribute("aria-pressed", String(point.key === next?.selected));
      button.dataset.status = visual?.status ?? (visual?.mean ? "UNCLASSIFIED" : "NO_DATA");
      button.dataset.readOnly = String(Boolean(next?.readOnly));
      const label = document.createElement("span");
      const displayedMean = visual?.mean
        ? ` · Avg ${Number(visual.mean).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${visual.unit}`
        : "";
      label.textContent = `${point.number} · ${point.code}${displayedMean}${statusText}`;
      button.append(label);
      button.addEventListener("click", (event) => {
        if (config?.readOnly || event.detail === 0) config?.onSelect(point.key);
      });
      const marker = {
        point,
        location,
        button,
        localPosition: new T.Vector3(...location.position),
        localNormal: new T.Vector3(...location.normal),
        world: new T.Vector3(),
        normal: new T.Vector3(),
        projected: new T.Vector3(),
        toCamera: new T.Vector3(),
        normalMatrix: new T.Matrix3(),
      };
      button.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || drag || config?.readOnly) return;
        event.preventDefault();
        event.stopPropagation();
        button.focus({ preventScroll: true });
        drag = {
          marker,
          original: marker.location,
          hit: marker.location,
          pointerId: event.pointerId,
          start: { x: event.clientX, y: event.clientY },
          moved: false,
        };
        button.setPointerCapture(event.pointerId);
        button.classList.add("is-dragging");
        onManipulate(true);
        config?.onSelect(point.key);
      });
      button.addEventListener("pointermove", (event) => {
        if (!drag || drag.pointerId !== event.pointerId) return;
        if (!isPlacementClick(drag.start, { x: event.clientX, y: event.clientY }))
          drag.moved = true;
        if (!drag.moved) return;
        const rect = canvas.getBoundingClientRect();
        const hit = pickBodySurface(
          camera,
          meshes,
          new T.Vector2(
            ((event.clientX - rect.left) / rect.width) * 2 - 1,
            1 - ((event.clientY - rect.top) / rect.height) * 2,
          ),
        );
        drag.hit = hit && (!config?.zone || hit.zone === config.zone) ? hit : null;
        if (drag.hit) {
          marker.location = drag.hit;
          marker.localPosition.fromArray(drag.hit.position);
          marker.localNormal.fromArray(drag.hit.normal);
        }
        button.classList.toggle("is-outside", !drag.hit);
        requestFrame();
      });
      button.addEventListener("pointerup", (event) => {
        if (drag?.pointerId === event.pointerId) endDrag(true);
      });
      button.addEventListener("pointercancel", () => endDrag(false));
      button.addEventListener("lostpointercapture", () => endDrag(false));
      button.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          endDrag(false);
        }
      });
      overlay.append(button);
      markers.push(marker);
    }
    requestFrame();
  }
  return {
    pick,
    configure,
    render() {
      camera.updateMatrixWorld();
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      for (const marker of markers) {
        const { location, button, localPosition, localNormal, world, normal, projected, toCamera } =
          marker;
        const mesh = meshes.find((m) => m.name === location.mesh);
        if (!mesh) {
          button.hidden = true;
          continue;
        }
        button.hidden = false;
        world.copy(localPosition);
        mesh.localToWorld(world);
        normal
          .copy(localNormal)
          .applyNormalMatrix(marker.normalMatrix.getNormalMatrix(mesh.matrixWorld));
        world.addScaledVector(normal, 0.012);
        projected.copy(world).project(camera);
        const facesCamera = normal.dot(toCamera.subVectors(camera.position, world)) > 0;
        let obscured = false;
        if (facesCamera) {
          const distance = rayDirection.subVectors(world, camera.position).length();
          occlusionRay.set(camera.position, rayDirection.normalize());
          occlusionRay.far = Math.max(0, distance - 0.02);
          obscured = meshes.some(
            (surface) => occlusionRay.intersectObject(surface, false).length > 0,
          );
        }
        const hidden =
          !facesCamera ||
          obscured ||
          projected.z < -1 ||
          projected.z > 1 ||
          Math.abs(projected.x) > 0.96 ||
          Math.abs(projected.y) > 0.94;
        button.style.visibility = hidden ? "hidden" : "visible";
        if (!hidden)
          button.style.transform = `translate3d(${((projected.x + 1) * width) / 2}px, ${((1 - projected.y) * height) / 2}px, 0) translate(-50%, -50%)`;
      }
    },
    dispose() {
      endDrag(false);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", cancel);
      overlay.remove();
    },
  };
}
