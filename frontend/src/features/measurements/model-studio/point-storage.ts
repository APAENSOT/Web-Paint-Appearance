import type { components } from "@/api/types";
import type { PointDraft, StudioPoint, SurfaceLocation } from "./point-placement";
export type PointProfile = components["schemas"]["PointProfileOut"];
export type PointChanges = Record<string, SurfaceLocation | null>;
export const storageKey = (domain: string, pointKey: string) => JSON.stringify([domain, pointKey]);
export function profilePoints(profile: PointProfile | undefined): StudioPoint[] {
  return (profile?.points ?? []).map((p) => ({
    key: storageKey(profile!.domain, p.point_key),
    pointKey: p.point_key,
    domain: profile!.domain,
    code: p.label,
    number: p.point_no ?? 0,
    counted: p.counted ?? false,
  }));
}
export function profileLocations(
  profile: PointProfile | undefined,
  assetVersion: string,
): PointDraft {
  const locations: PointDraft = {};
  for (const p of profile?.points ?? []) {
    const a = p.anchor;
    if (!a?.asset_compatible || a.asset_version !== assetVersion) continue;
    locations[storageKey(profile!.domain, p.point_key)] = {
      assetVersion: a.asset_version,
      mesh: a.mesh_name,
      position: a.position as [number, number, number],
      normal: a.normal as [number, number, number],
      ...(a.body_zone ? { zone: a.body_zone } : {}),
    };
  }
  return locations;
}
export function mergeLocations(saved: PointDraft, changes: PointChanges): PointDraft {
  const result = { ...saved };
  for (const [key, location] of Object.entries(changes)) {
    if (location) result[key] = location;
    else delete result[key];
  }
  return result;
}
export function toAnchor(location: SurfaceLocation): components["schemas"]["AnchorIn"] {
  return {
    asset_version: location.assetVersion,
    mesh_name: location.mesh,
    position: location.position,
    normal: location.normal,
    body_zone: location.zone ?? null,
  };
}
