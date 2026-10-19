import * as T from "three";
import { acceleratedRaycast, computeBoundsTree, disposeBoundsTree } from "three-mesh-bvh";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { buildWorkshop } from "./robots";
import { createPointLayer } from "./point-layer";
import { RANGER_ASSET_VERSION } from "./point-placement";
import { BODY_ZONES, type BodyZoneId } from "./body-zones";
import { splitBodyPanels } from "./panel-geometry";
import { FINISH_VALUES, type PaintFinish } from "./paint-finish";

export type StudioView =
  "workshop" | "body" | "front" | "rear" | "side" | "opposite" | "top" | "under";
export type StudioState = { status: string; ready: boolean; painting: boolean; error: boolean };
export type StudioScene = ReturnType<typeof createStudio>;
const views: Record<StudioView, [number, number, number]> = {
  workshop: [-8.5, 6.7, 10],
  body: [-5.4, 3.1, 6.1],
  front: [-8, 1, 0],
  rear: [8, 1, 0],
  side: [0, 1, 8.5],
  opposite: [0, 1, -8.5],
  top: [0, 9, 0.01],
  under: [0, -7, 0.01],
};

function disposeObject(root: T.Object3D) {
  const geometries = new Set<T.BufferGeometry>(),
    materials = new Set<T.Material>();
  root.traverse((node) => {
    if (node instanceof T.Mesh) {
      geometries.add(node.geometry);
      (Array.isArray(node.material) ? node.material : [node.material]).forEach((m) =>
        materials.add(m),
      );
    }
  });
  geometries.forEach((g) => {
    disposeBoundsTree.call(g);
    g.dispose();
  });
  materials.forEach((m) => m.dispose());
}

