import type { Candidate } from "./comparison-state";
import { vehicleLabel } from "./comparison-state";
export function ComparisonIdentity({
  vehicle: v,
  compact = false,
}: {
  vehicle: Candidate;
  compact?: boolean;
}) {
  return (
    <div className="cv-identity">
      <strong title={v.vehicle_id}>{vehicleLabel(v)}</strong>
      <span>
        {v.measured_date} · {v.measured_date.slice(0, 7)}-W{v.week}
      </span>
      <span>
        {v.model ?? "Model not recorded"} · {v.color ?? "Colour not recorded"}
      </span>
      {compact && (
        <span className="cv-muted">
          {v.domain === "WAVESCAN"
            ? `Load ${v.load_id ?? "unrecorded"}`
            : `Jobs: ${v.job_nos?.join(", ") ?? "unrecorded"}`}
        </span>
      )}
      {!compact && (
        <>
          <span>
            {v.point_count} / {v.expected_point_count ?? "Unproved"} points ·{" "}
            {v.incomplete ? "Incomplete set" : "Complete set"}
          </span>
          <span>{v.identity_complete ? "Identity complete" : "Identity incomplete"}</span>
          {v.job_nos?.length ? <span>Jobs: {v.job_nos.join(", ")}</span> : null}
          <span className="cv-muted">
            {v.domain === "WAVESCAN"
              ? `Load ${v.load_id ?? "unrecorded"} · ${v.source_file ?? "File unrecorded"} · ${v.source_sheet ?? "Sheet unrecorded"}`
              : `Loads ${v.load_ids?.join(", ") ?? "unrecorded"} · ${v.source_files?.join(", ") ?? "Files unrecorded"}`}
          </span>
        </>
      )}
    </div>
  );
}
