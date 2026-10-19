import { useState } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import {
  api,
  batchOptions,
  workbookOptions,
  workbookVehiclesOptions,
  workbookVehiclePointsOptions,
  workbookIssuesOptions,
  refreshPlantWorkbooks,
  refreshActiveMeasurements,
  meOptions,
} from "@/api/queries";
import { isAdmin } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { WorkbookIssues, WorkbookRows, WorkbookHistory, Acknowledge } from "./WorkbookSections";
import { FilesMapping } from "./FilesMapping";
import { HeldIdentityList } from "./HeldIdentityList";
import { FileCounts, FileRange } from "./files-shared";
import { friendlySheetStatus, friendlyStatus } from "./friendly-status";
import { RemoveWorkbook } from "./RemoveWorkbook";
import {
  aggregateRowsExcluded,
  CORRECT_REASON_PRESETS,
  needsUnknownModelAction,
  needsTemplateMapping,
  nextPendingSheet,
  primaryBlockerSentences,
  profilePublishAvailable,
  readinessSummary,
  SHEET_APPROVED_NOTICE,
  sheetClassNotice,
  vehicleHoldBack,
  vehicleTitle,
  carLine,
} from "./review-copy";
import { pointText, usePointLabels } from "./point-labels";
import { dayText } from "./day-text";
import { ReasonPresets } from "./ReasonPresets";
import { TemplatePublishDialog } from "./TemplatePublishDialog";
import { ConfirmWorksheet } from "./ConfirmWorksheet";
import { FILM_LAYERS, orientationLabel } from "@/features/filmthickness/film-overview-display";
import { OdsQuickSummaryNotice } from "./OdsQuickSummaryNotice";
type Sheet = components["schemas"]["WorkbookSheetOut"];
type Point = components["schemas"]["VehiclePointOut"];
type Change = components["schemas"]["OverrideChange"];
const fields: Change["field"][] = [
  "lw",
  "sw",
  "cf",
  "doi",
  "du",
  "wa",
  "wb",
  "wc",
  "wd",
  "we",
  "b",
];
const valueText = (value: unknown) =>
  value === null || value === undefined
    ? "Not available"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
