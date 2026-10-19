/**
 * T109 (D-109-6): the Film point question, drawn inside the table row's own
 * "Resolved zone" cell -- the same placement T94's panel question has, and
 * for the same reason: the screen the owner actually reviews is the table,
 * so the answer belongs in it and a browser spec can assert that.
 *
 * The list offered is the server's (`film_point_choices`): this plant's live
 * points for the tab's model, in walk order. Nothing is pre-selected,
 * because nobody can propose a point for an unknown label without guessing.
 */
import { useState } from "react";
import type { components } from "@/api/types";
import { ApiErrorState } from "@/components/ApiState";
import { pointText } from "./point-labels";
import { Button } from "@/components/ui/button";
import {
  FILM_POINT_COPY,
  type FilmPointQuestions,
  type FilmUnknownLabel,
} from "./film-point-questions";

export function FilmPointCell({
  label,
  row,
  questions,
  labelOf = (code) => code,
}: {
  label: FilmUnknownLabel;
  row: components["schemas"]["WorksheetRowOut"];
  questions: FilmPointQuestions;
  /** D-RO17-16: the plant's label of a point code (the code when none). */
  labelOf?: (code: string) => string;
}) {
  const value = questions.selected(label);
  const [asking, setAsking] = useState(false);
  const busy = questions.answer.isPending || questions.notAPoint.isPending;
  const selectId = `film-point-${questions.loadId}-${row.source_row}`;
  return (
    <div className="min-w-56 space-y-1" data-testid={`film-point-row-${label.raw_location}`}>
      <label className="block text-xs font-medium" htmlFor={selectId}>
        Which point is {label.raw_location}?
      </label>
      <select
        id={selectId}
        data-testid={`film-point-select-${label.raw_location}`}
        className="min-h-11 w-full rounded-md border border-border bg-background px-2 text-xs"
        value={value}
        disabled={busy}
        onChange={(event) => questions.choose(label, event.target.value)}
      >
        <option value="">{FILM_POINT_COPY.choose}</option>
        {questions.choices.map((point) => (
          <option key={point.point_code} value={point.point_code}>
            {point.point_no} {pointText(labelOf(point.point_code), point.point_code)}
            {point.orientation ? ` · ${point.orientation}` : ""}
            {point.is_extra ? FILM_POINT_COPY.extra : ""}
          </option>
        ))}
      </select>
      <Button
        className="min-h-11 w-full"
        data-testid={`film-point-answer-${label.raw_location}`}
        disabled={!value || busy}
        onClick={() =>
          questions.answer.mutate({ raw_location: label.raw_location, point_code: value })
        }
      >
        {FILM_POINT_COPY.answer} {value && pointText(labelOf(value), value)}
      </Button>
      {/* RO18 (B5): the other answer, with a confirm line: it is remembered. */}
      {asking ? (
        <div
          className="space-y-2 border border-primary bg-[var(--primary-soft)] p-2"
          role="alert"
          data-testid={`film-not-a-point-confirm-${label.raw_location}`}
        >
          <p className="text-xs font-medium">{FILM_POINT_COPY.notAPointConfirm}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              className="min-h-11"
              data-testid={`film-not-a-point-submit-${label.raw_location}`}
              disabled={busy}
              onClick={() => questions.notAPoint.mutate(label)}
            >
              {FILM_POINT_COPY.notAPointSubmit}
            </Button>
            <Button
              variant="outline"
              className="min-h-11"
              disabled={busy}
              onClick={() => setAsking(false)}
            >
              {FILM_POINT_COPY.cancel}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          variant="outline"
          className="min-h-11 w-full"
          data-testid={`film-not-a-point-${label.raw_location}`}
          disabled={busy}
          onClick={() => setAsking(true)}
        >
          {FILM_POINT_COPY.notAPoint}
        </Button>
      )}
      <p className="text-xs text-muted-foreground">
        {label.rows} row{label.rows === 1 ? "" : "s"} carry this label.
      </p>
      {questions.answer.isError && <ApiErrorState error={questions.answer.error} />}
      {questions.notAPoint.isError && <ApiErrorState error={questions.notAPoint.error} />}
    </div>
  );
}
