import type { components } from "@/api/types";
import { blockerCopy, tokenHeadline } from "@/api/error-copy";

type Sheet = components["schemas"]["WorkbookSheetOut"];
type Workbook = components["schemas"]["WorkbookOut"];

export const IGNORE_COPY = "We do not use this column. Ignore it and keep the rest?";
export const LOAD_LABEL = "Yes, load these rows.";
export const EMPTY_IDENTITY_COPY =
  "We will not guess. These rows will not load. Fix the Excel file and upload again, or remove this file and upload again.";

type Held = components["schemas"]["HeldLabelGroup"];

/** RO15: a date group held on its Month / Year cell has a date; it disagrees. */
export const disagreesWithMonth = (item: Held) =>
  item.display_group === "date" && (item.column === "month" || item.column === "year");

export function emptyIdentityCopy(held: Held[]) {
  // D-RO17-18: say RO15's own row sentence (the server's), never "no date".
  const disagree = new Set(held.filter(disagreesWithMonth).map((item) => item.operator_message));
  const missing = new Set(
    held
      .filter(
        (item) =>
          !disagreesWithMonth(item) &&
          (item.display_group === "empty_identity" || item.display_group === "date"),
      )
      .map((item) =>
        item.display_group === "date"
          ? "date"
          : item.column === "color"
            ? "colour"
            : item.column === "model"
              ? "model"
              : "identity",
      ),
  );
  const none = missing.size
    ? `These rows have no ${[...missing].join(" or no ")}. ${EMPTY_IDENTITY_COPY}`
    : "";
  return [...disagree, none].filter(Boolean).join(" ");
}

export const RETIRE_REASON_PRESETS = [
  "Incorrect workbook",
  "Wrong plant file",
  "Duplicate send",
  "Replaced by a later file",
  "Other",
] as const;

export const CORRECT_REASON_PRESETS = [
  "Instrument check",
  "Transcription error",
  "Plant resent values",
  "Other",
] as const;

export const ACK_NOTE_PRESETS: Record<string, readonly string[]> = {
  QUARANTINED_MODELS: ["Unknown model rows held back; remaining rows reviewed", "Other"],
  REJECTED_ROWS: ["Rejected rows reviewed; they will not load", "Other"],
  DUPLICATE_ROWS: ["Duplicate rows reviewed; they will not load", "Other"],
};

export { tokenHeadline };

export function blockerSentence(token: string, sheet?: Sheet) {
  if (token === "WARNINGS_UNACKNOWLEDGED" && sheet) {
    const required = sheet.required_acknowledgements;
    if (required.includes("QUARANTINED_MODELS")) return blockerCopy("QUARANTINED_MODELS");
    if (required.includes("REJECTED_ROWS"))
      return "Rejected rows will not load. Acknowledge that hold-back after reviewing the evidence, then approve the rest.";
    if (required.includes("DUPLICATE_ROWS"))
      return "Duplicate rows will not load. Acknowledge that hold-back after reviewing the evidence, then approve the rest.";
  }
  return blockerCopy(token);
}

export function noUsableQuickSummary(workbook: Workbook) {
  if (!/\.ods$/i.test(workbook.source_file)) return false;
  const current = workbook.sheets.filter(
    (sheet) => !["ABANDONED", "SUPERSEDED"].includes(sheet.batch.status),
  );
  return (
    current.length > 0 && current.every((sheet) => sheet.batch.sheet_class === "OUT_OF_SCOPE_SHEET")
  );
}

export function sheetClassNotice(sheet: Sheet, workbook?: Workbook) {
  if (sheet.batch.sheet_class === "OUT_OF_SCOPE_SHEET") {
    const odsFilmReview =
      workbook &&
      /\.ods$/i.test(workbook.source_file) &&
      (noUsableQuickSummary(workbook) ||
        workbook.sheets.some(
          (item) =>
            !["ABANDONED", "SUPERSEDED"].includes(item.batch.status) &&
            item.batch.sheet_class === "FILMTHICKNESS",
        ));
    if (odsFilmReview)
      return "This tab is kept as evidence. Film Thickness measurements need usable Quick Summary data; this tab cannot be approved as Film measurements.";
    return blockerCopy("OUT_OF_SCOPE_SHEET");
  }
  if (sheet.batch.sheet_class === "UNKNOWN_DATA_SHEET") return blockerCopy("UNKNOWN_DATA_SHEET");
  return null;
}

