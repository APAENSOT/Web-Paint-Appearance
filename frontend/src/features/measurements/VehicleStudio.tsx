import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { comparisonVehicleVisualsOptions } from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import type { components } from "@/api/types";
import type { ComparisonSession } from "./useComparisonVehicles";
import { BoxStage, ProfilePair } from "./StudioCharts";
import { vehicleLabel } from "./comparison-state";
import "./comparison-studio.css";
type Trace = components["schemas"]["ComparisonRawTrace"];
const parameters = ["du", "wa", "wb", "wc", "wd", "we"] as const;
function Source({ trace }: { trace: Trace }) {
  return (
    <dl className="studio-stats">
      {(
        [
          "measurement_id",
          "panel_label",
          "source_file",
          "source_sheet",
          "source_row",
          "load_id",
          "cf",
          ...parameters,
        ] as const
      ).map((k) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd className="num">
            {trace[k] ??
              (["cf", ...parameters].includes(k as (typeof parameters)[number])
                ? "Not measured"
                : "Not recorded")}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function VehicleStudio({ code, session }: { code: string; session: ComparisonSession }) {
  const [view, setView] = useState<"readings" | "cf" | "profiles">("readings");
  const [choice, setChoice] = useState("");
  const query = useQuery({
    ...comparisonVehicleVisualsOptions(code, {
      model: session.state.model ?? "",
      vehicle_id: session.visible.map((v) => v.vehicle_id),
    }),
    enabled:
      session.state.domain === "WAVESCAN" && session.visible.length > 0 && view !== "readings",
  });
  if (session.state.domain !== "WAVESCAN" || !session.visible.length) return null;
  const visual =
    query.data?.vehicles.find((v) => v.vehicle_id === choice) ?? query.data?.vehicles[0];
  const candidate = query.data?.columns.find((v) => v.vehicle_id === visual?.vehicle_id);
  const lines =
    visual?.locations.flatMap((l) =>
      l.traces.map((t) => ({
        id: `m${t.measurement_id}`,
        label: `${l.point_no}. ${l.code} / measurement ${t.measurement_id} / ${t.source_file ?? "File not recorded"} / row ${t.source_row ?? "Not recorded"}`,
        orientation: l.orientation,
        values: parameters.map((metric) => ({
          metric,
          value: t[metric],
          detail: (
            <>
              <p>
                {l.point_no}. {l.code} / {metric.toUpperCase()}:{" "}
                <strong className="num">{t[metric] ?? "Not measured"}</strong>
              </p>
              <Source trace={t} />
            </>
          ),
        })),
      })),
    ) ?? [];
  return (
    <section className="studio" aria-label="WaveScan vehicle visuals">
      <div className="studio-panel studio-toolbar">
        <strong>WaveScan / {session.state.model} views</strong>
        {(["readings", "cf", "profiles"] as const).map((v) => (
          <button
            key={v}
            className="cv-button"
            aria-pressed={view === v}
            onClick={() => setView(v)}
          >
            {v === "readings"
              ? "Exact readings"
              : v === "cf"
                ? "Vehicle CF distributions"
                : "Raw DU-WE profiles"}
          </button>
        ))}
      </div>
      {view !== "readings" && (
        <>
          {query.isPending && <LoadingState>Loading current vehicle page visuals...</LoadingState>}
          {query.isError && (
            <ApiErrorState error={query.error} retry={() => void query.refetch()} />
          )}
          {view === "cf" && query.data && (
            <BoxStage
              title={`${query.data.model} / Vehicle CF distributions`}
              entries={query.data.vehicles.flatMap((v) =>
                v.cf_boxes.map((b) => ({
                  key: `${v.vehicle_id}-${b.orientation}`,
                  caption: `${session.state.columnPage * 8 + query.data!.columns.findIndex((c) => c.vehicle_id === v.vehicle_id) + 1}. ${vehicleLabel(query.data!.columns.find((c) => c.vehicle_id === v.vehicle_id)!)}`,
                  label: `${query.data!.columns.findIndex((c) => c.vehicle_id === v.vehicle_id) + 1}. ${vehicleLabel(query.data!.columns.find((c) => c.vehicle_id === v.vehicle_id)!)} / ${query.data!.columns.find((c) => c.vehicle_id === v.vehicle_id)!.measured_date}`,
                  orientation: b.orientation,
                  n: b.n,
                  box: b.stats,
                })),
              )}
            />
          )}
          {view === "profiles" && query.data && (
            <section className="studio-item-profile" aria-label="Raw vehicle profile card">
              <label>
                One vehicle at a time
                <select
                  className="cv-input"
                  aria-label="Profile vehicle"
                  value={visual?.vehicle_id ?? ""}
                  onChange={(e) => setChoice(e.target.value)}
                >
                  {query.data.columns.map((c, i) => (
                    <option key={c.vehicle_id} value={c.vehicle_id}>
                      {i + 1}. {vehicleLabel(c)} / {c.measured_date} / load {c.load_id}
                    </option>
                  ))}
                </select>
              </label>
              <h2>
                {candidate && vehicleLabel(candidate)} / {candidate?.model} /{" "}
                {candidate?.color ?? "Colour not recorded"} / {candidate?.measured_date}
              </h2>
              <p className="cv-muted">
                Each line is one raw source measurement row. Duplicate locations retain distinct
                measurements.
              </p>
              <ProfilePair title="Raw DU-WE" lines={lines} />
              <details>
                <summary>
                  Catalogue locations without source rows (
                  {visual?.locations.filter((l) => !l.traces.length).length ?? 0})
                </summary>
                {visual?.locations
                  .filter((l) => !l.traces.length)
                  .map((l) => (
                    <p key={`${l.point_no}-${l.code}`}>
                      {l.point_no}. {l.code} / {l.orientation ?? "Unproved orientation"}: Not
                      measured
                    </p>
                  ))}
              </details>
              <details>
                <summary>
                  Historical unaligned raw rows ({visual?.unaligned_locations.length ?? 0})
                </summary>
                {visual?.unaligned_locations.map((l) => (
                  <section key={l.trace.measurement_id}>
                    <h3>{l.checkzone}</h3>
                    <Source trace={l.trace} />
                  </section>
                ))}
              </details>
            </section>
          )}
        </>
      )}
    </section>
  );
}
