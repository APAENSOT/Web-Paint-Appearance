import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { ComparisonIdentity } from "./ComparisonIdentity";
import { ComparisonDetail, ReadingSource } from "./ComparisonDetail";
import { vehicleLabel } from "./comparison-state";
import type { ComparisonSession } from "./useComparisonVehicles";
export function ComparisonMatrix({ session }: { session: ComparisonSession }) {
  const { state: s, dispatch: d, points: q } = session;
  const data = q.data;
  if (!s.selected.length) return null;
  return (
    <section className="panel cv-section" aria-label="Vehicle measurement matrix">
      <div className="cv-heading">
        <div>
          <p className="eyebrow">Catalogue locations</p>
          <h2>{s.metric} · raw readings</h2>
        </div>
        <div className="cv-pagination">
          <span className="num">
            {s.columnPage * 8 + 1}–{Math.min(s.columnPage * 8 + 8, s.selected.length)} of{" "}
            {s.selected.length}
          </span>
          <button
            className="cv-button"
            disabled={s.columnPage === 0}
            onClick={() => d({ type: "page", page: s.columnPage - 1 })}
          >
            Previous columns
          </button>
          <button
            className="cv-button"
            disabled={(s.columnPage + 1) * 8 >= s.selected.length}
            onClick={() => d({ type: "page", page: s.columnPage + 1 })}
          >
            Next columns
          </button>
        </div>
      </div>
      {q.isPending ? (
        <LoadingState>Loading raw readings...</LoadingState>
      ) : q.isError ? (
        <ApiErrorState error={q.error} retry={() => void q.refetch()} />
      ) : (
        data && (
          <>
            <p className="cv-muted mb-3">
              Open a location to inspect every reading and its source. Scroll horizontally for more
              vehicles.
            </p>
            <div
              className="cv-matrix-scroll"
              tabIndex={0}
              aria-label="Scrollable measurement columns"
            >
              <table aria-label="Raw vehicle measurements" className="cv-matrix">
                <thead>
                  <tr>
                    <th>Location / code</th>
                    {data.columns.map((v, i) => (
                      <th key={v.vehicle_id}>
                        <span className="eyebrow">Vehicle {s.columnPage * 8 + i + 1}</span>
                        <ComparisonIdentity vehicle={v} compact />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.locations.map((row) => (
                    <tr key={row.code}>
                      <th scope="row">
                        <button
                          className="cv-location"
                          onClick={() => d({ type: "focus", code: row.code })}
                        >
                          {row.point_no}. {row.code}
                        </button>
                        <span className="cv-muted block">
                          Orientation: {row.orientation ?? "unproved"}
                        </span>
                      </th>
                      {row.cells.map((cell, i) => (
                        <td data-testid={`cell-${row.point_no}-${i}`} key={cell.vehicle_id}>
                          {cell.missing ? (
                            <span className="cv-muted">Not measured</span>
                          ) : (
                            cell.readings.map((r, j) => (
                              <span className="num cv-cell-reading" key={j}>
                                {r.value}
                              </span>
                            ))
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!!data.unaligned_locations.length && (
              <section className="cv-unaligned" aria-label="Historical unaligned locations">
                <p className="eyebrow">Historical WaveScan rows</p>
                <h3>Not aligned to the current catalogue</h3>
                {data.unaligned_locations.map((row, i) => (
                  <div className="cv-reading" key={i}>
                    <strong>{row.checkzone}</strong>
                    <span className="cv-muted">
                      Vehicle{" "}
                      {s.columnPage * 8 +
                        data.columns.findIndex((v) => v.vehicle_id === row.vehicle_id) +
                        1}
                    </span>
                    <details className="cv-muted">
                      <summary>Vehicle identity</summary>
                      <code className="break-all">{row.vehicle_id}</code>
                    </details>
                    <span>
                      {vehicleLabel(data.columns.find((v) => v.vehicle_id === row.vehicle_id)!)} ·{" "}
                      <span className="num">{row.reading.value}</span>
                    </span>
                    <ReadingSource reading={row.reading} />
                  </div>
                ))}
              </section>
            )}
            <ComparisonDetail
              columnStart={s.columnPage * 8}
              data={data}
              code={s.focused}
              onClose={() => d({ type: "focus", code: null })}
            />
          </>
        )
      )}
    </section>
  );
}
