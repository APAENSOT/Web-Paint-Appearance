import type { components } from "@/api/types";
import { noUsableQuickSummary } from "./review-copy";

export function OdsQuickSummaryNotice({
  workbook,
  className = "",
}: {
  workbook: components["schemas"]["WorkbookOut"];
  className?: string;
}) {
  if (!noUsableQuickSummary(workbook)) return null;
  return (
    <aside
      role="status"
      className={`${className} rounded-sm border border-border border-l-4 border-l-primary bg-[var(--primary-soft)] p-3 text-sm`}
    >
      <p className="font-semibold">
        No usable Quick Summary data was found in this file. Its tabs were kept as evidence; no Film
        Thickness measurements can be approved from it.
      </p>
      <p className="mt-2">
        Find this retained workbook under Both in Upload Data after closing the review.
      </p>
    </aside>
  );
}
