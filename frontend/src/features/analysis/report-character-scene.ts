import * as T from "three";

/** Approved artwork on layered geometry: independent neck pose and local eye gaze. */
export function createReportCharacter(host: HTMLElement, onLost: () => void, onReady: () => void) {
  let disposed = false;
  const renderer = new T.WebGLRenderer({
    alpha: true,
    antialias: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0, 0);
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.domElement.setAttribute("aria-hidden", "true");
  host.appendChild(renderer.domElement);
  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(T.MathUtils.radToDeg(2 * Math.atan(1.5 / 7)), 1, 0.1, 20);
  camera.position.z = 7;
  const gaze = new T.Vector2();
  const atlas = new T.TextureLoader().load(
    "/characters/report-chibi-3d-atlas.webp",
    () => {
      if (!disposed && !lost) {
        render();
        onReady();
      }
    },
    undefined,
    () => {
      if (!disposed) onLost();
    },
  );
  atlas.colorSpace = T.SRGBColorSpace;
  // The atlas has a wide head on the left and a separate shirt at the lower right.
  // Explicit UV crops preserve every hair tip without bleeding the shirt into the head.
  function artwork(width: number, height: number, crop: number[], head = false) {
    const geometry = new T.PlaneGeometry(width, height, head ? 80 : 1, head ? 80 : 1);
    const uv = geometry.getAttribute("uv");
    const positions = geometry.getAttribute("position");
    for (let i = 0; i < uv.count; i++) {
      const u = uv.getX(i),
        v = uv.getY(i);
      uv.setXY(i, (crop[0] + u * crop[2]) / 1774, 1 - (crop[1] + (1 - v) * crop[3]) / 887);
      if (head) {
        // Sculpt a portrait relief instead of rotating a flat card. The front projection
        // remains registered to the approved artwork; depth is revealed during a turn.
        const bump = (x: number, y: number, rx: number, ry: number) =>
          Math.exp(-2 * (((u - x) / rx) ** 2 + ((v - y) / ry) ** 2));
        const depth =
          (0.62 * bump(0.5, 0.46, 0.49, 0.54) +
            0.23 * bump(0.5, 0.76, 0.43, 0.34) +
            0.15 * bump(0.49, 0.28, 0.08, 0.085) +
            0.09 * bump(0.36, 0.33, 0.16, 0.15) +
            0.09 * bump(0.63, 0.32, 0.16, 0.15)) *
          T.MathUtils.smoothstep(v, 0.035, 0.17);
        const perspective = (7 - 0.1 - depth) / 7;
        positions.setXYZ(
          i,
          positions.getX(i) * perspective,
          (positions.getY(i) + 0.175) * perspective - 0.175,
          depth,
        );
      }
    }
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
    const material = new T.MeshBasicMaterial({
      map: atlas,
      transparent: true,
      depthWrite: false,
      toneMapped: false,
    });
    if (head)
      material.onBeforeCompile = (shader) => {
        shader.uniforms.guideGaze = { value: gaze };
        shader.vertexShader = shader.vertexShader
          .replace(
            "#include <common>",
            `#include <common>
          varying vec3 guideNormal;
          varying vec3 guideRestNormal;
        `,
          )
          .replace(
            "#include <begin_vertex>",
            `#include <begin_vertex>
          guideNormal = normalize(normalMatrix * normal);
          guideRestNormal = normal;
        `,
          );
        shader.fragmentShader = shader.fragmentShader
          .replace(
            "#include <common>",
            `#include <common>
        uniform vec2 guideGaze;
        varying vec3 guideNormal;
        varying vec3 guideRestNormal;
        float eyeMask(vec2 p, vec2 center, vec2 radius) {
          return 1.0 - smoothstep(0.50, 1.0, length((p-center)/radius));
        }
      `,
          )
          .replace(
            "#include <map_fragment>",
            `
        // Warp only inside the eye whites. Rims, eyebrows and cheeks remain anchored.
        vec2 pixel = vec2(vMapUv.x * 1774.0, (1.0-vMapUv.y) * 887.0);
        float mask = max(eyeMask(pixel, vec2(353.0, 591.0), vec2(79.0, 65.0)),
                         eyeMask(pixel, vec2(613.0, 607.0), vec2(76.0, 62.0)));
        vec2 offset = vec2(guideGaze.x * 140.0 / 1774.0, guideGaze.y * 140.0 / 887.0);
        diffuseColor *= texture2D(map, vMapUv - offset * mask);
        // Artwork already includes studio lighting. Add only the change caused by
        // turning the relief, keeping its original colours at the neutral pose.
        vec3 key = normalize(vec3(-0.55, 0.7, 1.0));
        float lit = 0.78 + 0.22 * max(dot(normalize(guideNormal), key), 0.0);
        float rest = 0.78 + 0.22 * max(dot(normalize(guideRestNormal), key), 0.0);
        diffuseColor.rgb *= lit / rest;
      `,
          );
      };
    return new T.Mesh(geometry, material);
  }
  const torso = artwork(2.3, 0.86, [970, 600, 804, 287]);
  torso.name = "fixed-torso";
  torso.position.set(0, -1.08, 0);
  scene.add(torso);
  const neck = new T.Group();
  neck.name = "head-pivot";
  neck.position.set(0, -0.88, 0.1);
  scene.add(neck);
  const head = artwork(2.75, 2.515, [0, 0, 970, 887], true);
  head.position.set(0, 1.055, 0);
  neck.add(head);

  let lost = false,
    enabled = false,
    frame = 0,
    previous = 0;
  let targetX = 0,
    targetY = 0,
    eyeX = 0,
    eyeY = 0,
    nodStart = 0;
  function render() {
    if (!disposed && !lost) renderer.render(scene, camera);
  }
  const velocity = new T.Vector2();
  // Analytic critically damped spring: velocity survives retargeting, so a quick
  // direction change decelerates naturally. Exact integration is frame-rate independent.
  function spring(position: number, target: number, speed: number, dt: number, axis: "x" | "y") {
    const offset = position - target;
    const impulse = velocity[axis] + speed * offset;
    const decay = Math.exp(-speed * dt);
    velocity[axis] = (velocity[axis] - speed * impulse * dt) * decay;
    return target + (offset + impulse * dt) * decay;
  }
  function tick(now: number) {
    frame = 0;
    if (disposed || lost || !enabled) return;
    const dt = Math.min((now - previous) / 1000, 0.05);
    previous = now;
    const eyeRate = 1 - Math.exp(-20 * dt);
    const nodAge = nodStart ? (now - nodStart) / 700 : 1;
    const nod =
      nodAge < 1 ? Math.sin(nodAge * Math.PI * 2) * Math.sin(nodAge * Math.PI) ** 2 * 0.1 : 0;
    neck.rotation.y = spring(
      neck.rotation.y,
      T.MathUtils.clamp(targetX * 0.32, -0.22, 0.22),
      14,
      dt,
      "y",
    );
    neck.rotation.x = spring(
      neck.rotation.x,
      T.MathUtils.clamp(targetY * 0.19, -0.14, 0.14) + nod,
      14,
      dt,
      "x",
    );
    eyeX = T.MathUtils.lerp(eyeX, targetX * 0.062, eyeRate);
    eyeY = T.MathUtils.lerp(eyeY, -targetY * 0.045, eyeRate);
    gaze.set(eyeX, eyeY);
    render();
    if (
      Math.abs(neck.rotation.y - T.MathUtils.clamp(targetX * 0.32, -0.22, 0.22)) +
        Math.abs(neck.rotation.x - T.MathUtils.clamp(targetY * 0.19, -0.14, 0.14)) +
        Math.abs(eyeX - targetX * 0.062) +
        Math.abs(eyeY + targetY * 0.045) +
        velocity.length() >
        0.0001 ||
      nodAge < 1
    ) {
      request();
    } else {
      velocity.set(0, 0);
      previous = 0;
      // Finish at an exact rest pose and stop rendering until the next interaction.
      neck.rotation.y = T.MathUtils.clamp(targetX * 0.32, -0.22, 0.22);
      neck.rotation.x = T.MathUtils.clamp(targetY * 0.19, -0.14, 0.14);
      eyeX = targetX * 0.062;
      eyeY = -targetY * 0.045;
      gaze.set(eyeX, eyeY);
      render();
    }
  }
  function request() {
    if (!frame && enabled && !disposed && !lost) {
      if (!previous) previous = performance.now();
      frame = requestAnimationFrame(tick);
    }
  }
  const resize = () => {
    const { width, height } = host.getBoundingClientRect();
    if (width && height) {
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      render();
    }
  };
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();
  const contextLost = (event: Event) => {
    event.preventDefault();
    lost = true;
    cancelAnimationFrame(frame);
    frame = 0;
    onLost();
  };
  renderer.domElement.addEventListener("webglcontextlost", contextLost);
  return {
    look(x: number, y: number) {
      if (!enabled) return;
      targetX = T.MathUtils.clamp(x, -1, 1);
      targetY = T.MathUtils.clamp(y, -1, 1);
      request();
    },
    nod() {
      if (enabled) {
        nodStart = performance.now();
        request();
      }
    },
    motion(value: boolean) {
      enabled = value;
      if (!value) {
        cancelAnimationFrame(frame);
        frame = 0;
        targetX = targetY = eyeX = eyeY = nodStart = previous = 0;
        velocity.set(0, 0);
        neck.rotation.set(0, 0, 0);
        gaze.set(0, 0);
        render();
      }
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("webglcontextlost", contextLost);
      const geometries = new Set<T.BufferGeometry>(),
        materials = new Set<T.Material>();
      scene.traverse((node) => {
        if (node instanceof T.Mesh) {
          geometries.add(node.geometry);
          (Array.isArray(node.material) ? node.material : [node.material]).forEach((m) =>
            materials.add(m),
          );
        }
      });
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.dispose());
      atlas.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
export type ReportCharacterScene = ReturnType<typeof createReportCharacter>;
