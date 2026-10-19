import assert from "node:assert/strict";
import { test } from "node:test";
import { friendlyStatus, friendlySheetStatus } from "../src/features/measurements/friendly-status";
import { workbookFixture } from "./workbook-fixtures";
import type { components } from "../src/api/types";
test("friendly workflow labels reflect API summaries with readiness and never grade", () => {
  const labels: Record<components["schemas"]["WorkbookOut"]["operational_summary"], string> = {
    PROCESSING: "Processing",
    REVIEW_REQUIRED: "Needs attention",
    ACTIVE: "Approved",
    PARTIALLY_COMMITTED: "Partially approved",
    ABANDONED: "Removed from review",
    SUPERSEDED: "Retired from active reads",
    SKIPPED: "Skipped sheets kept as evidence",
  };
  for (const [summary, label] of Object.entries(labels))
    assert.equal(
      friendlyStatus({
        ...workbookFixture,
        operational_summary: summary as keyof typeof labels,
        sheets: [{ ...workbookFixture.sheets[0], committable: false }],
      }),
      label,
    );
  assert.equal(friendlyStatus(workbookFixture), "Ready to approve");
  assert.equal(friendlySheetStatus(workbookFixture.sheets[0]), "Ready to approve");
  for (const status of ["PENDING_REVIEW", "REJECTED_TEMPLATE", "FAILED"] as const)
    assert.equal(
      friendlySheetStatus({
        ...workbookFixture.sheets[0],
        committable: false,
        batch: { ...workbookFixture.sheets[0].batch, status },
      }),
      "Needs attention",
    );

  const otherTab = {
    ...workbookFixture.sheets[0],
    committable: false,
    batch: {
      ...workbookFixture.sheets[0].batch,
      status: "REJECTED_TEMPLATE" as const,
      sheet_class: "OUT_OF_SCOPE_SHEET",
    },
  };
  assert.equal(friendlySheetStatus(otherTab), "Other tab kept as evidence");
  assert.equal(
    friendlyStatus({
      ...workbookFixture,
      operational_summary: "REVIEW_REQUIRED",
      sheets: [otherTab],
    }),
    "Other tabs kept as evidence",
  );
});
