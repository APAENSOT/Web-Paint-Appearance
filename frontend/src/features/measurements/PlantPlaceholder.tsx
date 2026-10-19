import { VisualPlaceholder } from "@/features/shell/VisualPlaceholder";
import { LENS_PLACEHOLDER, type PlantLens } from "./plant-lens";

export function PlantPlaceholder({ lens }: { lens: PlantLens }) {
  const copy = LENS_PLACEHOLDER[lens];
  return <VisualPlaceholder title={copy.title} reason={copy.reason} />;
}
