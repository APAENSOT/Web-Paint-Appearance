/**
 * RO18 (B3 / B4): the one date question a held tab asks, either domain, drawn
 * once above the tab's rows. Everything comes from `sheet.date_question`:
 *
 * - **month** - the sheet has no date anywhere. Which month were these cars
 *   measured? The input starts at the file name's month, a suggestion only:
 *   nothing is sent until a person presses the button.
 * - **date** - a Film sheet's date and its file name's date disagree. One
 *   button per date.
 *
 * Engineer / Admin answer (`mayIngest`); anybody else sees the question with
 * its controls disabled.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, meOptions, refreshActiveMeasurements, refreshWorksheet } from "@/api/queries";
import { mayIngest } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";

type Sheet = components["schemas"]["WorksheetSheetOut"];

export const DATE_QUESTION_COPY = {
  month: "Which month were these cars measured?",
  date: "Which date is right?",
  monthLabel: "Month measured",
  monthAnswer: "Use this month",
  sheetDate: "The sheet's date",
  fileNameDate: "The file name's date",
} as const;

export function SheetDateQuestion({
  sheet,
  plant,
  fileHash,
}: {
  sheet: Sheet;
  plant: string;
  fileHash: string;
}) {
  const client = useQueryClient();
  const identity = useQuery(meOptions);
  const ingest = !identity.isError && mayIngest(identity.data?.principal);
  const question = sheet.date_question ?? null;
  const [month, setMonth] = useState(question?.suggested_month ?? "");
  const afterAnswer = async () => {
    await refreshWorksheet(client, plant, fileHash);
    await refreshActiveMeasurements(client);
  };
  const answerMonth = useMutation({
    mutationFn: () => api().answerMonth(plant, fileHash, { load_id: sheet.load_id, month }),
    retry: false,
    onSuccess: afterAnswer,
  });
  const answerDate = useMutation({
    mutationFn: (choice: "sheet" | "file_name") =>
      api().answerFilmDate(plant, fileHash, { load_id: sheet.load_id, choice }),
    retry: false,
    onSuccess: afterAnswer,
  });
  if (!question) return null;
  const disabled = !ingest || answerMonth.isPending || answerDate.isPending;
  const inputId = `date-question-month-${sheet.load_id}`;
  return (
    <section
      className="space-y-3 border border-primary bg-[var(--primary-soft)] p-3"
      data-testid="date-question"
      data-date-question={question.kind}
      aria-label="Date question about this tab"
    >
      <h5 className="text-sm font-semibold">
        {question.kind === "month" ? DATE_QUESTION_COPY.month : DATE_QUESTION_COPY.date}
      </h5>
      <p className="text-sm">{question.operator_message}</p>
      {question.kind === "month" ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="block text-xs font-medium" htmlFor={inputId}>
            {DATE_QUESTION_COPY.monthLabel}
            <input
              id={inputId}
              type="month"
              data-testid="date-question-month"
              className="mt-1 block min-h-11 rounded-md border border-border bg-background px-2 text-sm"
              value={month}
              disabled={disabled}
              onChange={(event) => setMonth(event.target.value)}
            />
          </label>
          <Button
            className="min-h-11"
            data-testid="date-question-month-answer"
            disabled={disabled || !/^\d{4}-\d{2}$/.test(month)}
            onClick={() => answerMonth.mutate()}
          >
            {DATE_QUESTION_COPY.monthAnswer}
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            className="min-h-11"
            data-testid="date-question-sheet"
            disabled={disabled}
            onClick={() => answerDate.mutate("sheet")}
          >
            {DATE_QUESTION_COPY.sheetDate} ({question.sheet_date ?? "-"})
          </Button>
          <Button
            className="min-h-11"
            data-testid="date-question-file-name"
            disabled={disabled}
            onClick={() => answerDate.mutate("file_name")}
          >
            {DATE_QUESTION_COPY.fileNameDate} ({question.file_name_date ?? "-"})
          </Button>
        </div>
      )}
      {(answerMonth.error ?? answerDate.error) && (
        <ApiErrorState error={(answerMonth.error ?? answerDate.error)!} />
      )}
    </section>
  );
}
