/**
 * RO17: what Point Check shares between its Wave Scan and Film sections --
 * the plant's own word for a point (D-RO17-1), rename (D-RO17-6), restore
 * (D-RO17-9), the aliases list (D-RO17-13) and the Film switch-on
 * (D-RO17-11). No JSX, the split `film-points.ts` uses.
 */
import type { QueryClient } from "@tanstack/react-query";
import type { PointDomain } from "@/api/client";
import { refreshFilmPoints, refreshPointLabels, refreshWsPoints } from "@/api/queries";
import type { components } from "@/api/types";

export type PointAlias = components["schemas"]["PointAliasItem"];
type FilmPoint = components["schemas"]["FilmPointSettingItem"];

export const POINT_EDIT_COPY = {
  rename: "Rename",
  renameLabel: "The plant's word for this point",
  renameHint:
    "History, Comparison and every reading stay under the same code, so nothing splits. " +
    "The old word still reads on upload.",
  renameReason: "Why does the name change?",
  renameSubmit: "Save name",
  restore: "Restore",
  restoreReason: "Why is this point back?",
  restoreWarning:
    "This puts the point back on the walk and on the dashboard for every month, " +
    "including past ones. Its readings were never removed.",
  restoreSubmit: "Restore point",
  cancel: "Cancel",
  reasonHint: "At least 3 characters. It is stored with your name and the time.",
  aliasesHeading: "Other spellings",
  aliasesExplain:
    "Every spelling a file may write for a point of this list, and the point it reads as. " +
    "Retiring a spelling never changes a stored reading.",
  aliasesNone: "No other spelling reads as a point of this list.",
  shared: "Shared by all plants",
  sharedTitle: "A spelling every plant reads the same way. It cannot be retired here.",
  aliasRetire: "Retire",
  aliasRetireReason: "Why should this spelling stop reading?",
  aliasRetireWarning:
    "Files that write this spelling will no longer read it as this point. Stored readings stay as they are.",
  aliasRetireSubmit: "Retire spelling",
  live: "Live",
  retired: "Retired",
  noList: "no list yet",
  emptyList: "This model has no points yet. Add the first one below.",
} as const;

export const ALIAS_KIND: Record<PointAlias["kind"], string> = {
  zone_map: "Plant map",
  global_alias: "Shared spelling",
  film_alias: "Taught answer",
  location_map: "Location map",
  earlier_label: "Earlier name",
  // RO18 (B5): an uploader's "Not a point of this list" answer. No target point.
  not_a_point: "Not a point of this list — kept, never loaded",
};

/** The plant's word first; the code only when it says something more. */
export function pointName(label: string | null | undefined, code: string) {
  const word = label?.trim() || code;
  return { word, code: word === code ? null : code };
}

export async function refreshPointWrite(
  client: QueryClient,
  plant: string,
  domain: PointDomain,
  model: string,
) {
  await Promise.all([
    domain === "wavescan"
      ? refreshWsPoints(client, plant)
      : refreshFilmPoints(client, plant, model),
    refreshPointLabels(client, plant),
  ]);
}

/** RO19 follow-up: an add or restore re-read stored sheets; show their new state now. */
export async function refreshReplayed(client: QueryClient, replayed?: number[]) {
  if (!replayed?.length) return;
  await Promise.all(
    ["worksheet", "workbook", "workbooks"].map((key) =>
      client.invalidateQueries({ queryKey: [key] }),
    ),
  );
}

/**
 * D-RO17-11: what "Switch on the point rules" would write -- every live point
 * counted, at the H / V the list already carries. A point with no H / V is a
 * refusal here, never a guess.
 */
export function switchOnRows(points: FilmPoint[]): {
  rows: components["schemas"]["FilmWalkPoint"][];
  missing: string[];
} {
  const missing = points.filter((point) => !point.orientation).map((point) => point.point_code);
  const rows = points.flatMap((point) =>
    point.orientation
      ? [{ point_code: point.point_code, counted: true, orientation: point.orientation }]
      : [],
  );
  return { rows, missing };
}