/** Asset review uses the same lighting, paint and robots without registering a point surface. */
export type StudioPreviewAsset = { url: string; label: string; assetVersion?: string };
export function createStudio(
  stage: HTMLDivElement,
  notify: (state: StudioState) => void,
  previewAsset?: StudioPreviewAsset,
) {
  const assetLabel = previewAsset?.label ?? "Ranger";
  const renderer = new T.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  const restingPixelRatio = Math.min(devicePixelRatio, 1.25);
  renderer.setPixelRatio(restingPixelRatio);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.82;
  const canvas = renderer.domElement;
  canvas.setAttribute("role", "img");
  canvas.setAttribute(
    "aria-label",
    `${assetLabel} exterior body with four fixed painting robots. Use view and zoom controls, or drag to orbit.`,
  );
  stage.append(canvas);
  const scene = new T.Scene(),
    camera = new T.PerspectiveCamera(34, 1, 0.05, 80);
  let previewBounds: T.Box3 | null = null;
  camera.position.set(...views.workshop);
  const controls = new OrbitControls(camera, canvas);
  controls.target.set(0, 1, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.1;
  controls.enablePan = false;
  controls.minDistance = 3.3;
  controls.maxDistance = 20;
  controls.maxPolarAngle = Math.PI * 0.95;
  const generator = new T.PMREMGenerator(renderer),
    room = new RoomEnvironment();
  const environment = generator.fromScene(room, 0.035);
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.6;
  room.dispose();
  generator.dispose();
  scene.add(new T.HemisphereLight(0xe0eeff, 0x4b5566, 1));
  const key = new T.DirectionalLight(0xfff5e8, 2.5);
  key.position.set(-4, 8, 5);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -6, right: 6, top: 6, bottom: -6, near: 0.1, far: 24 });
  key.shadow.normalBias = 0.025;
  scene.add(key);
  const rim = new T.DirectionalLight(0xb8d2ff, 1.8);
  rim.position.set(3, 5, -5);
  scene.add(rim);
  const workshop = buildWorkshop(scene);
  const material = new T.MeshPhysicalMaterial({
    color: 0xffffff,
    metalness: 0.45,
    roughness: 0.35,
    clearcoat: 0.25,
    side: T.DoubleSide,
  });
  const uniforms = {
    previous: { value: new T.Color("#d6dcdf") },
    next: { value: new T.Color("#d6dcdf") },
    previousFinish: { value: new T.Vector3(...FINISH_VALUES.unpainted) },
    nextFinish: { value: new T.Vector3(...FINISH_VALUES.unpainted) },
    amount: { value: 1 },
  };
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, {
      coatPrevious: uniforms.previous,
      coatNext: uniforms.next,
      coatPreviousFinish: uniforms.previousFinish,
      coatNextFinish: uniforms.nextFinish,
      coatAmount: uniforms.amount,
    });
    shader.vertexShader = "varying vec3 coatPosition;\n" + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace(
      "#include <begin_vertex>",
      "#include <begin_vertex>\ncoatPosition=(modelMatrix*vec4(position,1.0)).xyz;",
    );
    shader.fragmentShader =
      `varying vec3 coatPosition;
      uniform vec3 coatPrevious;uniform vec3 coatNext;
      uniform vec3 coatPreviousFinish;uniform vec3 coatNextFinish;uniform float coatAmount;
      float pigmentHash(vec3 p) {
        return fract(sin(dot(p,vec3(12.9898,78.233,37.719)))*43758.5453);
      }
      float pigmentNoise(vec3 p) {
        vec3 cell=floor(p), t=fract(p);
        t=t*t*(3.0-2.0*t);
        return mix(
          mix(mix(pigmentHash(cell),pigmentHash(cell+vec3(1,0,0)),t.x),
              mix(pigmentHash(cell+vec3(0,1,0)),pigmentHash(cell+vec3(1,1,0)),t.x),t.y),
          mix(mix(pigmentHash(cell+vec3(0,0,1)),pigmentHash(cell+vec3(1,0,1)),t.x),
              mix(pigmentHash(cell+vec3(0,1,1)),pigmentHash(cell+vec3(1,1,1)),t.x),t.y),t.z);
      }
      ` + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace(
      "#include <color_fragment>",
      `#include <color_fragment>
      float localX=coatPosition.x<.25?(coatPosition.x+2.5)/2.75:(coatPosition.x-.25)/2.6;
      float coverage=coatAmount>=1.0?1.0:1.0-smoothstep(coatAmount*1.22-.11,coatAmount*1.22+.03,localX);
      vec3 coatFinish=mix(coatPreviousFinish,coatNextFinish,coverage);
      diffuseColor.rgb=mix(coatPrevious,coatNext,coverage);
      // Pigment lives in the reflected finish, without white dots in the base colour.
      vec3 pigmentPosition=coatPosition*180.0;
      float footprint=max(length(dFdx(pigmentPosition)),length(dFdy(pigmentPosition)));
      float pigmentDetail=1.0-smoothstep(0.35,1.5,footprint);
      float pigment=(pigmentNoise(pigmentPosition)-0.5)*pigmentDetail;`,
    );
    shader.fragmentShader = shader.fragmentShader.replace(
      "#include <roughnessmap_fragment>",
      "#include <roughnessmap_fragment>\nroughnessFactor=clamp(coatFinish.y+pigment*coatFinish.z,0.18,1.0);",
    );
    shader.fragmentShader = shader.fragmentShader.replace(
      "#include <metalnessmap_fragment>",
      "#include <metalnessmap_fragment>\nmetalnessFactor=coatFinish.x;",
    );
  };
  let disposed = false,
    loaded = false,
    frame = 0,
    visible = true;
  let paintStart: number | null = null;
  let label = "Unpainted metal",
    phase = "";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  // User motion setting and the live OS preference remain independent.
  let motion = true;
  let tween: {
    from: T.Vector3;
    to: T.Vector3;
    start: number;
    targetFrom: T.Vector3;
    targetTo: T.Vector3;
    duration?: number;
    kind?: "zoom";
  } | null = null;
  const bodyMeshes: T.Mesh[] = [];
  const pickMeshes: T.Mesh[] = [];
  let panelGroups = new Map<BodyZoneId, T.Group>();
  let focusedZone: BodyZoneId | null = null;
  let cubeElement: HTMLDivElement | null = null;
  let draggingPoint = false;
  const pointLayer = createPointLayer(
    stage,
    canvas,
    camera,
    pickMeshes,
    requestFrame,
    (dragging) => {
      draggingPoint = dragging;
      controls.enabled = !dragging;
      if (dragging) tween = null;
      requestFrame();
    },
    previewAsset?.assetVersion ?? RANGER_ASSET_VERSION,
  );
  const emit = (status: string, error = false) => {
    if (disposed || status === phase) return;
    phase = status;
    notify({ status, ready: loaded, painting: paintStart !== null, error });
  };
  function requestFrame() {
    if (!disposed && visible && !document.hidden && !frame) frame = requestAnimationFrame(render);
  }
  function completePaint() {
    uniforms.amount.value = 1;
    uniforms.previous.value.copy(uniforms.next.value);
    uniforms.previousFinish.value.copy(uniforms.nextFinish.value);
    paintStart = null;
    workshop.park();
    emit(`${label} · Ready to inspect`);
    requestFrame();
  }
  function render(now: number) {
    frame = 0;
    if (disposed || !visible || document.hidden) return;
    if (paintStart !== null) {
      renderer.shadowMap.needsUpdate = true;
      const t = Math.min(1, (now - paintStart) / 4800);
      uniforms.amount.value = workshop.animate(t);
      if (t >= 1) completePaint();
      else
        emit(
          t < 0.14
            ? "Preparing paint pass"
            : t > 0.83
              ? "Arms returning to park"
              : `Painting ${label}`,
        );
    }
    if (tween) {
      const t = Math.min(1, (now - tween.start) / (tween.duration ?? 280));
      camera.position.lerpVectors(tween.from, tween.to, t * t * (3 - 2 * t));
      controls.target.lerpVectors(tween.targetFrom, tween.targetTo, t * t * (3 - 2 * t));
      if (t >= 1) tween = null;
    }
    const moving = !draggingPoint && controls.update();
    renderer.render(scene, camera);
    pointLayer.render();
    if (cubeElement) {
      const matrix = new T.Matrix4().makeRotationFromQuaternion(camera.quaternion.clone().invert());
      for (const index of [1, 4, 6, 9]) matrix.elements[index] *= -1;
      cubeElement.style.transform = `matrix3d(${matrix.elements.join(",")})`;
    }
    if (paintStart !== null || tween || moving) requestFrame();
  }
  function view(name: StudioView) {
    showZone(null);
    workshop.group.visible = name === "workshop";
    const to = new T.Vector3(...views[name]);
    const target = new T.Vector3(0, 1, 0);
    if (previewBounds && name !== "workshop") {
      previewBounds.getCenter(target);
      const direction = to
        .clone()
        .sub(new T.Vector3(0, 1, 0))
        .normalize();
      const right = new T.Vector3().crossVectors(new T.Vector3(0, 1, 0), direction).normalize();
      const up = new T.Vector3().crossVectors(direction, right).normalize();
      const tangent = Math.tan(T.MathUtils.degToRad(camera.fov / 2));
      let distance = 3.3;
      for (const x of [previewBounds.min.x, previewBounds.max.x])
        for (const y of [previewBounds.min.y, previewBounds.max.y])
          for (const z of [previewBounds.min.z, previewBounds.max.z]) {
            const corner = new T.Vector3(x, y, z).sub(target);
            distance = Math.max(
              distance,
              corner.dot(direction) +
                Math.max(
                  Math.abs(corner.dot(right)) / (tangent * camera.aspect),
                  Math.abs(corner.dot(up)) / tangent,
                ),
            );
          }
      to.copy(target).addScaledVector(direction, distance * 1.08);
    }
    if (!motion || reduce.matches) {
      camera.position.copy(to);
      tween = null;
      controls.target.copy(target);
    } else
      tween = {
        from: camera.position.clone(),
        to,
        start: performance.now(),
        targetFrom: controls.target.clone(),
        targetTo: target,
      };
    controls.update();
    requestFrame();
  }
  function showZone(zone: BodyZoneId | null) {
    focusedZone = zone;
    canvas.setAttribute(
      "aria-label",
      zone
        ? `${BODY_ZONES.find((item) => item.id === zone)?.label} isolated for point placement. Drag to orbit or use zoom controls.`
        : previewAsset
          ? `${assetLabel} exterior shell preview. Drag to orbit or use camera controls.`
          : "Ranger exterior body. Click a panel to focus in Inspection points, or drag to orbit.",
    );
    controls.enableRotate = true;
    controls.minDistance = zone ? 0.18 : 3.3;
    bodyMeshes.forEach((mesh) => {
      mesh.visible = zone === null;
    });
    panelGroups.forEach((group, id) => {
      group.visible = id === zone;
    });
    pickMeshes.splice(
      0,
      pickMeshes.length,
      ...(zone ? ((panelGroups.get(zone)?.children as T.Mesh[]) ?? []) : bodyMeshes),
    );
    renderer.shadowMap.needsUpdate = true;
  }
  function focusZone(zone: BodyZoneId | null, directionOverride?: T.Vector3) {
    if (!zone) {
      view("body");
      return;
    }
    const group = panelGroups.get(zone);
    const definition = BODY_ZONES.find((item) => item.id === zone);
    if (!group || !definition) return;
    completePaint();
    showZone(zone);
    workshop.group.visible = false;
    const bounds = new T.Box3().setFromObject(group);
    const center = bounds.getCenter(new T.Vector3());
    const direction = directionOverride ?? new T.Vector3(...definition.direction).normalize();
    const basis = new T.Matrix4().lookAt(center.clone().add(direction), center, camera.up);
    const right = new T.Vector3().setFromMatrixColumn(basis, 0);
    const up = new T.Vector3().setFromMatrixColumn(basis, 1);
    let width = 0,
      height = 0,
      depth = 0;
    for (const x of [bounds.min.x, bounds.max.x])
      for (const y of [bounds.min.y, bounds.max.y])
        for (const z of [bounds.min.z, bounds.max.z]) {
          const corner = new T.Vector3(x, y, z).sub(center);
          width = Math.max(width, Math.abs(corner.dot(right)));
          height = Math.max(height, Math.abs(corner.dot(up)));
          depth = Math.max(depth, Math.abs(corner.dot(direction)));
        }
    const tangent = Math.tan(T.MathUtils.degToRad(camera.fov / 2));
    const distance = Math.max(height / tangent, width / (tangent * camera.aspect)) * 1.38 + depth;
    const to = center.clone().addScaledVector(direction, distance);
    if (!motion || reduce.matches) {
      camera.position.copy(to);
      controls.target.copy(center);
      tween = null;
    } else
      tween = {
        from: camera.position.clone(),
        to,
        start: performance.now(),
        targetFrom: controls.target.clone(),
        targetTo: center,
      };
    controls.update();
    requestFrame();
  }
  const stopTween = () => {
    tween = null;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1));
  };
  const restoreResolution = () => {
    renderer.setPixelRatio(restingPixelRatio);
    requestFrame();
  };
  controls.addEventListener("start", stopTween);
  controls.addEventListener("end", restoreResolution);
  controls.addEventListener("change", requestFrame);
  const resize = new ResizeObserver(() => {
    const w = stage.clientWidth,
      h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.fov = w < 550 ? 51 : 34;
    camera.updateProjectionMatrix();
    if (focusedZone) focusZone(focusedZone);
    requestFrame();
  });
  resize.observe(stage);
  const intersection = new IntersectionObserver((entries) => {
    visible = entries[0].isIntersecting;
    requestFrame();
  });
  intersection.observe(stage);
  document.addEventListener("visibilitychange", requestFrame);
  const theme = () => {
    const dark = document.documentElement.classList.contains("dark");
    scene.background = new T.Color(dark ? 0x182532 : 0xe4ebef);
    workshop.theme(dark);
    requestFrame();
  };
  const themeObserver = new MutationObserver(theme);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  const reducedChange = () => {
    if (reduce.matches && paintStart !== null) completePaint();
    if (reduce.matches) completeCameraMotion();
  };
  function completeCameraMotion() {
    if (!tween) return;
    camera.position.copy(tween.to);
    controls.target.copy(tween.targetTo);
    tween = null;
    controls.update();
    requestFrame();
  }
  reduce.addEventListener("change", reducedChange);
  const contextLost = (e: Event) => {
    e.preventDefault();
    loaded = false;
    paintStart = null;
    emit("3D display interrupted. Reload the model to continue.", true);
  };
  canvas.addEventListener("webglcontextlost", contextLost);
  emit(`Loading ${assetLabel} body…`);
  theme();
  new GLTFLoader().load(
    previewAsset?.url ?? `/models/ranger/ranger-body.glb?v=${RANGER_ASSET_VERSION}`,
    (gltf) => {
      if (disposed) {
        disposeObject(gltf.scene);
        return;
      }
      const replaced = new Set<T.Material>();
      gltf.scene.traverse((node) => {
        if (node instanceof T.Mesh) {
          bodyMeshes.push(node);
          node.userData.assetVersion = previewAsset?.assetVersion ?? RANGER_ASSET_VERSION;
          (Array.isArray(node.material) ? node.material : [node.material]).forEach((m) =>
            replaced.add(m),
          );
          node.material = material;
          node.castShadow = true;
          node.receiveShadow = true;
        }
      });
      replaced.forEach((m) => m.dispose());
      scene.add(gltf.scene);
      gltf.scene.updateMatrixWorld(true);
      if (previewAsset) previewBounds = new T.Box3().setFromObject(gltf.scene);
      panelGroups = previewAsset ? new Map() : splitBodyPanels(bodyMeshes);
      // Keep source vertex/index order intact: saved anchors use the original mesh coordinates.
      const accelerate = (mesh: T.Mesh) => {
        if (!mesh.geometry.boundsTree) computeBoundsTree.call(mesh.geometry, { indirect: true });
        mesh.raycast = acceleratedRaycast;
      };
      bodyMeshes.forEach(accelerate);
      panelGroups.forEach((group) =>
        group.traverse((node) => {
          if (node instanceof T.Mesh) accelerate(node);
        }),
      );
      renderer.shadowMap.needsUpdate = true;
      panelGroups.forEach((group) => {
        group.visible = false;
        scene.add(group);
      });
      pickMeshes.push(...bodyMeshes);
      loaded = true;
      emit("Unpainted metal · Ready to inspect");
      requestFrame();
    },
    undefined,
    () => emit(`Could not load the ${assetLabel} body. Retry loading the model.`, true),
  );
  return {
    navigationCube(element: HTMLDivElement | null) {
      cubeElement = element;
      requestFrame();
    },
    orient(name: StudioView) {
      if (draggingPoint) return;
      if (!focusedZone || name === "workshop") {
        view(name);
        return;
      }
      const directions: Record<StudioView, T.Vector3> = {
        workshop: new T.Vector3(-1, 0.65, 1),
        body: new T.Vector3(-1, 0.65, 1),
        front: new T.Vector3(-1, 0, 0),
        rear: new T.Vector3(1, 0, 0),
        side: new T.Vector3(0, 0, 1),
        opposite: new T.Vector3(0, 0, -1),
        top: new T.Vector3(0, 1, 0.001),
        under: new T.Vector3(0, -1, 0.001),
      };
      focusZone(focusedZone, directions[name].normalize());
    },
    focusZone,
    points: pointLayer.configure,
    view,
    finish: completePaint,
    // Editing a shade preserves the inspection camera and never starts a robot pass.
    preview(hex: string, name: string, finish: PaintFinish = "unpainted") {
      if (!loaded || disposed) return;
      label = name;
      uniforms.next.value.set(hex);
      uniforms.nextFinish.value.set(...FINISH_VALUES[finish]);
      workshop.shade(hex);
      completePaint();
    },
    paint(hex: string, name: string, finish: PaintFinish = "unpainted", animate = true) {
      if (!loaded || disposed) return;
      if (paintStart !== null) completePaint();
      label = name;
      uniforms.previous.value.copy(uniforms.next.value);
      uniforms.previousFinish.value.copy(uniforms.nextFinish.value);
      uniforms.next.value.set(hex);
      uniforms.nextFinish.value.set(...FINISH_VALUES[finish]);
      uniforms.amount.value = 0;
      workshop.shade(hex);
      paintStart = performance.now();
      view("workshop");
      if (!animate || !motion || reduce.matches) completePaint();
      else {
        emit("Preparing paint pass");
        requestFrame();
      }
    },
    motion(enabled: boolean) {
      motion = enabled;
      if (!motion && paintStart !== null) completePaint();
      if (!motion) completeCameraMotion();
    },
    zoom(direction: "in" | "out", animate = true) {
      const offset =
        tween?.kind === "zoom"
          ? tween.to.clone().sub(tween.targetTo)
          : camera.position.clone().sub(controls.target);
      offset.setLength(
        T.MathUtils.clamp(
          offset.length() * (direction === "in" ? 0.82 : 1.22),
          controls.minDistance,
          20,
        ),
      );
      const to = controls.target.clone().add(offset);
      tween = {
        from: camera.position.clone(),
        to,
        targetFrom: controls.target.clone(),
        targetTo: controls.target.clone(),
        start: performance.now(),
        kind: "zoom",
        duration: Number.parseFloat(getComputedStyle(stage).getPropertyValue("--dur-base")) || 240,
      };
      if (!animate || !motion || reduce.matches) completeCameraMotion();
      controls.update();
      requestFrame();
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      resize.disconnect();
      intersection.disconnect();
      themeObserver.disconnect();
      document.removeEventListener("visibilitychange", requestFrame);
      reduce.removeEventListener("change", reducedChange);
      canvas.removeEventListener("webglcontextlost", contextLost);
      controls.dispose();
      pointLayer.dispose();
      disposeObject(scene);
      material.dispose();
      environment.dispose();
      key.shadow.dispose();
      renderer.dispose();
      canvas.remove();
    },
  };
}
