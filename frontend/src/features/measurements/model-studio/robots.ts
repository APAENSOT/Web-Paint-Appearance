import * as T from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

const up = new T.Vector3(0, 1, 0);
const down = new T.Vector3(0, -1, 0);
const upperLength = 1.25,
  foreLength = 1.726;

export function buildWorkshop(scene: T.Scene) {
  const workshop = new T.Group();
  scene.add(workshop);
  const white = new T.MeshStandardMaterial({ color: 0xe4e7e8, metalness: 0.2, roughness: 0.32 });
  const joint = new T.MeshStandardMaterial({ color: 0x667789, metalness: 0.65, roughness: 0.33 });
  const blue = new T.MeshStandardMaterial({ color: 0x174a7e, metalness: 0.4, roughness: 0.3 });
  const deck = new T.MeshStandardMaterial({ color: 0x384a5b, metalness: 0.3, roughness: 0.65 });
  function mesh(geometry: T.BufferGeometry, material: T.Material, parent: T.Object3D) {
    const item = new T.Mesh(geometry, material);
    item.castShadow = true;
    item.receiveShadow = true;
    parent.add(item);
    return item;
  }
  function box(
    w: number,
    h: number,
    d: number,
    x: number,
    y: number,
    z: number,
    material: T.Material,
    parent = workshop,
  ) {
    const item = mesh(
      new RoundedBoxGeometry(w, h, d, 3, Math.min(0.06, w * 0.3, h * 0.3, d * 0.3)),
      material,
      parent,
    );
    item.position.set(x, y, z);
    return item;
  }
  function cylinder(
    top: number,
    bottom: number,
    height: number,
    y: number,
    parent: T.Object3D,
    material = white,
  ) {
    const item = mesh(new T.CylinderGeometry(top, bottom, height, 24), material, parent);
    item.position.y = y;
    return item;
  }
  function housing(length: number, width: number) {
    const group = new T.Group();
    box(width, length - 0.16, width * 0.82, 0, length / 2, 0, white, group);
    cylinder(width * 0.52, width * 0.52, 0.12, 0.08, group, joint);
    cylinder(width * 0.4, width * 0.4, 0.1, length - 0.07, group, joint);
    box(width * 0.46, 0.09, 0.03, 0, length * 0.66, width * 0.43, blue, group);
    return group;
  }
  box(8.4, 0.18, 6.3, 0, -0.22, 0, deck);
  box(8.46, 0.055, 6.36, 0, -0.305, 0, joint);
  for (const x of [-0.7, 0.65]) box(0.28, 0.55, 1.5, x, 0.16, 0, joint);
  const lightMaterial = new T.MeshStandardMaterial({
    color: 0xe2edff,
    emissive: 0xb7d2ff,
    emissiveIntensity: 1.5,
  });
  for (const x of [-3.75, 3.75]) {
    box(0.045, 2.65, 0.06, x, 1.18, -2.75, joint);
    box(0.02, 2.22, 0.035, x, 1.22, -2.71, lightMaterial);
  }
  const robots = [-1, 1].flatMap((gx) =>
    [-1, 1].map((gz) => {
      const root = new T.Group();
      root.name = `Fixed robot ${gx} ${gz}`;
      root.position.set(gx * 1.8, -0.12, gz * 2.13);
      workshop.add(root);
      box(0.78, 0.075, 0.7, 0, 0.035, 0, joint, root);
      cylinder(0.25, 0.31, 0.28, 0.22, root);
      cylinder(0.265, 0.265, 0.065, 0.375, root, joint);
      box(0.39, 0.46, 0.35, 0, 0.6, 0, white, root);
      const shoulder = mesh(new T.SphereGeometry(0.24, 20, 14), white, root);
      shoulder.position.y = 0.82;
      const upper = housing(upperLength, 0.35),
        fore = housing(foreLength, 0.29);
      root.add(upper, fore);
      const elbow = mesh(new T.SphereGeometry(0.2, 20, 14), white, root);
      const wrist = new T.Group();
      root.add(wrist);
      cylinder(0.12, 0.15, 0.19, 0, wrist);
      cylinder(0.066, 0.103, 0.22, -0.24, wrist);
      cylinder(0.089, 0.053, 0.065, -0.375, wrist, joint);
      const sprayMaterial = new T.MeshBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 0.09,
        depthWrite: false,
        side: T.DoubleSide,
      });
      const spray = mesh(new T.ConeGeometry(0.23, 0.4, 20, 1, true), sprayMaterial, wrist);
      spray.position.y = -0.6;
      spray.visible = false;
      spray.castShadow = false;
      const shoulderPosition = new T.Vector3(0, 0.82, 0);
      const park = new T.Vector3(gx * 1.4, 0.95, gz * 0.3);
      return {
        root,
        upper,
        fore,
        elbow,
        wrist,
        spray,
        sprayMaterial,
        shoulderPosition,
        park,
        gx,
        gz,
      };
    }),
  );
  type Robot = (typeof robots)[number];
  function solve(robot: Robot, end: T.Vector3) {
    const delta = end.clone().sub(robot.shoulderPosition);
    const distance = T.MathUtils.clamp(
      delta.length(),
      Math.abs(foreLength - upperLength) + 0.02,
      upperLength + foreLength - 0.015,
    );
    const direction = delta.normalize();
    const along = (upperLength ** 2 - foreLength ** 2 + distance ** 2) / (2 * distance);
    const bendHeight = Math.sqrt(Math.max(0, upperLength ** 2 - along ** 2));
    const bend = up.clone().addScaledVector(direction, -direction.y);
    if (bend.lengthSq() < 0.001) bend.set(robot.gx, 0, 0);
    bend.normalize();
    const elbow = robot.shoulderPosition
      .clone()
      .addScaledVector(direction, along)
      .addScaledVector(bend, bendHeight);
    const wrist = robot.shoulderPosition.clone().addScaledVector(direction, distance);
    for (const [group, from, to] of [
      [robot.upper, robot.shoulderPosition, elbow],
      [robot.fore, elbow, wrist],
    ] as const) {
      group.position.copy(from);
      group.quaternion.setFromUnitVectors(up, to.clone().sub(from).normalize());
    }
    robot.elbow.position.copy(elbow);
    robot.wrist.position.copy(wrist);
    robot.wrist.quaternion.setFromUnitVectors(down, down);
  }
  function target(robot: Robot, amount: number) {
    const x = robot.gx < 0 ? -2.3 + amount * 2.5 : 0.25 + amount * 2.5;
    const y =
      1.93 +
      0.5 * T.MathUtils.smoothstep(x, -1.1, -0.5) * (1 - T.MathUtils.smoothstep(x, 0.9, 1.5));
    return new T.Vector3(x, y, robot.gz * (0.63 + 0.22 * Math.sin(amount * Math.PI))).sub(
      robot.root.position,
    );
  }
  const ease = (t: number) => t * t * (3 - 2 * t);
  function park() {
    for (const r of robots) {
      solve(r, r.park);
      r.spray.visible = false;
    }
  }
  park();
  return {
    group: workshop,
    park,
    shade(hex: string) {
      robots.forEach((r) => r.sprayMaterial.color.set(hex));
    },
    animate(t: number) {
      const amount = T.MathUtils.clamp((t - 0.14) / 0.69, 0, 1);
      for (const r of robots) {
        const end =
          t < 0.14
            ? r.park.clone().lerp(target(r, 0), ease(t / 0.14))
            : t > 0.83
              ? target(r, 1).lerp(r.park, ease((t - 0.83) / 0.17))
              : target(r, amount);
        solve(r, end);
        r.spray.visible = t >= 0.14 && t <= 0.83;
      }
      return amount;
    },
    theme(dark: boolean) {
      deck.color.set(dark ? 0x344657 : 0xa4b5c3);
    },
  };
}
