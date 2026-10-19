/**
 * T109 (D-109-6): the Film row question's state and copy. No JSX -- the cell
 * that draws it is `FilmPointCell.tsx`, the split `rough-panels.ts` /
 * `RoughPanelCell.tsx` already use.
 *
 * A Location this plant's live list for the model does not hold -- a point
 * that was retired, a spelling the plant has started writing -- is asked
 * about **in the row that carries it**: which live point is this? The answer
 * is remembered for every later upload of this plant x model, so the same
 * label never asks twice.
 *
 * T109-FIX (D-109F-1, D-109F-3): while any label is unanswered **nothing on
 * the sheet loads** -- a walk renumbered down writes live names one spot out,
 * so "the rest" would be filed onto the wrong points of the truck -- and the
 * copy says so, with what to do instead of mapping a renumbered walk.
 *
 * Nothing here decides anything. The labels (`film_unknown_labels`) and the
 * points an answer may name (`film_point_choices`) both come from the
 * worksheet read, so this screen never proposes a point: a Film point is its
 * number *and* its name (D-99-1), and a guess would file a reading onto the
 * wrong spot of the truck.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, refreshActiveMeasurements, refreshWorksheet } from "@/api/queries";
import type { components } from "@/api/types";

type Sheet = components["schemas"]["WorksheetSheetOut"];
export type FilmUnknownLabel = components["schemas"]["FilmUnknownLabel"];
export type FilmPointChoice = components["schemas"]["FilmPointChoice"];

export const FILM_POINT_COPY = {
  heading: "Some labels are not points of this plant's list",
  explain:
    "Say which live point each one is in its row - we remember it for every later upload of " +
    "this plant and model - or add it as a new point on Point Check and then re-check this " +
    "file. Nothing on this sheet loads until every label is answered. If the walk was " +
    "renumbered - a point was taken out and the rest shifted down - do not map these labels: " +
    "fix the file and upload it again.",
  // RO17-FIX (D-RO17F-2): a list without settings loads the other rows.
  explainRestLoads:
    "Say which live point each one is in its row - we remember it for every later upload of " +
    "this plant and model - or add it as a new point on Point Check and then re-check this " +
    "file. The other rows of this sheet load; these rows wait until they are answered.",
  choose: "Choose point",
  // RO18 (B5): the other answer -- this label is not a point at all.
  notAPoint: "Not a point of this list",
  notAPointConfirm:
    "Keep these rows with the file and never load them. We remember this for every later " +
    "upload of this plant and model.",
  notAPointSubmit: "Keep it, never load it",
  cancel: "Cancel",
  answer: "This is",
  extra: " (extra)",
} as const;

/** The same fold the backend compares a Location by: upper-case, no spaces. */
export function labelKey(label: string | null | undefined): string {
  return (label ?? "").replace(/\s+/g, "").toUpperCase();
}

/** `{normalised label: the question}` for one tab. */
export function unknownByLabel(sheet: Sheet): Map<string, FilmUnknownLabel> {
  const out = new Map<string, FilmUnknownLabel>();
  for (const item of sheet.film_unknown_labels ?? []) {
    const key = labelKey(item.raw_location);
    if (!out.has(key)) out.set(key, item);
  }
  return out;
}

/** RO18 (B5): what "Not a point of this list" posts: the label as the sheet wrote it. */
export function notAPointBody(
  loadId: number,
  label: FilmUnknownLabel,
): components["schemas"]["FilmNotAPointCreate"] {
  return { load_id: loadId, raw_location: label.raw_location };
}

export function useFilmPointQuestions({
  sheet,
  plant,
  fileHash,
}: {
  sheet: Sheet;
  plant: string;
  fileHash: string;
}) {
  const client = useQueryClient();
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const byLabel = unknownByLabel(sheet);
  const choices = sheet.film_point_choices ?? [];

  const answer = useMutation({
    mutationFn: (body: { raw_location: string; point_code: string }) =>
      api().answerFilmPoint(plant, fileHash, { load_id: sheet.load_id, ...body }),
    retry: false,
    onSuccess: async () => {
      setChosen({});
      await refreshWorksheet(client, plant, fileHash);
      await refreshActiveMeasurements(client);
    },
  });

  const notAPoint = useMutation({
    mutationFn: (label: FilmUnknownLabel) =>
      api().answerFilmNotAPoint(plant, fileHash, notAPointBody(sheet.load_id, label)),
    retry: false,
    onSuccess: async () => {
      await refreshWorksheet(client, plant, fileHash);
      await refreshActiveMeasurements(client);
    },
  });

  return {
    byLabel,
    choices,
    answer,
    notAPoint,
    loadId: sheet.load_id,
    pending: [...byLabel.values()],
    selected: (label: FilmUnknownLabel): string => chosen[labelKey(label.raw_location)] ?? "",
    choose: (label: FilmUnknownLabel, point: string) =>
      setChosen((was) => ({ ...was, [labelKey(label.raw_location)]: point })),
    /** The question this row carries, or undefined when it carries none. */
    questionFor: (label: string | null | undefined): FilmUnknownLabel | undefined =>
      byLabel.get(labelKey(label)),
  };
}

export type FilmPointQuestions = ReturnType<typeof useFilmPointQuestions>;
