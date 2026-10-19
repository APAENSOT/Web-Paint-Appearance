import type { components } from "@/api/types";
export function FileCounts({ counts }: { counts: components["schemas"]["BatchCountsOut"] }) {
  return (
    <dl className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
      {(
        [
          ["Source rows", counts.rows_in_file],
          ["Load", counts.rows_loaded],
          ["Duplicate", counts.rows_duplicate],
          ["Rejected", counts.rows_rejected],
          ["Quarantine", counts.rows_quarantine],
        ] as const
      ).map(([name, value]) => (
        <div key={name}>
          <dt className="text-muted-foreground">{name}</dt>
          <dd className="num mt-1 font-semibold">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
/** RO13 (F10): the viewer's local date and time. The API names the uploader only by id, so no name. */
export function UploadedAt({ uploadedAt }: { uploadedAt: string }) {
  return (
    <>
      Uploaded{" "}
      <time dateTime={uploadedAt}>
        {new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(
          new Date(uploadedAt),
        )}
      </time>
    </>
  );
}
export function FileRange({ workbook }: { workbook: components["schemas"]["WorkbookOut"] }) {
  return (
    <p className="text-xs text-muted-foreground">
      Measured: {workbook.measured_date_min ?? "Not available"}
      {workbook.measured_date_max ? ` to ${workbook.measured_date_max}` : ""}
    </p>
  );
}
