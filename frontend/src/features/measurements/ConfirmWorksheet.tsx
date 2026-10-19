import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  meOptions,
  refreshActiveMeasurements,
  refreshWorksheet,
  worksheetOptions,
} from "@/api/queries";
import { mayCorrect, mayIngest } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { FilesMapping } from "./FilesMapping";
import { HeldIdentityList } from "./HeldIdentityList";
import { TemplatePublishDialog } from "./TemplatePublishDialog";
import { FilmBoxTag } from "@/features/filmthickness/FilmBoxTag";
import { emptyIdentityCopy, IGNORE_COPY, needsTemplateMapping } from "./review-copy";
import { canTeach, rowKey, useHeldAlias } from "./held-alias";
import { HeldAliasConfirmation } from "./HeldAliasConfirmation";
import { FilmPointCell } from "./FilmPointCell";
import { FILM_POINT_COPY, useFilmPointQuestions } from "./film-point-questions";
import { ROUGH_PANEL_COPY, useRoughPanels } from "./rough-panels";
import { RoughPanelCell } from "./RoughPanelCell";
import { FilmSheetQuestion } from "./FilmSheetQuestion";
import { useFilmSheetQuestion } from "./film-sheet-question";
import { SheetDateQuestion } from "./SheetDateQuestion";
import { pointText, usePointLabels } from "./point-labels";
import { SkippedSheets } from "./WorkbookSections";

type Workbook = components["schemas"]["WorkbookOut"];
type Worksheet = components["schemas"]["WorksheetOut"];
type Decision =
  | { kind: "ignore"; headers: string[] }
  | { kind: "plant"; plant: string }
  | { kind: "holes"; loadId: number; rows: number[] };

