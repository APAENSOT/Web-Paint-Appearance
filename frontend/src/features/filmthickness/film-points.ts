/**
 * T100 Part C: the Points panel's copy and its diff. No JSX --
 * `FilmPointSettings.tsx` draws it, the same split `rough-panels.ts` and
 * `RoughPanelCell.tsx` already use.
 */
import type { components } from "@/api/types";

export type Point = components["schemas"]["FilmPointSettingItem"];
export type RetiredPoint = components["schemas"]["FilmRetiredPointItem"];
export type Orientation = "H" | "V";
export type Draft = { counted: boolean; orientation: Orientation };

export const POINTS_COPY = {
  heading: "Points",
  explain:
    "Which points of this walk count towards the dashboard's Horizontal and Vertical boxes, " +
    "and which of the two each one is. Readings are never changed here.",
  warning: "This changes Horizontal / Vertical for every month at {plant}, including past ones.",
  reason: "Why are you changing this?",
  reasonHint: "At least 3 characters. It is stored with your name and the time.",
  save: "Save",
  cancel: "Cancel",
  // RO17 (D-RO17-11): the list is editable without the rules; only Counted and H / V wait.
  readOnly:
    "The point rules are not switched on for this list, so nothing here counts towards " +
    "Horizontal / Vertical yet. Points can still be added, renamed, retired and restored.",
  seed: "seed",
  noChange: "Nothing has changed yet.",
} as const;

/**
 * T109: Point Check's own words. The page is one entry inside Standard
 * (D-109-1) and its Film section is the panel above, widened by add
 * (D-109-5) and retire (D-109-4).
 *
 * The retire warning is the owner's sentence, not a softened one: a retire
 * takes the point off the walk for **every** month the dashboard shows, and
 * the readings stay where they are.
 */
export const POINT_CHECK_COPY = {
  heading: "Point Check",
  explain:
    "The points each plant walks, in the plant's own words. Change what counts and its " +
    "Hor / Ver, rename a point, add one a file has started writing, retire one the plant " +
    "no longer measures, or restore it. Readings are never changed here.",
  filmSection: "Film Thickness",
  extra: "Extra",
  extraTitle: "Beyond this plant's standard list for the model.",
  retiredHeading: "Retired points",
  retiredExplain:
    "Off the walk and off the dashboard for every month. The readings cars already have on " +
    "them are still in History, marked retired. Points retired by an earlier task are here " +
    "too, each with the reason it carries.",
  retiredNone: "Nothing has been retired on this list.",
  add: "Add a point",
  addName: "Point name, as a file writes it",
  addNameHint: "Number first, then the panel word: 099TGATEIN. The number is read off the name.",
  addOrientation: "H / V",
  addOrientationAuto: "From the list's own points of that word",
  addCounted: "Counts towards Horizontal / Vertical",
  addReason: "Why does this point exist?",
  addSubmit: "Add point",
  retire: "Retire",
  retireReason: "Why is this point gone?",
  retireWarning:
    "This stops counting on the dashboard for every month, including past ones. " +
    "The readings stay in History, marked retired.",
  retireSubmit: "Retire point",
  cancel: "Cancel",
  reasonHint: "At least 3 characters. It is stored with your name and the time.",
} as const;

/** RO17 (D-RO17-12): a list's tail labels. */
export const TAIL_COPY = {
  heading: "Tail labels",
  explain:
    "Words a file writes below the walk that are not points, such as a total. A reading " +
    "under one of these is not read as a point.",
  none: "This list has no tail labels.",
  live: "Live",
  retired: "Retired",
  add: "Add a tail label",
  addLabel: "The word, as a file writes it",
  addReason: "Why is this word not a point?",
  addSubmit: "Add tail label",
  retire: "Retire",
  retireReason: "Why should this word be read again?",
  retireSubmit: "Retire tail label",
  cancel: "Cancel",
} as const;

/** RO17 (D-RO17-11): the Admin switch-on for a list with no point rules. */
export const SWITCH_ON_COPY = {
  open: "Switch on the point rules",
  warning:
    "This switches on Counted and Horizontal / Vertical for this list at {plant}, for every " +
    "month, including past ones.",
  preview: "It will write these values. Change any of them after it is on.",
  missing:
    "These points have no Horizontal / Vertical yet, so the rules cannot be switched on. " +
    "Nothing was sent:",
  reason: "Why are you switching the rules on?",
  submit: "Switch on",
  cancel: "Cancel",
} as const;

/** Only the points whose tick or orientation differs from what is stored. */
export function changedPoints(
  points: Point[],
  draft: Record<string, Draft>,
): components["schemas"]["FilmWalkPoint"][] {
  return points
    .filter((point) => {
      const next = draft[point.point_code];
      return next && (next.counted !== point.counted || next.orientation !== point.orientation);
    })
    .map((point) => ({
      point_code: point.point_code,
      counted: draft[point.point_code].counted,
      orientation: draft[point.point_code].orientation,
    }));
}
