import type { components } from "../src/api/types";
import { cleanReview } from "./fixtures";
export const fileHash = "a".repeat(64);
export const workbookFixture: components["schemas"]["WorkbookOut"] = {
  file_hash: fileHash,
  plant_code: "AAT",
  source_file: "review.xlsx",
  operational_summary: "REVIEW_REQUIRED",
  measured_date_min: "2026-06-07",
  measured_date_max: "2026-07-03",
  uploaded_at: "2026-09-16T08:00:00Z",
  loaded_by: "fixture-admin",
  counts: cleanReview.batch.counts,
  sheet_count: 1,
  skipped_sheet_count: 0,
  superseded: false,
  abandoned: false,
  vehicle_set_count: 1,
  measured_dates_span_months: true,
  sheets: [
    {
      batch: { ...cleanReview.batch, file_hash: fileHash, review_revision: "b".repeat(64) },
      committable: true,
      commit_blockers: [],
      required_acknowledgements: [],
      acknowledged: [],
    },
  ],
};
export const detailFixture: components["schemas"]["WorkbookDetailOut"] = {
  workbook: workbookFixture,
  profiles: [],
  possible_replacements: [],
  acknowledgements: [],
};
