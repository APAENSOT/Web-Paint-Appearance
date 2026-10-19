import type { components } from "@/api/types";

type Catalogue = components["schemas"]["CatalogueOut"];
export const RANGER_MODEL = "P703 DBL RANGER";

export function studioColors(catalogue: Catalogue, plant: string) {
  return catalogue.colors.filter((color) =>
    color.plants.some((row) => row.plant_code === plant && row.is_offered),
  );
}

// Display approximations ONLY. These are not Standard values, paint formulae,
// grading families, or an authoritative mapping of individual colour names.
const GROUP_SHADE: Record<string, string> = {
  BLACK: "#242a30",
  WHITE: "#e4e6e4",
  SILVER: "#a2adb6",
  GREY: "#626f78",
  GRAY: "#626f78",
  BLUE: "#245e9b",
  RED: "#9e263b",
  ORANGE: "#cd632a",
  GREEN: "#4d6c59",
  BROWN: "#736153",
  GOLD: "#a18a5d",
  YELLOW: "#ccaa48",
};
export function displayShade(group: string | null): string | null {
  return group ? (GROUP_SHADE[group.toUpperCase()] ?? null) : null;
}