export function primaryBlockerSentences(sheet: Sheet) {
  const sheetClass = sheet.batch.sheet_class;
  if (sheetClass !== "OUT_OF_SCOPE_SHEET" && sheetClass !== "UNKNOWN_DATA_SHEET") {
    return sheet.commit_blockers.map((token) => blockerSentence(token, sheet));
  }

  const classToken = sheetClass;
  return sheet.commit_blockers
    .filter(
      (token) =>
        token !== classToken && token !== "UNKNOWN_TEMPLATE" && token !== "NOT_PENDING_REVIEW",
    )
    .map((token) => blockerSentence(token, sheet));
}

export function aggregateRowsExcluded(review: components["schemas"]["BatchReviewOut"] | undefined) {
  return review?.review_dispositions?.AGGREGATE_ROW ?? 0;
}

export function profilePublishAvailable(sheet: Sheet) {
  return (
    sheet.batch.sheet_class === "WAVESCAN" &&
    (sheet.batch.status === "REJECTED_TEMPLATE" ||
      sheet.commit_blockers.some(
        (token) => token === "UNKNOWN_TEMPLATE" || token === "REJECTED_TEMPLATE",
      ) ||
      sheet.commit_blockers.some(
        (token) => token === "UNREVIEWED_HEADER" || token === "UNVERIFIED_PROFILE",
      ))
  );
}

export function needsTemplateMapping(sheet: Sheet) {
  return (
    sheet.batch.sheet_class === "WAVESCAN" &&
    (sheet.batch.status === "REJECTED_TEMPLATE" ||
      sheet.commit_blockers.some(
        (token) =>
          token === "UNKNOWN_TEMPLATE" ||
          token === "REJECTED_TEMPLATE" ||
          token === "UNREVIEWED_HEADER" ||
          token === "UNVERIFIED_PROFILE",
      ))
  );
}

export function showsFillMissingPlant(sheet: Sheet) {
  const blockerNamesPlant = sheet.commit_blockers.some(
    (token) => token.includes("PLANT") && token.includes("MISSING"),
  );
  const notes = sheet.batch.notes ?? "";
  const notesNamePlant = /\bplant\b/i.test(notes);
  const notesNameMissing = /\b(missing|omitted|absent)\b/i.test(notes);
  return blockerNamesPlant || (notesNamePlant && notesNameMissing);
}

export function needsUnknownModelAction(sheet: Sheet) {
  return (
    sheet.batch.counts.rows_quarantine > 0 ||
    sheet.required_acknowledgements.includes("QUARANTINED_MODELS")
  );
}

export function inboxWarning(file: Workbook) {
  const live = file.sheets.filter(
    (sheet) => !["ABANDONED", "SUPERSEDED"].includes(sheet.batch.status),
  );
  if (live.length > 0 && live.every((sheet) => sheet.batch.sheet_class === "OUT_OF_SCOPE_SHEET"))
    return "Other tabs kept as evidence";
  if (file.counts.rows_quarantine > 0) return "Unknown model held back";
  if (file.counts.rows_rejected > 0) return "Rejected rows";
  if (file.sheets.some((sheet) => sheet.batch.status === "PENDING_REVIEW" && !sheet.committable))
    return "Needs review before approval";
  return null;
}

export function vehicleHoldBack(item: components["schemas"]["VehicleSetOut"]) {
  if (item.dispositions.quarantine > 0) return "Unknown model held back";
  if (item.dispositions.reject > 0) return "Rejected rows";
  return null;
}

/** RO13 (R11a): a Film set carries a Job Number, not a serial, so it is titled by what it does carry. */
export function vehicleTitle(item: components["schemas"]["VehicleSetOut"]) {
  if (!item.identity_complete) return "Identity incomplete";
  // D-RO17-17: same-day cars with no serial are told apart by car_label.
  return (
    item.serial_no ??
    item.car_label ??
    [item.model, item.color, item.measured_date].filter(Boolean).join(" · ")
  );
}

/** D-RO17-17: the car's label as its own line, when the title is not it already. */
export function carLine(item: { car_label?: string | null }, title: string) {
  return item.car_label && item.car_label !== title ? item.car_label : null;
}

