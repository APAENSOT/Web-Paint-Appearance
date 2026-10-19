import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/api/client";
import { duplicateUploadCopy, errorDetail, errorHeadline } from "../src/api/error-copy";
import { workbookFixture } from "./workbook-fixtures";
import { cleanReview } from "./fixtures";
import type { components } from "../src/api/types";
import {
  aggregateRowsExcluded,
  blockerSentence,
  CLEAN_SHEET_READINESS,
  howFileWasReadLabel,
  inboxWarning,
  informationalIssues,
  issueGroupsToShow,
  needsUnknownModelAction,
  needsTemplateMapping,
  isFailedUploadStatus,
  nextPendingSheet,
  primaryBlockerSentences,
  profilePublishAvailable,
  readinessSummary,
  retireNotice,
  SHEET_APPROVED_NOTICE,
  shouldAutoOpenReview,
  sheetClassNotice,
  showsFillMissingPlant,
  uploadAcceptedNotice,
  uploadPhase,
  uploadProgressCopy,
  uploadProgressValue,
} from "../src/features/measurements/review-copy";

test("duplicate 409 copy names the retired load and asks an Admin to restore", () => {
  const message = `"07. Jul'26 CF data AAT.xlsx" has already been ingested: its SHA-256 matches load_id 1088 (07. Jul'26 CF data AAT.xlsx [Sheet1], SUPERSEDED). Nothing was stored. A corrected re-send must be a different file; identical bytes are the same evidence.`;
  const friendly = duplicateUploadCopy(message);
  assert.match(friendly ?? "", /load 1088/);
  assert.match(friendly ?? "", /retired/);
  assert.match(friendly ?? "", /Ask an Admin/);
  assert.doesNotMatch(friendly ?? "", /not available in this slice/);
  assert.doesNotMatch(friendly ?? "", /SHA-256/);
  const error = new ApiError(409, {
    statusCode: 409,
    error: "Conflict",
    message,
    correlationId: "dup-hash",
  });
  assert.equal(errorHeadline(error), "Ask an Admin to restore this file");
  assert.equal(errorDetail(error), friendly);
});

test("engineer 409 on a retired hash uses the Admin-decision sentence", () => {
  const message = `"07. Jul'26 CF data AAT.xlsx" has already been ingested: its SHA-256 matches load_id 1088 (07. Jul'26 CF data AAT.xlsx [Sheet1], SUPERSEDED). Nothing was stored. At least one of those sheets was committed and then retired, and bringing committed measurements back into the active reads is an Admin decision. Ask an Admin to upload the file again or to restore the batch. Nothing was reopened, including any abandoned sibling sheet.`;
  assert.match(duplicateUploadCopy(message) ?? "", /Ask an Admin/);
  assert.equal(
    errorHeadline(
      new ApiError(409, { statusCode: 409, error: "Conflict", message, correlationId: "eng" }),
    ),
    "Ask an Admin to restore this file",
  );
});

test("abandoned 409 copy tells the uploader to send the same file again", () => {
  const message = `"06. Jun'26 CF data AAT.xlsx" has already been ingested: its SHA-256 matches load_id 1089 (06. Jun'26 CF data AAT.xlsx [Sheet1], ABANDONED). Nothing was stored. A corrected re-send must be a different file; identical bytes are the same evidence.`;
  const friendly = duplicateUploadCopy(message);
  assert.match(friendly ?? "", /1089/);
  assert.match(friendly ?? "", /reopen that sheet/);
  assert.equal(
    errorHeadline(
      new ApiError(409, { statusCode: 409, error: "Conflict", message, correlationId: "abn" }),
    ),
    "This file can be reopened",
  );
});

