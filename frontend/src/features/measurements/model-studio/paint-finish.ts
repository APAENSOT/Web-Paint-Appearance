// A visual studio treatment derived only from the plant's Standard family.
// It is not a paint formula or calibrated pigment measurement.
export type PaintFinish = "unpainted" | "solid" | "metallic";

export function finishForFamily(family: string | null): PaintFinish {
  return /\bmetallics?\b/i.test(family ?? "") ? "metallic" : "solid";
}

// Visual animation parameters: metalness, roughness, fine roughness variation.
export const FINISH_VALUES: Record<PaintFinish, readonly [number, number, number]> = {
  unpainted: [0.45, 0.35, 0],
  solid: [0, 0.53, 0],
  metallic: [0.58, 0.32, 0.055],
};
