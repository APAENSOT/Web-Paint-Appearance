import type { components } from "../../api/types";
type Workbook = components["schemas"]["WorkbookOut"];
type Sheet = components["schemas"]["WorkbookSheetOut"];
const labels: Record<string, string> = {
  RUNNING: "Processing",
  PROCESSING: "Processing",
  PENDING_REVIEW: "Needs attention",
  REJECTED_TEMPLATE: "Needs attention",
  FAILED: "Needs attention",
  REVIEW_REQUIRED: "Needs attention",
  COMMITTED: "Approved",
  ACTIVE: "Approved",
  PARTIALLY_COMMITTED: "Partially approved",
  ABANDONED: "Removed from review",
  SUPERSEDED: "Retired from active reads",
  SKIPPED: "Skipped sheets kept as evidence",
};
export function friendlySheetStatus(sheet: Sheet) {
  if (sheet.batch.sheet_class === "OUT_OF_SCOPE_SHEET") return "Other tab kept as evidence";
  if (sheet.batch.sheet_class === "UNKNOWN_DATA_SHEET") return "Unknown data tab";
  return sheet.committable ? "Ready to approve" : (labels[sheet.batch.status] ?? "Needs attention");
}
export function friendlyStatus(workbook: Workbook) {
  const live = workbook.sheets.filter(
    (sheet) => !["ABANDONED", "SUPERSEDED"].includes(sheet.batch.status),
  );
  if (live.length && live.every((sheet) => sheet.batch.sheet_class === "OUT_OF_SCOPE_SHEET"))
    return "Other tabs kept as evidence";
  if (live.length && live.every((sheet) => sheet.committable)) return "Ready to approve";
  return labels[workbook.operational_summary] ?? "Needs attention";
}