test("blocker sentences replace raw tokens; exact token stays available to the caller", () => {
  const sheet: components["schemas"]["WorkbookSheetOut"] = {
    ...workbookFixture.sheets[0],
    committable: false,
    commit_blockers: ["WARNINGS_UNACKNOWLEDGED"],
    required_acknowledgements: ["QUARANTINED_MODELS"],
    batch: {
      ...workbookFixture.sheets[0].batch,
      counts: { ...cleanReview.batch.counts, rows_quarantine: 2, rows_loaded: 0 },
    },
  };
  assert.match(blockerSentence("WARNINGS_UNACKNOWLEDGED", sheet), /existing model/);
  assert.equal(
    blockerSentence("UNBALANCED"),
    "Row counts do not add up. Upload a corrected workbook. Rows cannot be deleted here.",
  );
  assert.equal(needsUnknownModelAction(sheet), true);
  assert.equal(
    inboxWarning({ ...workbookFixture, counts: sheet.batch.counts, sheets: [sheet] }),
    "Unknown model held back",
  );
  assert.equal(
    retireNotice([{ message: "Retired from active reads" }]),
    "Retired from active reads. Original records retained. Re-upload the same file to continue this batch.",
  );
  assert.equal(
    uploadAcceptedNotice([{ status: "COMMITTED" }], true),
    "This file is current again. Open Measurement History to inspect the restored measurements.",
  );
  assert.equal(shouldAutoOpenReview([{ status: "COMMITTED" }]), false);
  assert.equal(shouldAutoOpenReview([{ status: "PENDING_REVIEW" }]), true);
});

test("clean-layer blockers explain action without treating other tabs as broken templates", () => {
  assert.equal(
    blockerSentence("UNREVIEWED_HEADER"),
    "Extra columns have no agreed meaning. Map them, or have a named plant/quality owner mark them ignored with a reason. Nothing is ignored automatically.",
  );
  assert.equal(
    blockerSentence("DUPLICATE_LOGICAL_FIELD"),
    "Two columns mean the same field. This sheet was not read. Upload a corrected workbook.",
  );
  assert.equal(
    blockerSentence("OUT_OF_SCOPE_SHEET"),
    "This tab is not WaveScan. It is kept as evidence and is not a broken template.",
  );
  assert.equal(
    blockerSentence("UNKNOWN_DATA_SHEET"),
    "This tab looks like data but is not a WaveScan sheet. It is blocked for classification.",
  );
  assert.equal(
    blockerSentence("AGGREGATE_ONLY_SHEET"),
    "This sheet only contains report roll-up rows. Those rows are not vehicles.",
  );
  assert.equal(
    blockerSentence("PAINTLINE_MISSING"),
    "Paintline is missing. A corrected export is required; do not type a line here.",
  );
  assert.equal(
    blockerSentence("UNVERIFIED_PROFILE"),
    "This layout is readable but not fixture-verified. A named owner must publish a proving workbook.",
  );
});

test("sheet class, extra headers and aggregate evidence drive honest review actions", () => {
  const waveScan: components["schemas"]["WorkbookSheetOut"] = {
    ...workbookFixture.sheets[0],
    committable: false,
    commit_blockers: ["UNREVIEWED_HEADER", "UNVERIFIED_PROFILE"],
    batch: {
      ...workbookFixture.sheets[0].batch,
      domain: "WAVESCAN",
      semantic_signature: "c".repeat(64),
      sheet_class: "WAVESCAN",
      unreviewed_headers: ["Panel2"],
      notes: "The Plant column is missing from this export.",
    },
  };
  assert.equal(profilePublishAvailable(waveScan), true);
  assert.equal(showsFillMissingPlant(waveScan), true);
  assert.equal(
    aggregateRowsExcluded({
      ...cleanReview,
      batch: waveScan.batch,
      review_dispositions: { LOAD: 2, AGGREGATE_ROW: 3 },
    }),
    3,
  );
  assert.equal(sheetClassNotice(waveScan), null);

  const outOfScope = {
    ...waveScan,
    commit_blockers: ["NOT_PENDING_REVIEW", "OUT_OF_SCOPE_SHEET", "UNKNOWN_TEMPLATE"],
    batch: { ...waveScan.batch, sheet_class: "OUT_OF_SCOPE_SHEET" },
  };
  assert.equal(profilePublishAvailable(outOfScope), false);
  assert.deepEqual(primaryBlockerSentences(outOfScope), []);
  assert.equal(
    sheetClassNotice(outOfScope),
    "This tab is not WaveScan. It is kept as evidence and is not a broken template.",
  );
  assert.equal(
    inboxWarning({ ...workbookFixture, sheets: [outOfScope] }),
    "Other tabs kept as evidence",
  );

  const unknown = {
    ...waveScan,
    commit_blockers: ["UNKNOWN_TEMPLATE", "UNKNOWN_DATA_SHEET", "NOT_PENDING_REVIEW"],
    batch: { ...waveScan.batch, sheet_class: "UNKNOWN_DATA_SHEET" },
  };
  assert.equal(profilePublishAvailable(unknown), false);
  assert.deepEqual(primaryBlockerSentences(unknown), []);
  assert.equal(
    sheetClassNotice(unknown),
    "This tab looks like data but is not a WaveScan sheet. It is blocked for classification.",
  );

  assert.deepEqual(
    primaryBlockerSentences({
      ...waveScan,
      commit_blockers: ["UNKNOWN_TEMPLATE", "UNREVIEWED_HEADER"],
    }),
    [
      "This workbook layout is not an approved template.",
      "Extra columns have no agreed meaning. Map them, or have a named plant/quality owner mark them ignored with a reason. Nothing is ignored automatically.",
    ],
  );
});

