import { storageKey, type PointChanges, type PointProfile } from "./point-storage";
import type { PointDraft, PointDomain, SurfaceLocation } from "./point-placement";
export type PointWrite = {
  domain: PointDomain;
  key: string;
  pointKey: string;
  revision: number | null;
  location: SurfaceLocation | null;
};
export function completeLayout(profile: PointProfile | undefined, draft: PointDraft) {
  return Boolean(
    profile?.points.length &&
    profile.points.every((p) => draft[storageKey(profile.domain, p.point_key)]),
  );
}
export function pendingPointWrites(profile: PointProfile, changes: PointChanges): PointWrite[] {
  return profile.points.flatMap((p) => {
    const key = storageKey(profile.domain, p.point_key);
    return Object.hasOwn(changes, key)
      ? [
          {
            domain: profile.domain,
            key,
            pointKey: p.point_key,
            revision: p.revision,
            location: changes[key],
          },
        ]
      : [];
  });
}
/** Sequential writes retain per-point conflict/retry semantics. Completed writes stay saved. */
export async function persistPoints<T>(
  requests: readonly T[],
  save: (request: T) => Promise<unknown>,
  progress: (done: number, total: number) => void,
) {
  let completed = 0;
  for (const request of requests) {
    try {
      await save(request);
      completed++;
      progress(completed, requests.length);
    } catch (error) {
      return { completed, failed: request, error };
    }
  }
  return { completed, failed: null, error: null };
}
