/**
 * T100: the state and the copy of the one question a held Film sheet asks.
 * No JSX -- `FilmSheetQuestion.tsx` draws it, the same split `rough-panels.ts`
 * and `RoughPanelCell.tsx` already use.
 *
 * Nothing here decides anything (D-100-1). Whether the sheet is held, which
 * of the three questions it asks, which two models it names, which names it
 * appended and what Horizontal / Vertical we propose for each all come from
 * `sheet.film_question`, filled by the server from the code that decided the
 * hold. The client sends an answer only because a person pressed a button.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, refreshActiveMeasurements, refreshWorksheet } from "@/api/queries";
import type { components } from "@/api/types";

type Sheet = components["schemas"]["WorksheetSheetOut"];
export type FilmQuestion = components["schemas"]["FilmSheetQuestion"];
export type FilmAppended = components["schemas"]["FilmAppendedPoint"];
export type Orientation = "H" | "V";

/** What each row of the confirm table says about a new point. */
export type AppendedChoice = { counted: boolean; orientation: Orientation | "" };

export const FILM_QUESTION_COPY = {
  walk: "This file walks points we do not have yet",
  walkHeld: "This file does not walk the list we know",
  model: "This file names two models",
  job: "This Job Number is not the shape this plant writes",
  confirm: "Confirm these",
  loadAsWritten: "Load as written",
  counted: "Counted",
  orientation: "Horizontal / Vertical",
  chooseOrientation: "Choose H or V",
  needsOrientation:
    "The list has no point of this name yet, so nobody can propose Horizontal or Vertical. Choose it.",
  ownerDecision:
    "This one needs an owner decision, so there is nothing to confirm here. The sentence above says what the file did.",
} as const;

/** The default a new point starts at: the server's proposal, counted on. */
export function initialChoices(question: FilmQuestion | null | undefined) {
  const out: Record<string, AppendedChoice> = {};
  for (const point of question?.appended ?? []) {
    out[point.point_code] = {
      counted: point.counted,
      orientation: point.proposed_orientation ?? "",
    };
  }
  return out;
}

/** Every appended point has an H or a V: until then Confirm stays disabled. */
export function readyToConfirm(
  question: FilmQuestion | null | undefined,
  choices: Record<string, AppendedChoice>,
): boolean {
  const points = question?.appended ?? [];
  if (!question?.confirmable || points.length === 0) return false;
  return points.every((point) => choices[point.point_code]?.orientation);
}

/** What the confirm POST sends: one entry per appended name, nothing else. */
export function confirmBody(
  question: FilmQuestion,
  loadId: number,
  choices: Record<string, AppendedChoice>,
): components["schemas"]["FilmWalkConfirmCreate"] {
  return {
    load_id: loadId,
    points: (question.appended ?? []).map((point) => ({
      point_code: point.point_code,
      counted: choices[point.point_code]?.counted ?? point.counted,
      orientation: (choices[point.point_code]?.orientation || "V") as Orientation,
    })),
  };
}

export function useFilmSheetQuestion({
  sheet,
  plant,
  fileHash,
}: {
  sheet: Sheet;
  plant: string;
  fileHash: string;
}) {
  const client = useQueryClient();
  const question = sheet.film_question ?? null;
  const [choices, setChoices] = useState<Record<string, AppendedChoice>>(() =>
    initialChoices(question),
  );

  const afterAnswer = async () => {
    // T97 (D-97-5): the review reads the worksheet once; an answer makes it
    // read again, which is what turns the held rows into ready ones.
    await refreshWorksheet(client, plant, fileHash);
    await refreshActiveMeasurements(client);
  };

  const confirmWalk = useMutation({
    mutationFn: () =>
      api().confirmFilmWalk(plant, fileHash, confirmBody(question!, sheet.load_id, choices)),
    retry: false,
    onSuccess: afterAnswer,
  });
  const chooseModel = useMutation({
    mutationFn: (model: string) =>
      api().answerFilmModel(plant, fileHash, {
        load_id: sheet.load_id,
        model_code: model,
      }),
    retry: false,
    onSuccess: afterAnswer,
  });
  const loadAsWritten = useMutation({
    mutationFn: () => api().answerFilmJob(plant, fileHash, { load_id: sheet.load_id }),
    retry: false,
    onSuccess: afterAnswer,
  });

  const pending = confirmWalk.isPending || chooseModel.isPending || loadAsWritten.isPending;
  return {
    question,
    choices,
    pending,
    confirmWalk,
    chooseModel,
    loadAsWritten,
    canConfirm: readyToConfirm(question, choices) && !pending,
    setCounted: (point: string, counted: boolean) =>
      setChoices((was) => ({
        ...was,
        [point]: { orientation: was[point]?.orientation ?? "", counted },
      })),
    setOrientation: (point: string, orientation: Orientation | "") =>
      setChoices((was) => ({
        ...was,
        [point]: { counted: was[point]?.counted ?? true, orientation },
      })),
    error: confirmWalk.error ?? chooseModel.error ?? loadAsWritten.error,
  };
}

export type FilmSheetQuestionState = ReturnType<typeof useFilmSheetQuestion>;
