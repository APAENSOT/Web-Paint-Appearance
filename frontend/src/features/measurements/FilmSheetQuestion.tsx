/**
 * T100 (D-100-1, D-100-5): the one question a held Film sheet asks, drawn
 * once above the tab's row table.
 *
 * Once, not per row. A sheet-wide hold puts the same sentence on every one
 * of 98 rows; asking it 98 times is how T99's review read. The three
 * questions and their answers:
 *
 * - **walk, confirmable** - the file wrote names past the end of the list.
 *   One line per new name with its Counted tick and its H / V, pre-filled
 *   from what the list's own points of that word carry. Confirm posts them.
 * - **walk, not confirmable** - the walk inserts, reorders, renumbers or
 *   repeats a name. The sentence, and **no button**: it needs an owner
 *   decision (D-99-14), and offering a control that cannot help is the
 *   defect T86 fixed in the panel copy.
 * - **model** - the file name and the Job Number name two models. One
 *   button per model.
 * - **job** - the Job Number is not this plant's shape. One button.
 */
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import {
  FILM_QUESTION_COPY,
  type FilmSheetQuestionState,
  type Orientation,
} from "./film-sheet-question";

const HEADING = {
  walk: FILM_QUESTION_COPY.walk,
  model: FILM_QUESTION_COPY.model,
  job: FILM_QUESTION_COPY.job,
} as const;

export function FilmSheetQuestion({ state }: { state: FilmSheetQuestionState }) {
  const { question } = state;
  if (!question) return null;
  const heading =
    question.kind === "walk" && !question.confirmable
      ? FILM_QUESTION_COPY.walkHeld
      : HEADING[question.kind];
  return (
    <section
      className="space-y-3 border border-primary bg-[var(--primary-soft)] p-3"
      data-testid="film-question"
      data-film-question={question.kind}
      data-film-confirmable={question.confirmable ? "yes" : "no"}
      aria-label="Question about this tab"
    >
      <h5 className="text-sm font-semibold">{heading}</h5>
      <p className="text-sm">{question.operator_message}</p>

      {question.kind === "walk" && question.confirmable && (
        <div className="space-y-2">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">New points to confirm</caption>
            <thead className="text-xs text-muted-foreground">
              <tr>
                {["Point", FILM_QUESTION_COPY.counted, FILM_QUESTION_COPY.orientation].map(
                  (head) => (
                    <th key={head} scope="col" className="py-1 pr-3 font-medium">
                      {head}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {question.appended.map((point) => {
                const choice = state.choices[point.point_code];
                const id = `film-appended-${point.point_code}`;
                return (
                  <tr key={point.point_code} data-film-appended={point.point_code}>
                    <th scope="row" className="py-1 pr-3 font-semibold">
                      {point.point_code}
                      {point.proposed_orientation === null && (
                        <span className="block text-xs font-normal text-muted-foreground">
                          {FILM_QUESTION_COPY.needsOrientation}
                        </span>
                      )}
                    </th>
                    <td className="py-1 pr-3">
                      <input
                        type="checkbox"
                        id={`${id}-counted`}
                        data-testid={`film-appended-counted-${point.point_code}`}
                        aria-label={`${FILM_QUESTION_COPY.counted} ${point.point_code}`}
                        className="size-5"
                        checked={choice?.counted ?? point.counted}
                        disabled={state.pending}
                        onChange={(event) =>
                          state.setCounted(point.point_code, event.target.checked)
                        }
                      />
                    </td>
                    <td className="py-1 pr-3">
                      <select
                        id={`${id}-orientation`}
                        data-testid={`film-appended-orientation-${point.point_code}`}
                        aria-label={`${FILM_QUESTION_COPY.orientation} ${point.point_code}`}
                        className="min-h-11 rounded-md border border-border bg-background px-2 text-xs"
                        value={choice?.orientation ?? ""}
                        disabled={state.pending}
                        onChange={(event) =>
                          state.setOrientation(
                            point.point_code,
                            event.target.value as Orientation | "",
                          )
                        }
                      >
                        <option value="">{FILM_QUESTION_COPY.chooseOrientation}</option>
                        <option value="H">H (Horizontal)</option>
                        <option value="V">V (Vertical)</option>
                      </select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Button
            className="min-h-11"
            data-testid="film-confirm-walk"
            disabled={!state.canConfirm}
            onClick={() => state.confirmWalk.mutate()}
          >
            {FILM_QUESTION_COPY.confirm} {question.appended.length} point
            {question.appended.length === 1 ? "" : "s"}
          </Button>
        </div>
      )}

      {question.kind === "walk" && !question.confirmable && (
        <p className="text-sm text-muted-foreground">{FILM_QUESTION_COPY.ownerDecision}</p>
      )}

      {question.kind === "model" && (
        <div className="flex flex-wrap gap-2">
          {question.models.map((model) => (
            <Button
              key={model}
              className="min-h-11"
              data-testid={`film-choose-model-${model}`}
              disabled={state.pending}
              onClick={() => state.chooseModel.mutate(model)}
            >
              It is {model}
            </Button>
          ))}
        </div>
      )}

      {question.kind === "job" && (
        <Button
          className="min-h-11"
          data-testid="film-load-as-written"
          disabled={state.pending}
          onClick={() => state.loadAsWritten.mutate()}
        >
          {FILM_QUESTION_COPY.loadAsWritten}
          {question.job_no ? `: ${question.job_no}` : ""}
        </Button>
      )}

      {state.error && <ApiErrorState error={state.error} />}
    </section>
  );
}
