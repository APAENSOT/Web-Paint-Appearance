import type { components } from "@/api/types";

export type Walk = components["schemas"]["PointWalkOut"];
export type WalkDraft = Pick<
  components["schemas"]["PointWalkSetIn"],
  "point_codes" | "expected_version_id"
>;

export function moveWalkPoint(codes: readonly string[], code: string, direction: -1 | 1): string[] {
  const index = codes.indexOf(code);
  const target = index + direction;
  const next = [...codes];
  if (index < 0 || target < 0 || target >= codes.length) return next;
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function placeWalkPointAfter(
  codes: readonly string[],
  code: string,
  after: string,
): string[] {
  if (code === after || !codes.includes(code) || !codes.includes(after)) return [...codes];
  const next = codes.filter((item) => item !== code);
  next.splice(next.indexOf(after) + 1, 0, code);
  return next;
}

export function rebaseWalkDraft(draft: WalkDraft, latest: Walk): WalkDraft | null {
  const live = new Set(latest.items.map((point) => point.point_code));
  if (
    draft.point_codes.length !== live.size ||
    new Set(draft.point_codes).size !== live.size ||
    draft.point_codes.some((code) => !live.has(code))
  )
    return null;
  return { point_codes: [...draft.point_codes], expected_version_id: latest.version_id };
}
