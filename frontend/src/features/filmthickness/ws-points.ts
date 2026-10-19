/**
 * T114: Point Check's Wave Scan section -- its copy and its two small rules.
 * No JSX; `WsPointSettings.tsx` draws it, the split `film-points.ts` uses.
 */
import type { components } from "@/api/types";

export type WsPoint = components["schemas"]["WsPointItem"];
export type WsRetiredPoint = components["schemas"]["WsRetiredPointItem"];
export type WsZoneChoice = components["schemas"]["WsZoneChoice"];

export const WS_POINTS_COPY = {
  heading: "Wave Scan",
  explain:
    "Which points of this walk the dashboard counts. Horizontal / Vertical is fixed by each " +
    "point's name and is not edited here. Readings are never changed here: History and " +
    "Comparison keep every one.",
  none: "This plant has no Wave Scan point list yet.",
  counted: "Counted",
  warning:
    "This changes what the dashboard counts at {plant} for every month, including past ones. " +
    "History and Comparison keep every reading, tagged.",
  reason: "Why are you changing this?",
  reasonHint: "At least 3 characters. It is stored with your name and the time.",
  save: "Save",
  cancel: "Cancel",
  noChange: "Nothing has changed yet.",
  extra: "Extra",
  extraTitle: "Beyond this plant's standard list for the model. Added on Point Check.",
  retiredHeading: "Retired points",
  retiredExplain:
    "Off the walk and off the dashboard for every month. The readings cars already have on " +
    "them are still in History, marked retired. Points retired by an earlier task are here " +
    "too, each with the reason it carries.",
  retiredNone: "Nothing has been retired on this list.",
  retire: "Retire",
  retireReason: "Why is this point gone?",
  retireWarning:
    "This stops counting on the dashboard for every month, including past ones. " +
    "The readings stay in History, marked retired. It can be restored from Retired points below.",
  retireSubmit: "Retire point",
  add: "Add a point",
  addCode: "Zone code",
  addCodeHint:
    "Pick an existing zone code from the list, or type a new one exactly as the plant " +
    "writes it. It goes at the end of the walk and is tagged extra.",
  addNew: "New zone code -- it will be added as typed.",
  addExisting: "Existing zone code.",
  addHv: "Horizontal / Vertical (from the name)",
  addCounted: "Counted on the dashboard",
  addComplete: "Counts towards complete cars",
  addCompleteHint:
    "Admin only. A car is complete when it has a reading at every point that counts here, " +
    "so cars already stored without this point become incomplete.",
  addImpact: "{n} stored cars become incomplete.",
  addImpactLoading: "Counting the stored cars this would make incomplete...",
  addReason: "Why does this point exist?",
  addSubmit: "Add point",
} as const;

/** Only the points whose tick differs from what is stored. */
export function changedWsPoints(
  points: WsPoint[],
  draft: Record<string, boolean>,
): components["schemas"]["WsPointSettingRow"][] {
  return points
    .filter((point) => point.zone_code in draft && draft[point.zone_code] !== point.counted)
    .map((point) => ({ zone_code: point.zone_code, counted: draft[point.zone_code] }));
}

/**
 * What Add shows for the code being typed: the existing code's own Hor / Ver,
 * or, for a new code, the one its name gives by the server's words
 * (`horizontal_words`, `ck_zone_rule`). Shown only -- the server reads it
 * off the name again and the database enforces it.
 */
export function addPreview(
  typed: string,
  choices: WsZoneChoice[],
  horizontalWords: string[],
): { code: string; isNew: boolean; tolerance: string } | null {
  const code = typed.trim();
  if (!code) return null;
  const known = choices.find((choice) => choice.zone_code === code);
  if (known) return { code, isNew: false, tolerance: known.tolerance_group };
  const upper = code.toUpperCase();
  const horizontal = horizontalWords.some((word) => upper.includes(word.toUpperCase()));
  return { code, isNew: true, tolerance: horizontal ? "Horizontal" : "Vertical" };
}
