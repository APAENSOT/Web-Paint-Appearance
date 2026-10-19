// Visual regions of this verified Ranger asset, not Standard point groupings.
// Composite source meshes contain both sides; split their triangles at Z=0.
export const BODY_ZONES = [
  { id: "hood", label: "Hood", direction: [0, 1, 0.001] },
  { id: "roof", label: "Roof", direction: [0, 1, 0.001] },
  { id: "left-fender", label: "Left front fender", direction: [0, 0.15, 1] },
  { id: "right-fender", label: "Right front fender", direction: [0, 0.15, -1] },
  { id: "left-cab", label: "Left cab side", direction: [0, 0, 1] },
  { id: "right-cab", label: "Right cab side", direction: [0, 0, -1] },
  { id: "left-b-pillar", label: "Left B pillar", direction: [0, 0, 1] },
  { id: "right-b-pillar", label: "Right B pillar", direction: [0, 0, -1] },
  { id: "left-box", label: "Left box side", direction: [0, 0.1, 1] },
  { id: "right-box", label: "Right box side", direction: [0, 0.1, -1] },
  { id: "bed", label: "Bed / inner box", direction: [0, 1, 0.001] },
  { id: "tailgate", label: "Tailgate", direction: [1, 0, 0] },
] as const;
export type BodyZoneId = (typeof BODY_ZONES)[number]["id"];
export function bodyZone(mesh: string, position: readonly number[]): BodyZoneId | null {
  const left = position[2] >= 0;
  switch (mesh) {
    case "ranger-panel-5-Object006":
      return "hood";
    case "ranger-panel-3-Object006":
      return "roof";
    case "ranger-panel-0-mesh_33":
      return "bed";
    case "ranger-panel-1-Object002":
    case "ranger-panel-2-Object005":
      return "tailgate";
    case "ranger-panel-6-Object008":
      return left ? "left-fender" : "right-fender";
    case "ranger-panel-4-Object005":
    case "ranger-panel-7-Object009":
      return left ? "left-cab" : "right-cab";
    case "ranger-panel-8-Object010":
      return left ? "left-box" : "right-box";
    case "ranger-b-pillar-positive-z":
      return "left-b-pillar";
    case "ranger-b-pillar-negative-z":
      return "right-b-pillar";
    default:
      return null;
  }
}
