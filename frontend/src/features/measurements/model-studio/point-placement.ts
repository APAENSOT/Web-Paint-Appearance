import type { components } from "@/api/types";
import type { BodyZoneId } from "./body-zones";

export const RANGER_ASSET_VERSION = "20261012-b-pillars";
export type PointDomain = "wavescan" | "film";
// View state; point-storage maps the published API to mesh-local placements.
export type StudioPoint = {
  key: string;
  domain: PointDomain;
  code: string;
  number: number;
  counted: boolean;
  pointKey?: string;
};
export type SurfaceLocation = {
  zone?: BodyZoneId;
  assetVersion: string;
  mesh: string;
  position: [number, number, number];
  normal: [number, number, number];
};
export type PointDraft = Record<string, SurfaceLocation>;

export function waveStudioPoints(items: components["schemas"]["WsPointItem"][]): StudioPoint[] {
  return items.map((p) => ({
    key: JSON.stringify(["wavescan", p.zone_code]),
    domain: "wavescan",
    code: p.zone_code,
    number: p.point_no,
    counted: p.counted,
  }));
}

export function filmStudioPoints(
  items: components["schemas"]["FilmPointSettingItem"][],
): StudioPoint[] {
  return items.map((p) => ({
    key: JSON.stringify(["film", p.point_no, p.point_code]),
    domain: "film",
    code: p.point_code,
    number: p.point_no,
    counted: p.counted,
  }));
}

export function isPlacementClick(start: { x: number; y: number }, end: { x: number; y: number }) {
  return Math.hypot(end.x - start.x, end.y - start.y) <= 5;
}