export function retireNotice(outcomes: { message: string; error?: Error }[]) {
  const retired = outcomes.some((item) => item.message.includes("Retired"));
  const removed = outcomes.some((item) => item.message.includes("Removed"));
  const base =
    retired && removed
      ? "Removed from review and retired from active reads. Original records retained."
      : retired
        ? "Retired from active reads. Original records retained."
        : "Removed from review. Original records retained.";
  return `${base} Re-upload the same file to continue this batch.`;
}

export const SHEET_APPROVED_NOTICE = "Sheet approved.";

export const CLEAN_SHEET_READINESS = "No issues. You can approve this sheet.";

export type UploadPhase = "uploading" | "processing" | "ready" | "restored" | "error";

const FAILED_STATUSES = new Set(["FAILED"]);

export function uploadAcceptedNotice(sheets: { status: string }[], finished: boolean) {
  const restoredCurrent =
    sheets.length > 0 && sheets.every((sheet) => sheet.status === "COMMITTED");
  if (finished && restoredCurrent) {
    return "This file is current again. Open Measurement History to inspect the restored measurements.";
  }
  if (finished) {
    return "Upload processing finished. Open each workbook below to review.";
  }
  return "Upload accepted. Waiting for sheet processing; review opens when processing finishes.";
}

export function shouldAutoOpenReview(sheets: { status: string }[]) {
  return sheets.some((sheet) => sheet.status !== "COMMITTED");
}

export function isFailedUploadStatus(status: string) {
  return FAILED_STATUSES.has(status);
}

export function uploadPhase(input: {
  pending: boolean;
  hasError: boolean;
  acceptedCount: number;
  finished: boolean;
  failed: boolean;
  openReview: boolean;
}): UploadPhase | null {
  if (input.pending) return "uploading";
  if (input.hasError) return "error";
  if (input.acceptedCount === 0) return null;
  if (!input.finished) return "processing";
  if (input.failed) return "error";
  if (!input.openReview) return "restored";
  return "ready";
}

export function uploadProgressValue(phase: UploadPhase) {
  if (phase === "uploading") return 33;
  if (phase === "processing") return 66;
  return 100;
}

export function uploadProgressCopy(phase: UploadPhase, plant: string) {
  if (phase === "uploading") return `Uploading workbooks to ${plant}...`;
  if (phase === "processing") return "Processing sheets. Review opens when this finishes.";
  if (phase === "ready") return "Ready to review.";
  if (phase === "restored")
    return "This file is current again. Open Measurement History to inspect the restored measurements.";
  return "Upload did not finish.";
}

export function isInformationalIssue(issue: { level: string; token: string }) {
  return (
    issue.level === "INFORMATION" ||
    issue.token === "PLANT_FILLED" ||
    issue.token === "PROFILE_APPLIED"
  );
}

export function isActionableIssue(issue: { level: string; token: string }) {
  if (isInformationalIssue(issue)) return false;
  if (issue.token === "POSSIBLE_REPLACEMENT") return false;
  return issue.level === "BLOCKER" || issue.level === "WARNING";
}

export function issueGroupsToShow<T extends { level: string; token: string }>(issues: T[]) {
  return (["BLOCKER", "WARNING"] as const)
    .map((level) => ({
      level,
      items: issues.filter((issue) => issue.level === level && isActionableIssue(issue)),
    }))
    .filter((group) => group.items.length > 0);
}

export function informationalIssues<T extends { level: string; token: string }>(issues: T[]) {
  return issues.filter(isInformationalIssue);
}

export function howFileWasReadLabel(token: string) {
  if (token === "PLANT_FILLED") return "Plant cells filled in from the plant on the upload";
  if (token === "PROFILE_APPLIED") return "Template profile applied";
  return tokenHeadline(token);
}

export function readinessSummary(issues: { level: string; token: string }[]) {
  const groups = issueGroupsToShow(issues);
  if (!groups.length) return CLEAN_SHEET_READINESS;
  return groups.map((group) => `${group.items.length} ${group.level.toLowerCase()}`).join(" / ");
}

export function nextPendingSheet<T extends { batch: { load_id: number; status: string } }>(
  sheets: T[],
  currentLoadId: number,
  committedLoadIds: number[] = [],
) {
  const done = new Set([currentLoadId, ...committedLoadIds]);
  return sheets.find(
    (sheet) => sheet.batch.status === "PENDING_REVIEW" && !done.has(sheet.batch.load_id),
  );
}