/** RO11: one Film layer of a point, as stored (the file's precision). */
function layerValue(point: Point, source: "raw" | "proposed", code: string): unknown {
  const values =
    source === "raw"
      ? (point.raw?.values as Record<string, unknown> | undefined)
      : (point.proposed?.layers as Record<string, unknown> | undefined);
  return values?.[source === "raw" ? code.toLowerCase() : code];
}
function measureValue(
  point: Point | undefined,
  source: "raw" | "proposed",
  field: string,
): unknown {
  const values = point?.[source]?.[source === "raw" ? "values" : "measures"];
  return values && typeof values === "object" && !Array.isArray(values)
    ? (values as Record<string, unknown>)[field]
    : undefined;
}
export function VehicleReviewDialog({
  code,
  hash,
  sheetId,
  onSheet,
  onClose,
  onApproved,
}: {
  code: string;
  hash: string;
  sheetId?: number;
  onSheet: (id: number) => void;
  onClose: () => void;
  onApproved?: (message: string) => void;
}) {
  const detail = useQuery(workbookOptions(code, hash));
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [approvedIds, setApprovedIds] = useState<number[]>([]);
  const [savedRevisions, setSavedRevisions] = useState<Record<number, string>>({});
  const [reviewedRevisions, setReviewedRevisions] = useState<Record<number, string | undefined>>(
    {},
  );
  const workbook = detail.data?.workbook;
  const sheet =
    workbook?.sheets.find((item) => item.batch.load_id === sheetId) ?? workbook?.sheets[0];
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="!inset-0 !left-0 !top-0 flex !h-[100dvh] !w-screen !max-w-none !translate-x-0 !translate-y-0 flex-col gap-0 overflow-hidden !rounded-none p-0">
        <header className="shrink-0 space-y-2 border-b border-border px-4 py-4 pr-12 md:px-6 md:pr-14">
          <p className="eyebrow">{code} / Upload Data / Review</p>
          <DialogTitle className="break-all">
            {workbook?.source_file ?? "Workbook review"}
          </DialogTitle>
          <DialogDescription>
            Confirm the whole worksheet. Original source evidence is retained.
          </DialogDescription>
          {notice && (
            <p role="status" className="text-sm">
              {notice}
            </p>
          )}
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {detail.isPending ? (
            <LoadingState>Loading workbook...</LoadingState>
          ) : detail.isError && !workbook ? (
            <ApiErrorState error={detail.error} retry={() => void detail.refetch()} />
          ) : (
            workbook && (
              <>
                {detail.isError && (
                  <ApiErrorState error={detail.error} retry={() => void detail.refetch()} />
                )}
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-[var(--primary-soft)] px-4 py-3 md:px-6">
                  <div>
                    <p className="font-semibold">{friendlyStatus(workbook)}</p>
                    <FileRange workbook={workbook} />
                    {workbook.measured_dates_span_months && (
                      <p className="text-xs">Measurements span calendar months.</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {workbook.sheet_count > 1 && (
                      <label className="text-xs">
                        Sheet
                        <select
                          aria-label="Sheet"
                          value={sheet?.batch.load_id}
                          onChange={(event) => onSheet(Number(event.target.value))}
                          className="ml-2 max-w-48 border border-border bg-background p-2"
                        >
                          {workbook.sheets.map((item) => (
                            <option key={item.batch.load_id} value={item.batch.load_id}>
                              {item.batch.source_sheet}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    <RemoveWorkbook
                      code={code}
                      workbook={workbook}
                      disabled={detail.isError || detail.isFetching}
                      onNotice={setNotice}
                      onClosed={onClose}
                    />
                  </div>
                </div>
                <OdsQuickSummaryNotice workbook={workbook} className="mx-4 mt-4 md:mx-6" />
                <ConfirmWorksheet
                  code={code}
                  hash={hash}
                  workbook={workbook}
                  onLoaded={(message) => {
                    onApproved?.(message);
                    onClose();
                  }}
                />
                {sheet && (
                  <details className="m-4 border border-border p-4 md:mx-6">
                    <summary className="cursor-pointer text-sm font-semibold">
                      Vehicle evidence
                    </summary>
                    <SheetReview
                      key={sheet.batch.load_id}
                      code={code}
                      hash={hash}
                      sheet={sheet}
                      workbook={workbook}
                      allowCommit={false}
                      refreshing={detail.isFetching || detail.isError}
                      savedRevision={savedRevisions[sheet.batch.load_id]}
                      reviewedRevision={reviewedRevisions[sheet.batch.load_id]}
                      onSaved={(revision) => {
                        setSavedRevisions((previous) => ({
                          ...previous,
                          [sheet.batch.load_id]: revision,
                        }));
                        setReviewedRevisions((previous) => ({
                          ...previous,
                          [sheet.batch.load_id]: undefined,
                        }));
                      }}
                      onReviewed={(revision) =>
                        setReviewedRevisions((previous) => ({
                          ...previous,
                          [sheet.batch.load_id]: revision,
                        }))
                      }
                      onCommitted={(loadId) => {
                        const next = nextPendingSheet(workbook.sheets, loadId, approvedIds);
                        setApprovedIds((previous) => [...previous, loadId]);
                        if (next) {
                          onSheet(next.batch.load_id);
                          return;
                        }
                        onApproved?.(SHEET_APPROVED_NOTICE);
                        onClose();
                      }}
                    />
                  </details>
                )}
                <details
                  className="m-4 border border-border p-4 md:mx-6"
                  open={detailsOpen}
                  onToggle={(event) => setDetailsOpen(event.currentTarget.open)}
                >
                  <summary className="cursor-pointer text-sm font-semibold">Details</summary>
                  {detailsOpen && (
                    <div className="mt-4 space-y-5">
                      <section className="space-y-2">
                        <h3 className="font-semibold">Summary</h3>
                        <p className="break-all text-xs">
                          Workbook {hash} / {workbook.operational_summary}
                        </p>
                        <FileCounts counts={workbook.counts} />
                        {workbook.sheets.map((item) => (
                          <div key={item.batch.load_id} className="space-y-1 text-xs">
                            <p>
                              {item.batch.source_sheet}: {item.batch.status} / review revision{" "}
                              {item.batch.review_revision ?? "not available"}
                            </p>
                            <p className="break-all text-muted-foreground">
                              domain: {item.batch.domain ?? "not available"} / sheet_class:{" "}
                              {item.batch.sheet_class ?? "not available"} / semantic_signature:{" "}
                              {item.batch.semantic_signature ?? "not available"}
                            </p>
                            <p className="break-all text-muted-foreground">
                              unreviewed_headers:{" "}
                              {(item.batch.unreviewed_headers ?? []).join(", ") || "none"}
                            </p>
                          </div>
                        ))}
                        {detail.data?.profiles.map((profile) => (
                          <p key={profile.profile_id} className="text-xs">
                            Profile {profile.profile_id} / version {profile.version} / fixture
                            verified: {String(profile.fixture_verified)}
                          </p>
                        ))}
                      </section>
                      <details>
                        <summary className="cursor-pointer text-sm">Issues</summary>
                        <WorkbookIssues code={code} hash={hash} sheets={workbook.sheets} />
                      </details>
                      {sheet &&
                        !needsTemplateMapping(sheet) &&
                        sheet.batch.sheet_class !== "OUT_OF_SCOPE_SHEET" &&
                        ["PENDING_REVIEW", "REJECTED_TEMPLATE", "RUNNING"].includes(
                          sheet.batch.status,
                        ) && (
                          <details>
                            <summary className="cursor-pointer text-sm">Mapping review</summary>
                            <FilesMapping
                              id={sheet.batch.load_id}
                              status={sheet.batch.status}
                              plant={code}
                            />
                          </details>
                        )}
                      <LazyEvidence code={code} hash={hash} />
                    </div>
                  )}
                </details>
              </>
            )
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
function LazyEvidence({ code, hash }: { code: string; hash: string }) {
  const [rows, setRows] = useState(false);
  const [history, setHistory] = useState(false);
  return (
    <>
      <details onToggle={(event) => setRows(event.currentTarget.open)}>
        <summary className="cursor-pointer text-sm">Data rows</summary>
        {rows && <WorkbookRows code={code} hash={hash} />}
      </details>
      <details onToggle={(event) => setHistory(event.currentTarget.open)}>
        <summary className="cursor-pointer text-sm">History</summary>
        {history && <WorkbookHistory code={code} hash={hash} />}
      </details>
    </>
  );
}
function SheetReview({
  code,
  hash,
  sheet,
  workbook,
  allowCommit = true,
  refreshing,
  savedRevision,
  reviewedRevision,
  onSaved,
  onReviewed,
  onCommitted,
}: {
  code: string;
  hash: string;
  sheet: Sheet;
  workbook: components["schemas"]["WorkbookOut"];
  allowCommit?: boolean;
  refreshing: boolean;
  savedRevision?: string;
  reviewedRevision?: string;
  onSaved: (revision: string) => void;
  onReviewed: (revision?: string) => void;
  onCommitted: (loadId: number) => void;
}) {
  const classifiedOther =
    sheet.batch.sheet_class === "OUT_OF_SCOPE_SHEET" ||
    sheet.batch.sheet_class === "UNKNOWN_DATA_SHEET";
  const vehicles = useQuery({
    ...workbookVehiclesOptions(code, hash, sheet.batch.load_id),
    enabled: !classifiedOther,
  });
  const issues = useQuery(workbookIssuesOptions(code, hash));
  const batchReview = useQuery({
    ...batchOptions(sheet.batch.load_id),
    enabled: sheet.batch.sheet_class === "WAVESCAN",
  });
  const [selected, setSelected] = useState<string>();
  const reviewRequired = !!savedRevision;
  const [hasDrafts, setHasDrafts] = useState(false);
  const client = useQueryClient();
  const vehicle =
    vehicles.data?.items.find((item) => item.vehicle_id === selected) ?? vehicles.data?.items[0];
  const points = useQuery({
    ...workbookVehiclePointsOptions(code, hash, vehicle?.vehicle_id ?? ""),
    enabled: !classifiedOther && !!vehicle,
  });
  const evidenceUnavailable =
    refreshing ||
    !vehicles.isSuccess ||
    vehicles.isFetching ||
    !issues.isSuccess ||
    issues.isFetching ||
    (!!vehicle && (!points.isSuccess || points.isFetching));
  const commit = useMutation({
    mutationFn: () => api().commit(sheet.batch.load_id),
    retry: false,
    onSuccess: async () => {
      await refreshActiveMeasurements(client);
      await refreshPlantWorkbooks(client, code);
      onCommitted(sheet.batch.load_id);
    },
    onError: async () => {
      await refreshActiveMeasurements(client);
      await refreshPlantWorkbooks(client, code);
    },
  });
  const currentIssues =
    issues.data?.issues.filter(
      (issue) => issue.load_id === null || issue.load_id === sheet.batch.load_id,
    ) ?? [];
  const classNotice = sheetClassNotice(sheet, workbook);
  const blockerSentences = primaryBlockerSentences(sheet);
  const aggregateCount = aggregateRowsExcluded(batchReview.data);
  const extraHeaders = sheet.batch.unreviewed_headers ?? [];
  const templateMapping = needsTemplateMapping(sheet);
  const unknownModel = needsUnknownModelAction(sheet);
  return (
    <>
      {!classifiedOther && (templateMapping || unknownModel) && (
        <section
          className="space-y-3 border-b border-border bg-[var(--primary-soft)] p-4 md:px-6"
          aria-label="Mapping review"
        >
          <h3 className="text-sm font-semibold">Map this sheet</h3>
          {templateMapping && (
            <p className="text-sm">
              This layout is not approved yet. Map its headers and model spelling here, then publish
              the verified template. Approve stays disabled until the sheet is committable.
            </p>
          )}
          {unknownModel && (
            <p className="text-sm">
              Unknown model rows are held back. Map the spelling to an existing model, or review the
              hold-back before approving eligible rows.
            </p>
          )}
          <FilesMapping
            id={sheet.batch.load_id}
            status={sheet.batch.status}
            plant={code}
            defaultKind={unknownModel && !templateMapping ? "ALIAS_MODEL" : "COLUMN"}
            compact={unknownModel && !templateMapping}
          />
          {templateMapping && profilePublishAvailable(sheet) && (
            <TemplatePublishDialog code={code} hash={hash} sheet={sheet} />
          )}
        </section>
      )}
      <section
        aria-label="Sheet readiness"
        className="space-y-2 border-b border-border px-4 py-3 md:px-6"
      >
        <h3 className="text-sm font-semibold">
          {sheet.batch.source_sheet}: {friendlySheetStatus(sheet)}
        </h3>
        {classNotice && (
          <p className="border-l-2 border-primary bg-[var(--primary-soft)] p-3 text-sm">
            {classNotice}
          </p>
        )}
        {sheet.commit_blockers.length > 0 && (
          <div className="space-y-2">
            {blockerSentences.length > 0 && (
              <ul className="list-disc space-y-1 pl-4 text-xs">
                {blockerSentences.map((sentence) => (
                  <li key={sentence}>{sentence}</li>
                ))}
              </ul>
            )}
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Technical detail</summary>
              <p className="mt-1">{sheet.commit_blockers.join(", ")}</p>
            </details>
          </div>
        )}
        {extraHeaders.length > 0 && sheet.batch.sheet_class === "WAVESCAN" && (
          <section aria-label="Extra columns" className="space-y-2 border border-border p-3">
            <p className="text-xs font-semibold">Extra columns need a decision</p>
            <ul className="list-disc space-y-1 pl-4 text-xs">
              {extraHeaders.map((header) => (
                <li key={header}>{header}</li>
              ))}
            </ul>
            <p className="text-xs">
              Map a header in Mapping review above, or have a named owner publish this stored layout
              and give every ignored header a reason.
            </p>
            {!templateMapping && profilePublishAvailable(sheet) && (
              <TemplatePublishDialog code={code} hash={hash} sheet={sheet} />
            )}
          </section>
        )}
        {extraHeaders.length === 0 && !templateMapping && profilePublishAvailable(sheet) && (
          <TemplatePublishDialog code={code} hash={hash} sheet={sheet} />
        )}
        {aggregateCount > 0 && (
          <p className="text-xs">
            {aggregateCount} report roll-up rows excluded from measurements ([All]).
          </p>
        )}
        {issues.isPending ? (
          <LoadingState>Checking readiness...</LoadingState>
        ) : issues.isError ? (
          <ApiErrorState error={issues.error} retry={() => void issues.refetch()} />
        ) : (
          <p className="text-xs">
            {sheet.commit_blockers.length > 0
              ? "No additional row warnings."
              : readinessSummary(currentIssues)}
          </p>
        )}
        {currentIssues.some((issue) => issue.token === "POSSIBLE_REPLACEMENT") && (
          <p className="text-xs">
            Possible replacement is advisory. It does not block approval or retire another file.
          </p>
        )}
        {savedRevision && (
          <p role="status" className="break-all text-xs">
            Overrides saved. New review revision: {savedRevision}. Review the new proposal and
            acknowledge required warnings again.
          </p>
        )}
        {allowCommit &&
          sheet.batch.sheet_class === "WAVESCAN" &&
          (sheet.batch.status === "PENDING_REVIEW" ||
            sheet.batch.status === "REJECTED_TEMPLATE" ||
            sheet.batch.status === "COMMITTED") && (
            <HeldIdentityList
              loadId={sheet.batch.load_id}
              plant={code}
              status={sheet.batch.status}
            />
          )}
      </section>
      {!classifiedOther && (
        <div className="grid min-w-0 md:grid-cols-[280px_minmax(0,1fr)]">
          <aside
            aria-label="Vehicle sets"
            className="space-y-2 border-b border-border p-4 md:border-b-0 md:border-r"
          >
            <h3 className="eyebrow">Vehicle sets</h3>
            {vehicles.isPending ? (
              <LoadingState>Loading vehicle sets...</LoadingState>
            ) : vehicles.isError ? (
              <ApiErrorState error={vehicles.error} retry={() => void vehicles.refetch()} />
            ) : (
              <>
                {!vehicles.data.items.length && (
                  <p className="text-sm text-muted-foreground">
                    No vehicle sets yet. Wait for processing or review template mapping in Details.
                  </p>
                )}
                {vehicles.data.items.map((item) => {
                  const holdBack = vehicleHoldBack(item);
                  return (
                    <button
                      key={item.vehicle_id}
                      type="button"
                      disabled={hasDrafts}
                      aria-pressed={vehicle?.vehicle_id === item.vehicle_id}
                      onClick={() => setSelected(item.vehicle_id)}
                      className={`block w-full space-y-1 rounded-sm border border-border p-3 text-left text-xs aria-pressed:border-primary aria-pressed:bg-[var(--primary-soft)] disabled:opacity-60${
                        holdBack ? " border-l-4 border-l-primary" : ""
                      }`}
                    >
                      <strong className="block">{vehicleTitle(item)}</strong>
                      {carLine(item, vehicleTitle(item)) && (
                        <span className="block">{item.car_label}</span>
                      )}
                      {holdBack && (
                        <span className="inline-block rounded-sm border border-primary bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
                          {holdBack}
                        </span>
                      )}
                      <span className="block">
                        {item.model ?? "Model unavailable"} / {item.color ?? "Colour unavailable"}
                      </span>
                      <span className="block">
                        {item.measured_date
                          ? dayText(item.measured_date, item.date_is_month_only)
                          : "Measured date unavailable"}
                      </span>
                      <span className="block">
                        {item.point_count} of{" "}
                        {item.expected_point_count ?? "expected not available"}
                      </span>
                      {item.incomplete_set && (
                        <span className="block font-semibold">Incomplete set</span>
                      )}
                      <span className="block">
                        {Object.entries(item.dispositions)
                          .map(([key, value]) => `${key}: ${value}`)
                          .join(" / ")}
                      </span>
                    </button>
                  );
                })}
              </>
            )}
          </aside>
          <div className="min-w-0 p-4 md:p-6">
            {vehicle ? (
              <VehiclePoints
                key={vehicle.vehicle_id}
                code={code}
                hash={hash}
                vehicleId={vehicle.vehicle_id}
                points={points}
                sheet={sheet}
                refreshing={refreshing || vehicles.isFetching || vehicles.isError}
                onDrafts={setHasDrafts}
                onSaved={onSaved}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                Select a vehicle set to inspect its points.
              </p>
            )}
          </div>
        </div>
      )}
      {!classifiedOther && allowCommit && (
        <footer className="sticky bottom-0 z-10 space-y-3 border-y border-border bg-background p-4 shadow-sm md:px-6">
          {sheet.batch.status === "PENDING_REVIEW" &&
            sheet.required_acknowledgements
              .filter(
                (category) =>
                  !sheet.acknowledged.includes(category) && category !== "POSSIBLE_REPLACEMENT",
              )
              .map((category) => (
                <Acknowledge
                  key={`${category}-${sheet.batch.load_id}`}
                  code={code}
                  hash={hash}
                  sheet={sheet}
                  category={category}
                />
              ))}
          {reviewRequired && (
            <label className="flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                disabled={evidenceUnavailable || hasDrafts}
                checked={reviewedRevision === sheet.batch.review_revision}
                onChange={(event) =>
                  onReviewed(
                    event.target.checked ? (sheet.batch.review_revision ?? undefined) : undefined,
                  )
                }
              />
              I reviewed the new revision and its proposed points.
            </label>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button
              disabled={
                !sheet.committable ||
                evidenceUnavailable ||
                hasDrafts ||
                commit.isPending ||
                issues.isError ||
                issues.isPending ||
                (reviewRequired && reviewedRevision !== sheet.batch.review_revision)
              }
              onClick={() => commit.mutate()}
            >
              Approve sheet
            </Button>
            <p className="text-xs text-muted-foreground">
              Approval applies to the whole eligible sheet.
            </p>
          </div>
          {commit.isError && <ApiErrorState error={commit.error} />}
        </footer>
      )}
    </>
  );
}
export function VehiclePoints({
  code,
  hash,
  vehicleId,
  points,
  sheet,
  onDrafts,
  onSaved,
  refreshing,
}: {
  code: string;
  hash: string;
  vehicleId: string;
  points: UseQueryResult<components["schemas"]["VehiclePointPage"], Error>;
  sheet: Sheet;
  refreshing: boolean;
  onDrafts: (value: boolean) => void;
  onSaved: (revision: string) => void;
}) {
  const [editing, setEditing] = useState<Point>();
  const [field, setField] = useState<Change["field"]>("cf");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [drafts, setDrafts] = useState<Change[]>([]);
  const [confirm, setConfirm] = useState(false);
  const [draftRevision, setDraftRevision] = useState<string>();
  const client = useQueryClient();
  // RO11 (D-RO11-6): a Film sheet's points are Film points, never Wave Scan measures.
  const film = sheet.batch.sheet_class === "FILMTHICKNESS";
  // RO12 (D-RO12-4): an override is an Admin route; other roles are not offered Edit.
  const identity = useQuery(meOptions);
  const eligible =
    sheet.batch.status === "PENDING_REVIEW" &&
    !film &&
    identity.isSuccess &&
    isAdmin(identity.data.principal);
  const unavailable = refreshing || points.isFetching || points.isError;
  // D-RO17-16: a point reads by the plant's label first, its code beside it.
  const labelOf = usePointLabels(code);
  const pointName = (point: Point) =>
    point.checkzone
      ? pointText(
          labelOf(film ? "film" : "wavescan", points.data?.vehicle?.model, point.checkzone),
          point.checkzone,
        )
      : null;
  /** The plant's own word for this reading, as the file wrote it. */
  const inFile = (point: Point) => {
    const raw = point.proposed?.[film ? "src_location_text" : "src_zone_text"];
    return typeof raw === "string" && raw ? raw : null;
  };
  const save = useMutation({
    mutationFn: () =>
      api().overrideWorkbook(code, hash, {
        load_id: sheet.batch.load_id,
        vehicle_id: vehicleId,
        review_revision: draftRevision!,
        changes: drafts,
      }),
    retry: false,
    onSuccess: (result) => {
      setDrafts([]);
      setConfirm(false);
      setEditing(undefined);
      onSaved(result.review_revision);
    },
    onError: () => {
      setConfirm(false);
      setDrafts([]);
      setEditing(undefined);
      onDrafts(false);
    },
    onSettled: async () => {
      try {
        await refreshPlantWorkbooks(client, code);
      } finally {
        onDrafts(false);
      }
    },
  });
  const validValue =
    (field === "b" && value.trim() === "") || /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value.trim());
  const clear = () => {
    setDrafts([]);
    setEditing(undefined);
    setConfirm(false);
    onDrafts(false);
  };
  return (
    <section aria-label="Vehicle points" className="space-y-4">
      {film ? (
        points.data && (
          <h3 className="text-base font-semibold">
            {points.data.vehicle.point_count} of{" "}
            {points.data.vehicle.expected_point_count ?? "expected not available"} points
            {points.data.vehicle.incomplete_set ? " / Incomplete set" : ""}
          </h3>
        )
      ) : (
        <>
          <h3 className="text-base font-semibold">Points / raw and proposed</h3>
          <p className="text-xs text-muted-foreground">
            Identity fields use mapping or a corrected re-upload. Only measure values can be
            proposed here.
          </p>
        </>
      )}
      {points.isPending ? (
        <LoadingState>Loading points...</LoadingState>
      ) : points.isError ? (
        <ApiErrorState error={points.error} retry={() => void points.refetch()} />
      ) : (
        points.data.items.map((point) => (
          <article
            key={`${point.source_row}-${point.measurement_id ?? "review"}`}
            className="space-y-3 rounded-sm border border-border p-3"
          >
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-sm font-semibold">
                {film
                  ? `${pointName(point) ?? "Point unavailable"}${
                      point.proposed?.orientation === "H" || point.proposed?.orientation === "V"
                        ? ` / ${orientationLabel(point.proposed.orientation)}`
                        : ""
                    } / ${point.disposition}`
                  : `${pointName(point) ?? "Checkzone unavailable"} / ${point.disposition}`}
              </h4>
              {eligible && point.disposition === "LOAD" && (
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`Edit ${point.checkzone ?? "point"} row ${point.source_row}`}
                  disabled={save.isPending || confirm || unavailable}
                  onClick={() => {
                    setEditing(point);
                    setField("cf");
                    setValue(
                      measureValue(point, "proposed", "cf") == null
                        ? ""
                        : String(measureValue(point, "proposed", "cf")),
                    );
                    setReason("");
                    onDrafts(true);
                  }}
                >
                  Edit
                </Button>
              )}
            </div>
            {inFile(point) && (
              <p className="text-xs text-muted-foreground">In the file: {inFile(point)}</p>
            )}
            {point.projection_missing && (
              <p className="text-xs font-semibold">
                Projection missing. Raw source evidence is not available for this point.
              </p>
            )}
            {(point.reason || point.detail) && (
              <p className="text-xs">
                {point.reason} {point.detail}
              </p>
            )}
            {film ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="py-1">Layer</th>
                      <th>Proposed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {FILM_LAYERS.map((layer) => {
                      const proposed = layerValue(point, "proposed", layer.code);
                      const raw = layerValue(point, "raw", layer.code);
                      const differs =
                        raw !== null &&
                        raw !== undefined &&
                        raw !== "" &&
                        Number(raw) !== Number(proposed);
                      return (
                        <tr key={layer.code} className="border-b border-border/50">
                          <th className="py-1 font-medium">{layer.label}</th>
                          <td className="font-mono">
                            {proposed == null ? "Not measured" : String(proposed)}
                            {differs && (
                              <span className="ml-2 font-sans text-muted-foreground">
                                File: {String(raw)}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="py-1">Measure</th>
                      <th>Raw</th>
                      <th>Proposed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fields.map((measure) => (
                      <tr key={measure} className="border-b border-border/50">
                        <th className="py-1 font-medium">{measure.toUpperCase()}</th>
                        <td className="pr-3">{valueText(measureValue(point, "raw", measure))}</td>
                        <td>{valueText(measureValue(point, "proposed", measure))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <details className="text-xs">
              <summary className="cursor-pointer">Full source evidence</summary>
              <pre className="mt-2 whitespace-pre-wrap break-all">
                {JSON.stringify({ raw: point.raw, proposed: point.proposed }, null, 2)}
              </pre>
            </details>
            {point.current_overrides.map((override) => (
              <div key={override.override_id} className="border-t border-border pt-2 text-xs">
                <p>
                  {override.field}: previous {valueText(override.previous_proposed)} / new{" "}
                  {valueText(override.new_value)}
                </p>
                <p>Reason: {override.reason}</p>
                <p className="font-semibold">
                  {override.applied
                    ? "Applied to the current proposal"
                    : "Not applied: the current proposed value does not carry this override"}
                </p>
              </div>
            ))}
          </article>
        ))
      )}
      {editing && eligible && (
        <form
          className="space-y-3 border border-primary bg-[var(--primary-soft)] p-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!validValue || !reason.trim() || unavailable) return;
            const change: Change = {
              source_row: editing.source_row,
              field,
              value: field === "b" && !value.trim() ? null : value.trim(),
              reason: reason.trim(),
            };
            setDrafts((previous) => [
              ...previous.filter(
                (item) => item.source_row !== change.source_row || item.field !== change.field,
              ),
              change,
            ]);
            if (!drafts.length) setDraftRevision(sheet.batch.review_revision ?? undefined);
            setEditing(undefined);
          }}
        >
          <h4 className="font-semibold">Edit {pointName(editing) ?? "point"}</h4>
          <label className="block text-xs">
            Measure field
            <select
              aria-label="Measure field"
              value={field}
              onChange={(event) => {
                const next = event.target.value as Change["field"];
                setField(next);
                setValue(
                  measureValue(editing, "proposed", next) == null
                    ? ""
                    : String(measureValue(editing, "proposed", next)),
                );
              }}
              className="ml-2 border border-border bg-background p-2"
            >
              {fields.map((item) => (
                <option key={item} value={item}>
                  {item.toUpperCase()}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs">
            New proposed value
            <input
              aria-label="New proposed value"
              inputMode="decimal"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              className="mt-1 block w-full border border-border bg-background p-2"
            />
          </label>
          {field === "b" && <p className="text-xs">Leave blank to propose a null B value.</p>}
          <ReasonPresets
            label="Override reason"
            ariaLabel="Override reason"
            value={reason}
            onChange={setReason}
            presets={CORRECT_REASON_PRESETS}
          />
          <Button
            type="submit"
            disabled={unavailable || !validValue || !reason.trim() || reason.trim().length > 2000}
          >
            Add draft
          </Button>
        </form>
      )}
      {(drafts.length > 0 || editing) && (
        <div className="sticky bottom-0 space-y-3 border border-border bg-background p-3">
          <p className="text-sm">{drafts.length} proposed changes for this vehicle set</p>
          {confirm && (
            <section aria-label="Confirm overrides" className="space-y-2">
              <h4 className="font-semibold">Confirm overrides</h4>
              {drafts.map((draft) => {
                const point = points.data?.items.find(
                  (item) => item.source_row === draft.source_row,
                );
                return (
                  <p key={`${draft.source_row}-${draft.field}`} className="break-words text-xs">
                    Row {draft.source_row} / {draft.field}: raw{" "}
                    {valueText(measureValue(point, "raw", draft.field))}; previous proposed{" "}
                    {valueText(measureValue(point, "proposed", draft.field))}; new proposed{" "}
                    {draft.value ?? "null"}; reason: {draft.reason}
                  </p>
                );
              })}
            </section>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={
                !eligible ||
                unavailable ||
                !drafts.length ||
                !!editing ||
                save.isPending ||
                !draftRevision
              }
              onClick={() => (confirm ? save.mutate() : setConfirm(true))}
            >
              {confirm ? "Confirm overrides" : "Review changes"}
            </Button>
            <Button variant="outline" disabled={save.isPending} onClick={clear}>
              Discard drafts
            </Button>
          </div>
        </div>
      )}
      {save.isError && <ApiErrorState error={save.error} />}
    </section>
  );
}