test("upload phase copy and progress stay step-based", () => {
  assert.equal(isFailedUploadStatus("REJECTED_TEMPLATE"), false);
  assert.equal(shouldAutoOpenReview([{ status: "REJECTED_TEMPLATE" }]), true);
  assert.equal(
    needsTemplateMapping({
      ...workbookFixture.sheets[0],
      batch: {
        ...workbookFixture.sheets[0].batch,
        status: "REJECTED_TEMPLATE",
        sheet_class: "WAVESCAN",
      },
      committable: false,
      commit_blockers: ["UNKNOWN_TEMPLATE"],
    }),
    true,
  );
  assert.equal(
    uploadPhase({
      pending: true,
      hasError: false,
      acceptedCount: 0,
      finished: false,
      failed: false,
      openReview: true,
    }),
    "uploading",
  );
  assert.equal(
    uploadPhase({
      pending: false,
      hasError: false,
      acceptedCount: 1,
      finished: false,
      failed: false,
      openReview: true,
    }),
    "processing",
  );
  assert.equal(
    uploadPhase({
      pending: false,
      hasError: false,
      acceptedCount: 1,
      finished: true,
      failed: false,
      openReview: true,
    }),
    "ready",
  );
  assert.equal(
    uploadPhase({
      pending: false,
      hasError: false,
      acceptedCount: 1,
      finished: true,
      failed: false,
      openReview: false,
    }),
    "restored",
  );
  assert.equal(
    uploadPhase({
      pending: false,
      hasError: true,
      acceptedCount: 0,
      finished: false,
      failed: false,
      openReview: false,
    }),
    "error",
  );
  assert.equal(uploadProgressValue("uploading"), 33);
  assert.equal(uploadProgressValue("processing"), 66);
  assert.equal(uploadProgressValue("ready"), 100);
  assert.match(uploadProgressCopy("uploading", "FTM"), /Uploading workbooks to FTM/);
  assert.match(uploadProgressCopy("processing", "FTM"), /Processing sheets/);
});

test("issue groups hide empty levels and information tokens", () => {
  const issues = [
    { level: "INFORMATION", token: "PLANT_FILLED" },
    { level: "INFORMATION", token: "PROFILE_APPLIED" },
    { level: "WARNING", token: "POSSIBLE_REPLACEMENT" },
    { level: "WARNING", token: "REJECTED_ROWS" },
  ];
  const groups = issueGroupsToShow(issues);
  assert.deepEqual(
    groups.map((group) => group.level),
    ["WARNING"],
  );
  assert.deepEqual(
    groups[0].items.map((issue) => issue.token),
    ["REJECTED_ROWS"],
  );
  assert.equal(readinessSummary(issues), "1 warning");
  assert.equal(readinessSummary(issues.slice(0, 3)), CLEAN_SHEET_READINESS);
  assert.equal(informationalIssues(issues).length, 2);
  assert.match(howFileWasReadLabel("PLANT_FILLED"), /Plant cells filled/);
});

test("next pending sheet skips the sheet just approved", () => {
  const sheets = [
    { batch: { load_id: 123, status: "PENDING_REVIEW" as const } },
    { batch: { load_id: 124, status: "PENDING_REVIEW" as const } },
  ];
  assert.equal(nextPendingSheet(sheets, 123)?.batch.load_id, 124);
  assert.equal(nextPendingSheet(sheets, 124, [123]), undefined);
  assert.equal(SHEET_APPROVED_NOTICE, "Sheet approved.");
});