export function ConfirmWorksheet({
  code,
  hash,
  workbook,
  onLoaded,
}: {
  code: string;
  hash: string;
  workbook: Workbook;
  onLoaded: (notice: string) => void;
}) {
  const client = useQueryClient();
  const identity = useQuery(meOptions);
  const ingest = mayIngest(identity.data?.principal) && mayCorrect(identity.data?.principal);
  const allSkipped = workbook.operational_summary === "SKIPPED";
  const worksheet = useQuery({ ...worksheetOptions(code, hash), enabled: ingest && !allSkipped });
  const [decision, setDecision] = useState<Decision | null>(null);
  const [otherPlant, setOtherPlant] = useState("");
  const [cancelledPlant, setCancelledPlant] = useState<string | null>(null);
  const refresh = async (active = false) => {
    await refreshWorksheet(client, code, hash);
    if (active) await refreshActiveMeasurements(client);
  };
  const decide = useMutation({
    mutationFn: async (value: Decision) => {
      if (value.kind === "ignore")
        return api().ignoreColumns(code, hash, { headers: value.headers });
      if (value.kind === "holes")
        return api().approveHoles(code, hash, { load_id: value.loadId, source_rows: value.rows });
      return api().answerPlant(code, hash, { plant_code: value.plant });
    },
    retry: false,
    onSuccess: async (result) => {
      if ("open_plant" in result && typeof result.open_plant === "string")
        setCancelledPlant(result.open_plant);
      setDecision(null);
      await Promise.all(
        result.replayed_load_ids.map((loadId) =>
          client.invalidateQueries({ queryKey: ["batch", loadId] }),
        ),
      );
      await refresh();
    },
  });
  const load = useMutation({
    mutationFn: (remaining: boolean) =>
      remaining ? api().loadRemaining(code, hash) : api().loadReady(code, hash),
    retry: false,
    onSuccess: async (result) => {
      onLoaded(result.operator_message);
      await refresh(true);
    },
  });

  if (identity.isPending) return <LoadingState>Checking access...</LoadingState>;
  if (identity.isError) return <ApiErrorState error={identity.error} />;
  if (!ingest) return <p className="p-4 text-sm">Sign in to review this workbook.</p>;
  if (allSkipped)
    return (
      <section className="min-w-0 space-y-3 p-4">
        <p className="text-sm">
          No measurement sheets to review. The skipped sheets are kept as workbook evidence.
        </p>
        <SkippedSheets workbook={workbook} />
      </section>
    );
  if (cancelledPlant)
    return (
      <p role="status" className="p-4 text-sm">
        This upload was cancelled. Open the {cancelledPlant} plant page and upload the file there.
      </p>
    );
  if (worksheet.isPending) return <LoadingState>Loading worksheet table...</LoadingState>;
  if (worksheet.isError)
    return <ApiErrorState error={worksheet.error} retry={() => void worksheet.refetch()} />;
  const data: Worksheet = worksheet.data;
  const blockedSheets = data.sheets.filter(
    (item) =>
      item.state === "blocked" &&
      workbook.sheets.find((sheet) => sheet.batch.load_id === item.load_id)?.batch.sheet_class !==
        "OUT_OF_SCOPE_SHEET",
  );
  const remaining = data.sheets.some((sheet) => sheet.state === "loaded");
  // RO13 (F12): like Approve, nothing to press when no loaded tab has a ready row.
  const remainingReady = data.sheets.some(
    (sheet) => sheet.state === "loaded" && sheet.rows_ready > 0,
  );
  const missingStep = 2;
  const extraStep = missingStep + Number(Boolean(data.missing_optional_message));
  const plantStep = extraStep + Number(data.extra_columns.length > 0);
  const tabsStep = plantStep + Number(Boolean(data.plant_question));
  return (
    <section aria-label="Confirm this worksheet" className="space-y-5 p-4 md:p-6">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Confirm this worksheet</h2>
        <p className="text-sm">
          Check this attached workbook, answer any questions, then choose whether to load its ready
          rows.
        </p>
        <p className="break-all text-sm font-medium">1. Attached file: {data.source_file}</p>
        <p className="text-sm">{data.summary_message}</p>
      </div>
      {data.missing_optional_message && (
        <section
          className="space-y-2 border border-border p-4"
          aria-label="Missing optional columns"
        >
          <h3 className="font-semibold">{missingStep}. Check missing columns</h3>
          <p className="text-sm">{data.missing_optional_message}</p>
        </section>
      )}
      {blockedSheets.length > 0 && (
        <details
          className="space-y-3 border border-border bg-[var(--primary-soft)] p-4"
          aria-label="Layout not approved"
        >
          <summary className="min-h-11 cursor-pointer font-semibold">
            Advanced layout details
          </summary>
          {blockedSheets.map((item) => {
            const sheet = workbook.sheets.find(
              (candidate) => candidate.batch.load_id === item.load_id,
            );
            return (
              <div key={item.load_id} className="space-y-2">
                <p className="text-sm font-semibold">{item.sheet}</p>
                <p className="text-sm">{item.operator_message}</p>
                {sheet && needsTemplateMapping(sheet) && (
                  <>
                    <FilesMapping
                      id={item.load_id}
                      status={item.status}
                      plant={code}
                      fileHash={hash}
                    />
                    <TemplatePublishDialog code={code} hash={hash} sheet={sheet} />
                  </>
                )}
              </div>
            );
          })}
        </details>
      )}
      {data.extra_columns.length > 0 && (
        <section className="space-y-2 border border-border p-4" aria-label="Extra columns">
          <h3 className="font-semibold">{extraStep}. Decide about extra columns</h3>
          <p className="text-sm">{IGNORE_COPY}</p>
          <p className="text-sm">{data.extra_columns.join(", ")}</p>
          <Button
            className="min-h-11"
            onClick={() => setDecision({ kind: "ignore", headers: data.extra_columns })}
          >
            Review ignored columns
          </Button>
        </section>
      )}
      {data.plant_question && (
        <section className="space-y-2 border border-border p-4" aria-label="Plant question">
          <h3 className="font-semibold">{plantStep}. Which plant is this data from?</h3>
          <p className="text-sm">{data.plant_question.operator_message}</p>
          <p className="text-sm">
            The file says {data.plant_question.plant_texts.join(", ")}. This page is {code}.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              className="min-h-11"
              onClick={() => setDecision({ kind: "plant", plant: code })}
            >
              Yes, this is {code}
            </Button>
            <label className="text-sm">
              Another plant
              <select
                className="ml-2 min-h-11 border border-border bg-background p-2"
                value={otherPlant}
                onChange={(event) => setOtherPlant(event.target.value)}
              >
                <option value="">Choose plant</option>
                {["AAT", "FTM", "FVL", "SAP"]
                  .filter((plant) => plant !== code)
                  .map((plant) => (
                    <option key={plant}>{plant}</option>
                  ))}
              </select>
            </label>
            <Button
              variant="outline"
              className="min-h-11"
              disabled={!otherPlant}
              onClick={() => setDecision({ kind: "plant", plant: otherPlant })}
            >
              Use other plant
            </Button>
          </div>
        </section>
      )}
      <section className="space-y-3" aria-label="Workbook tabs">
        <h3 className="font-semibold">{tabsStep}. Check each tab</h3>
        <ol className="space-y-4">
          {data.sheets.map((item, index) => (
            <li key={item.load_id} className="space-y-3 border border-border p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h4 className="flex flex-wrap items-center gap-2 font-semibold">
                  <span>
                    {index + 1}. {item.sheet}
                  </span>
                  {/* T103 (D-103-3): the same Box / No box the car carries in
                      History, said here before the rows load. The server
                      decides it; null renders nothing. */}
                  <FilmBoxTag box={item.film_box} label="Walk" />
                </h4>
                {item.state !== "not_wavescan" && (
                  <p className="text-xs">
                    {item.rows_ready} ready / {item.rows_held} held out /{" "}
                    {item.rows_already_in_history} already in History
                  </p>
                )}
              </div>
              <p className="text-sm">{item.operator_message}</p>
              {/* RO18 (B3 / B4): the tab's one date question, either domain. */}
              <SheetDateQuestion sheet={item} plant={code} fileHash={hash} />
              {/* T89 Part 5 (D-88-7): one event, said once, above the row
                  table. A tab whose whole panel set was renamed used to be
                  reported as hundreds of unrelated bad rows. */}
              {item.panel_rename?.map((rename) => (
                <p
                  key={rename.model_code}
                  role="alert"
                  data-panel-rename={rename.model_code}
                  className="border border-border p-3 text-sm font-medium"
                >
                  {rename.operator_message}
                </p>
              ))}
              {item.state !== "not_wavescan" && item.rows.length > 0 && (
                <WorksheetRows sheet={item} plant={code} fileHash={hash} />
              )}
              {item.held.some(
                (held) => held.display_group === "empty_identity" || held.display_group === "date",
              ) && <p className="text-sm">{emptyIdentityCopy(item.held)}</p>}
              {item.held.length > 0 && (
                <HeldIdentityList
                  loadId={item.load_id}
                  plant={code}
                  status={item.status}
                  fileHash={hash}
                />
              )}
              {item.hole_rows.length > 0 && (
                <div className="space-y-2 border-l-2 border-primary pl-3">
                  <p className="text-sm">
                    LW/SW are missing on {item.hole_rows.length} rows. We will not fill them in.
                  </p>
                  <Button
                    className="min-h-11"
                    onClick={() =>
                      setDecision({ kind: "holes", loadId: item.load_id, rows: item.hole_rows })
                    }
                  >
                    Approve loading without LW/SW
                  </Button>
                </div>
              )}
              {item.short_vehicles.map((vehicle, index) => (
                <p key={index} className="text-sm">
                  {vehicle.operator_message}
                </p>
              ))}
            </li>
          ))}
        </ol>
      </section>
      {/* RO13 (F14): sticky on desktop only; on a phone it sat over all but one row. */}
      <div className="bottom-0 z-10 flex flex-wrap items-center gap-3 border border-border bg-background p-4 shadow-sm md:sticky">
        <p className="w-full text-sm font-semibold">{tabsStep + 1}. Approve the ready readings</p>
        <Button
          className="min-h-11"
          disabled={
            worksheet.isFetching ||
            data.extra_columns.length > 0 ||
            !!data.plant_question ||
            data.ready_sheet_count === 0 ||
            load.isPending ||
            decide.isPending ||
            !!decision ||
            !!cancelledPlant
          }
          onClick={() => load.mutate(false)}
        >
          Approve
        </Button>
        {remaining && (
          <Button
            variant="outline"
            className="min-h-11"
            disabled={!remainingReady || load.isPending || decide.isPending || !!cancelledPlant}
            onClick={() => load.mutate(true)}
          >
            Load remaining matched rows
          </Button>
        )}
        <p className="text-xs text-muted-foreground">
          Held rows remain visible after loading. Match them here later, then load remaining rows.
        </p>
      </div>
      {load.isError && <ApiErrorState error={load.error} />}
      {decide.isError && <ApiErrorState error={decide.error} />}
      <Dialog
        open={!!decision}
        onOpenChange={(open) => {
          if (!open && !decide.isPending) setDecision(null);
        }}
      >
        <DialogContent>
          <DialogTitle>Confirm worksheet decision</DialogTitle>
          <DialogDescription>
            {decision?.kind === "ignore"
              ? `${IGNORE_COPY} ${decision.headers.join(", ")}`
              : decision?.kind === "holes"
                ? `Load these ${decision.rows.length} rows without LW/SW? The missing values stay empty.`
                : decision?.plant === code
                  ? `Confirm this file belongs to ${code}?`
                  : `Cancel this upload and open the ${decision?.plant} plant page to upload it there?`}
          </DialogDescription>
          <div className="flex gap-2">
            <Button
              className="min-h-11"
              disabled={decide.isPending}
              onClick={() => decision && decide.mutate(decision)}
            >
              Confirm
            </Button>
            <Button
              variant="outline"
              className="min-h-11"
              disabled={decide.isPending}
              onClick={() => setDecision(null)}
            >
              Cancel
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export function WorksheetRows({
  sheet,
  plant,
  fileHash,
}: {
  sheet: components["schemas"]["WorksheetSheetOut"];
  plant: string;
  fileHash: string;
}) {
  const [attentionOnly, setAttentionOnly] = useState(false);
  const alias = useHeldAlias({ loadId: sheet.load_id, plant, status: sheet.status, fileHash });
  // T94 (D-94-3): the rough-panel question lives in the row, so its state
  // lives with the table and not in a dialog.
  const rough = useRoughPanels({ sheet, plant, fileHash });
  // T109 (D-109-6): the Film half of the same in-row question.
  const filmPoints = useFilmPointQuestions({ sheet, plant, fileHash });
  // D-RO17-16: the resolved point reads by the plant's label first.
  const labelOf = usePointLabels(plant);
  // T100 (D-100-5): the sheet's one question, asked once above the table.
  const film = useFilmSheetQuestion({ sheet, plant, fileHash });
  // T100 (D-100-2): the Counted column belongs to a Film tab whose plant x
  // model has a setting. A WaveScan table is unchanged.
  // `counted` is absent on a WaveScan row and null where there is nothing
  // to say, so the column appears only when some row carries a real tick.
  const showCounted = sheet.rows.some((row) => typeof row.counted === "boolean" || row.film_tail);
  const rows = attentionOnly
    ? sheet.rows.filter(
        (row) =>
          // T100 (D-100-4): a tail row is kept and not stored, which is not
          // a thing anybody has to look at.
          !row.film_tail && (row.outcome === "held_out" || row.outcome === "needs_confirmation"),
      )
    : sheet.rows;
  const picker = (
    row: components["schemas"]["WorksheetRowOut"],
    field: "colour" | "model" | "zone",
  ) => {
    if (row.outcome !== "held_out") return null;
    const text =
      field === "colour" ? row.color_text : field === "model" ? row.model_text : row.panel_label;
    const kind =
      field === "colour" ? "ALIAS_COLOR" : field === "model" ? "ALIAS_MODEL" : "ALIAS_CHECKZONE";
    const groups = sheet.held.filter(
      (item) =>
        item.raw_value === text &&
        item.teachable_kind === kind &&
        (item.display_group === field ||
          (field === "colour" && item.display_group === "plant_offer")) &&
        (field !== "zone" || item.model_code === row.model) &&
        canTeach(item, alias.ingest, sheet.status),
    );
    if (groups.length !== 1) return null;
    const item = groups[0];
    const label = field === "zone" ? "Choose panel" : `Choose ${field}`;
    const key = rowKey(item);
    const selectId = `worksheet-pick-${sheet.load_id}-${row.source_row}-${field}`;
    return (
      <div className="mt-2 min-w-40 space-y-1">
        <label className="block text-xs font-medium" htmlFor={selectId}>
          {label}
        </label>
        <select
          id={selectId}
          className="min-h-11 w-full rounded-md border border-border bg-background px-2 text-xs"
          value={alias.choice && rowKey(alias.choice.item) === key ? alias.choice.name : ""}
          disabled={alias.teach.isPending}
          onChange={(event) => {
            if (event.target.value && !alias.teach.isPending)
              alias.setChoice({ item, name: event.target.value });
          }}
        >
          <option value="">{label}</option>
          {item.candidates?.map((candidate) => (
            <option key={candidate} value={candidate}>
              {candidate}
            </option>
          ))}
        </select>
        {alias.rowErrors[key] && <ApiErrorState error={alias.rowErrors[key]} />}
      </div>
    );
  };
  // T94 (D-94-3): the question for this row, or nothing. Rendered in the
  // row's own resolved-panel cell, so the answer never leaves the table.
  const roughCell = (row: components["schemas"]["WorksheetRowOut"]) => {
    if (row.outcome !== "needs_confirmation") return null;
    // T109 (D-109-6): on a Film tab the question in this cell is "which
    // point is this label", never T94's "which panel" -- a Film row is not
    // asked about a panel at all.
    const unknown = filmPoints.questionFor(row.panel_label);
    if (unknown)
      return (
        <FilmPointCell
          label={unknown}
          row={row}
          questions={filmPoints}
          labelOf={(point) => labelOf("film", row.model, point)}
        />
      );
    const panel = rough.questionFor(row.panel_label);
    return panel ? <RoughPanelCell panel={panel} row={row} rough={rough} /> : null;
  };
  const outcomeLabels: Record<components["schemas"]["WorksheetRowOut"]["outcome"], string> = {
    ready: "Ready",
    held_out: "Held out",
    already_in_history: "Already in History",
    // T94 (D-94-2). Never "Ready": the panel name does not say which panel
    // it is, and the answer is one click away in this same row.
    needs_confirmation: "Confirm the panel",
  };
  // T109: a Film tab's needs-confirmation rows are point questions, so the
  // Outcome word is the Film one. Decided per tab, not per row, because a
  // tab is one domain.
  const confirmWord = filmPoints.pending.length > 0 ? "Name the point" : null;
  return (
    <div className="space-y-3">
      <FilmSheetQuestion state={film} />
      {filmPoints.pending.length > 0 && (
        <div
          className="space-y-2 border border-primary bg-[var(--primary-soft)] p-3"
          data-testid="film-point-summary"
          aria-label={`${sheet.sheet} point labels to name`}
        >
          <p className="text-sm font-semibold">{FILM_POINT_COPY.heading}</p>
          <p className="text-sm">
            {sheet.rows_ready > 0 ? FILM_POINT_COPY.explainRestLoads : FILM_POINT_COPY.explain}
          </p>
          <ul className="text-sm">
            {filmPoints.pending.map((label) => (
              <li key={label.raw_location} className="font-mono">
                {label.raw_location}
              </li>
            ))}
          </ul>
        </div>
      )}
      {rough.pending.length > 0 && (
        <div
          className="space-y-2 border border-primary bg-[var(--primary-soft)] p-3"
          data-testid="rough-panel-summary"
          aria-label={`${sheet.sheet} panel names to confirm`}
        >
          <p className="text-sm font-semibold">{ROUGH_PANEL_COPY.heading}</p>
          <p className="text-sm">{ROUGH_PANEL_COPY.explain}</p>
          {rough.prefilled.length > 0 && (
            <Button
              className="min-h-11"
              data-testid="rough-panel-accept-all"
              disabled={rough.confirm.isPending}
              onClick={() => rough.acceptAll()}
            >
              Confirm all {rough.prefilled.length} pre-filled panels
            </Button>
          )}
          {rough.confirm.isError && <ApiErrorState error={rough.confirm.error} />}
        </div>
      )}
      <div role="group" aria-label={`${sheet.sheet} row filter`} className="flex flex-wrap gap-2">
        <Button
          variant={attentionOnly ? "outline" : "default"}
          className="min-h-11"
          aria-pressed={!attentionOnly}
          onClick={() => setAttentionOnly(false)}
        >
          All rows
        </Button>
        <Button
          variant={attentionOnly ? "default" : "outline"}
          className="min-h-11"
          aria-pressed={attentionOnly}
          onClick={() => setAttentionOnly(true)}
        >
          Need attention
        </Button>
      </div>
      <div
        className="ro19-worksheet min-w-0 overflow-x-auto rounded-md border border-border"
        role="region"
        aria-label={`${sheet.sheet} readings`}
        tabIndex={0}
      >
        <style>{`@media (max-width: 639px) {
          .ro19-worksheet table { min-width: 0; table-layout: fixed; }
          .ro19-worksheet thead { display: none; }
          .ro19-worksheet tbody { display: block; }
          .ro19-worksheet tbody tr { display: grid; grid-template-columns: minmax(0, 1fr); }
          .ro19-worksheet tbody td, .ro19-worksheet tbody th { display: block; min-width: 0; width: auto; padding: .5rem .75rem; overflow-wrap: anywhere; }
          .ro19-worksheet [data-label]::before { content: attr(data-label); display: block; margin-bottom: .25rem; font-size: .7rem; font-weight: 600; color: var(--muted-foreground); }
          .ro19-worksheet select, .ro19-worksheet input { max-width: 100%; }
        }`}</style>
        <table className="w-full min-w-[960px] text-left text-sm">
          <caption className="sr-only">
            {sheet.sheet}: {attentionOnly ? "readings that need attention" : "every reading"} in
            file order
          </caption>
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              {[
                "Source row",
                "Panel as written",
                "Outcome",
                ...(showCounted ? ["Counted"] : []),
                "Resolved zone",
                "Model as written",
                "Colour as written",
                "Date as written",
                "Reason",
              ].map((heading) => (
                <th key={heading} scope="col" className="px-3 py-3 font-medium">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.source_sheet}:${row.source_row}`}
                data-outcome={row.outcome}
                data-rough-panel={
                  row.outcome === "needs_confirmation" ? (row.panel_label ?? "") : undefined
                }
                className={`border-t border-border align-top${
                  row.film_tail
                    ? // T100 (D-100-4): muted, never flagged.
                      " text-muted-foreground"
                    : row.outcome === "needs_confirmation"
                      ? // T94 (D-94-3): highlighted, in the table.
                        " border-l-4 border-l-primary bg-[var(--primary-soft)]"
                      : row.outcome === "held_out"
                        ? " bg-[var(--primary-soft)]"
                        : ""
                }`}
              >
                <td data-label="Source row" className="num px-3 py-3">
                  {row.source_row}
                </td>
                <th data-label="Panel as written" scope="row" className="px-3 py-3 font-semibold">
                  {row.panel_label ?? "Not recorded"}
                  {picker(row, "zone")}
                </th>
                <td data-label="Outcome" className="px-3 py-3 font-medium">
                  {/* T100 (D-100-4): the walk's known tail is "Not stored",
                      muted -- not "Held out", not a problem. */}
                  {row.film_tail ? (
                    <span className="text-muted-foreground">Not stored</span>
                  ) : row.outcome === "needs_confirmation" && confirmWord ? (
                    confirmWord
                  ) : (
                    outcomeLabels[row.outcome]
                  )}
                </td>
                {showCounted && (
                  <td data-label="Counted" className="px-3 py-3">
                    {typeof row.counted !== "boolean" ? (
                      <span className="text-muted-foreground">-</span>
                    ) : (
                      <input
                        type="checkbox"
                        readOnly
                        disabled
                        data-testid={`row-counted-${row.source_row}`}
                        aria-label={`Counted ${row.panel_label ?? row.source_row}`}
                        className="size-5"
                        checked={row.counted}
                      />
                    )}
                  </td>
                )}
                <td data-label="Resolved zone" className="px-3 py-3 text-muted-foreground">
                  {roughCell(row) ??
                    (row.checkzone
                      ? pointText(labelOf(null, row.model, row.checkzone), row.checkzone)
                      : "Not resolved")}
                  {/* T109 (D-109-3): the extra tag beside the point this row
                      resolved to. Null on a WaveScan row. */}
                  {row.film_extra && (
                    <span
                      data-testid={`row-extra-${row.source_row}`}
                      className="ml-2 rounded-sm border border-border px-1 text-[0.7rem]"
                    >
                      Extra
                    </span>
                  )}
                </td>
                <td data-label="Model as written" className="px-3 py-3">
                  {row.model_text ?? "Not recorded"}
                  {picker(row, "model")}
                </td>
                <td data-label="Colour as written" className="px-3 py-3">
                  {row.color_text ?? "Not recorded"}
                  {picker(row, "colour")}
                </td>
                <td data-label="Date as written" className="px-3 py-3">
                  {row.date_text ?? "Not recorded"}
                </td>
                <td data-label="Reason" className="min-w-64 px-3 py-3">
                  {row.operator_message}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {attentionOnly && rows.length === 0 && (
        <p role="status" className="text-sm">
          No rows need attention in this tab.
        </p>
      )}
      <HeldAliasConfirmation alias={alias} plant={plant} />
    </div>
  );
}
