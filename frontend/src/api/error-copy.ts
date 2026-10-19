import { ApiError } from "./client";

const BLOCKER_COPY: Record<string, string> = {
  WARNINGS_UNACKNOWLEDGED:
    "Some rows were not loaded. Acknowledge that those rows stay out of History, or map an unknown model spelling, then approve the rest.",
  UNBALANCED: "Row counts do not add up. Upload a corrected workbook. Rows cannot be deleted here.",
  QUARANTINED_MODELS:
    "Unknown model spelling is held back. Map it to an existing model, or hold those rows back and approve the rest.",
  NOT_PENDING_REVIEW: "This sheet is not waiting for approval.",
  UNKNOWN_TEMPLATE: "This workbook layout is not an approved template.",
  UNVERIFIED_PROFILE:
    "This layout is readable but not fixture-verified. A named owner must publish a proving workbook.",
  NO_REVIEW_PROJECTION: "Review evidence is not ready yet. Wait for processing.",
  VEHICLE_IDENTITY_MISSING:
    "Vehicle identity is missing. Mapping or a corrected workbook is required; do not type a serial here.",
  UNREVIEWED_HEADER:
    "Extra columns have no agreed meaning. Map them, or have a named plant/quality owner mark them ignored with a reason. Nothing is ignored automatically.",
  DUPLICATE_LOGICAL_FIELD:
    "Two columns mean the same field. This sheet was not read. Upload a corrected workbook.",
  OUT_OF_SCOPE_SHEET:
    "This tab is not WaveScan. It is kept as evidence and is not a broken template.",
  UNKNOWN_DATA_SHEET:
    "This tab looks like data but is not a WaveScan sheet. It is blocked for classification.",
  AGGREGATE_ONLY_SHEET:
    "This sheet only contains report roll-up rows. Those rows are not vehicles.",
  PAINTLINE_MISSING:
    "Paintline is missing. A corrected export is required; do not type a line here.",
};

const TOKEN_HEADLINES: Record<string, string> = {
  WARNINGS_UNACKNOWLEDGED: "Warnings still need acknowledgement",
  UNBALANCED: "Row counts do not add up",
  QUARANTINED_MODELS: "Unknown model held back",
  REJECTED_ROWS: "Rejected rows",
  DUPLICATE_ROWS: "Duplicate rows",
  POSSIBLE_REPLACEMENT: "Possible replacement (advisory)",
  NOT_PENDING_REVIEW: "Not waiting for approval",
  UNREVIEWED_HEADER: "Extra columns need a decision",
  DUPLICATE_LOGICAL_FIELD: "Duplicate field meaning",
  OUT_OF_SCOPE_SHEET: "Other tab kept as evidence",
  UNKNOWN_DATA_SHEET: "Unknown data tab",
  AGGREGATE_ONLY_SHEET: "Report roll-up rows only",
  PAINTLINE_MISSING: "Paintline missing",
  UNVERIFIED_PROFILE: "Layout needs owner verification",
};

const DUPLICATE_RE =
  /has already been ingested: its SHA-256 matches load_id (\d+) \((.+?) \[[^\]]+\], ([A-Z_]+)\)/;

export function tokenHeadline(token: string) {
  return TOKEN_HEADLINES[token] ?? token.replaceAll("_", " ").toLowerCase();
}

export function blockerCopy(token: string) {
  return BLOCKER_COPY[token] ?? `This sheet cannot be approved yet (${token}).`;
}

export function duplicateUploadCopy(message: string) {
  const match = message.match(DUPLICATE_RE);
  if (!match) return null;
  const [, loadId, file, status] = match;
  if (/filed under plant/.test(message) || /cannot reopen them/.test(message)) {
    return `This exact file is already stored as load ${loadId} (${file}) at another plant. Open that plant's Upload Data page. Identical bytes are not stored twice.`;
  }
  if (status === "SUPERSEDED" || /Admin decision/.test(message)) {
    return `This exact file is already stored as load ${loadId} (${file}; retired). Ask an Admin to restore it, or upload a changed workbook. Identical bytes are not stored twice.`;
  }
  if (status === "ABANDONED") {
    return `This exact file is already stored as load ${loadId} (${file}; removed from review). Upload the same file again to reopen that sheet. Identical bytes are not stored twice.`;
  }
  return `This exact file is already stored as load ${loadId} (${file}). Nothing was stored. A corrected send must be a different file.`;
}

export function errorHeadline(error: Error) {
  const message =
    error instanceof ApiError ? (error.body?.message ?? error.message) : error.message;
  const duplicate = duplicateUploadCopy(message);
  if (duplicate) {
    if (/Ask an Admin/.test(duplicate)) return "Ask an Admin to restore this file";
    if (/reopen that sheet/.test(duplicate)) return "This file can be reopened";
    if (/another plant/.test(duplicate)) return "This file belongs to another plant";
    return "This file is already stored";
  }
  if (TOKEN_HEADLINES[message]) return TOKEN_HEADLINES[message];
  return null;
}

export function errorDetail(error: Error) {
  const original =
    error instanceof ApiError ? (error.body?.message ?? error.message) : error.message;
  return duplicateUploadCopy(original) ?? BLOCKER_COPY[original] ?? original;
}
