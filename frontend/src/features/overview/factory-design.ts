export type Vec3 = [number, number, number];
export type FactoryMaterial =
  "base" | "road" | "wall" | "roof" | "trim" | "glass" | "solar" | "green";
export type FactoryPart = {
  position: Vec3;
  size: Vec3;
  material: FactoryMaterial;
  area?: "wave" | "film";
};
export type FactoryDesign = {
  name: string;
  parts: FactoryPart[];
  wave: Vec3;
  film: Vec3;
  vent: Vec3;
};

// Illustrated architectural cues, not surveyed floor plans. Geometry is shared
// between the lightweight map landmarks and the interactive Three.js models.
function design(code: string): FactoryDesign {
  const parts: FactoryPart[] = [];
  const add = (position: Vec3, size: Vec3, material: FactoryMaterial, area?: "wave" | "film") =>
    parts.push({ position, size, material, area });
  const hall = (
    x: number,
    z: number,
    width: number,
    depth: number,
    height: number,
    area: "wave" | "film",
  ) => {
    add([x, height / 2, z], [width, height, depth], "wall");
    add([x, height + 0.08, z], [width + 0.16, 0.16, depth + 0.16], "roof", area);
    for (let dx = -width / 2 + 0.3; dx < width / 2; dx += 0.65) {
      add([x + dx, height * 0.7, z + depth / 2 + 0.02], [0.42, 0.24, 0.04], "glass");
      add([x + dx, height + 0.19, z], [0.065, 0.07, depth], "trim");
    }
  };
  const canopy = (x: number, z: number, width: number) => {
    add([x, 0.62, z], [width, 0.09, 0.64], "solar");
    for (const dx of [-width / 2 + 0.18, width / 2 - 0.18])
      add([x + dx, 0.3, z], [0.055, 0.6, 0.055], "trim");
    for (let dx = -width / 2 + 0.25; dx < width / 2; dx += 0.5)
      add([x + dx, 0.675, z], [0.016, 0.012, 0.62], "trim");
  };
  const tree = (x: number, z: number) => {
    add([x, 0.2, z], [0.08, 0.4, 0.08], "roof");
    add([x, 0.52, z], [0.32, 0.42, 0.32], "green");
  };
  add([0, -0.13, 0], [7.4, 0.24, 5.2], "base");
  add([0, 0.01, 1.8], [7.1, 0.025, 0.72], "road");
  for (let x = -3; x < 3.5; x += 1) add([x, 0.029, 1.8], [0.36, 0.01, 0.025], "trim");
  let wave: Vec3 = [-1.4, 1.9, -0.6];
  let film: Vec3 = [1.8, 1.5, -0.7];
  let name = "Solar courtyard";
  if (code === "AAT") {
    name = "Twin assembly halls";
    hall(-1.65, -0.55, 2.3, 2.5, 1.35, "wave");
    hall(1.1, -0.55, 2.3, 2.5, 1.35, "film");
    add([-0.27, 0.46, 0], [0.5, 0.75, 0.6], "glass");
    add([-0.3, 0.38, 1.03], [4.8, 0.72, 0.42], "trim");
    add([-0.3, 0.5, 1.26], [4.5, 0.25, 0.025], "glass");
    add([2.85, 0.85, 0.9], [0.18, 1.7, 0.3], "trim");
    add([2.85, 1.48, 0.9], [0.25, 0.35, 0.38], "solar");
    wave = [-1.65, 1.98, -0.6];
    film = [1.1, 1.98, -0.6];
  } else if (code === "FVL") {
    name = "Garden entrance";
    hall(-0.95, -0.65, 3.6, 1.9, 1.05, "wave");
    hall(1.65, -0.82, 1.3, 1.55, 0.83, "film");
    add([-0.95, 0.28, 0.57], [3.1, 0.54, 0.55], "trim");
    add([-0.95, 0.36, 0.86], [2.8, 0.23, 0.025], "glass");
    // White entrance pylon and garden are the plant's visual signature.
    add([2.8, 0.9, 0.75], [0.48, 1.8, 0.28], "trim");
    add([2.8, 1.5, 0.902], [0.36, 0.18, 0.025], "solar");
    add([1.88, 0.3, 1.08], [0.55, 0.6, 0.5], "wall");
    add([0.4, 0.38, 1.12], [2.2, 0.06, 0.06], "trim");
    for (const x of [-2.7, -1.7, -0.7, 0.3]) tree(x, 1.1);
    wave = [-1.15, 1.72, -0.7];
    film = [1.65, 1.43, -0.8];
  } else if (code === "SAP") {
    name = "Solar assembly campus";
    hall(-0.9, -1.05, 4.5, 1.65, 1.1, "wave");
    hall(2, -1.05, 1.05, 1.65, 1.1, "film");
    for (const z of [0.3, 1.05]) canopy(-0.3, z, 5.9);
    wave = [-1.5, 1.78, -1.05];
    film = [2, 1.78, -1.05];
  } else {
    hall(-1, -0.75, 4.15, 2.15, 1.4, "wave");
    hall(1.85, -0.85, 1.35, 1.85, 0.95, "film");
    canopy(-1.1, 0.96, 3.6);
    add([1.85, 0.32, 0.48], [1.35, 0.62, 0.48], "glass");
  }
  const vent: Vec3 = [-2.5, code === "FTM" || code === "AAT" ? 1.92 : 1.65, -1.2];
  add([vent[0], vent[1] - 0.19, vent[2]], [0.24, 0.38, 0.26], "trim");
  for (const x of [-2.7, -1.9, -1.1]) {
    add([x, 0.13, 2.28], [0.42, 0.18, 0.46], "trim");
    add([x, 0.25, 2.28], [0.33, 0.13, 0.25], "glass");
  }
  tree(-3.25, 0.9);
  tree(3.15, 1.2);
  return { name, parts, wave, film, vent };
}

export const FACTORY_DESIGNS: Record<string, FactoryDesign> = Object.fromEntries(
  ["FTM", "AAT", "FVL", "SAP"].map((code) => [code, design(code)]),
);
export const FACTORY_PALETTES: Record<"light" | "dark", Record<FactoryMaterial, string>> = {
  light: {
    base: "#bacbd4",
    road: "#7d929e",
    wall: "#dbe5ea",
    roof: "#668ca9",
    trim: "#f2f5f3",
    glass: "#356780",
    solar: "#204d75",
    green: "#779b85",
  },
  dark: {
    base: "#203c50",
    road: "#182c3f",
    wall: "#63879e",
    roof: "#355d78",
    trim: "#a5c9d8",
    glass: "#d5e9be",
    solar: "#387da1",
    green: "#588b80",
  },
};
