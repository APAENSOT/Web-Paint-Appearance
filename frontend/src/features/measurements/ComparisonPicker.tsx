import { ArrowLeft, ArrowRight } from "lucide-react";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { ComparisonIdentity } from "./ComparisonIdentity";
import type { ComparisonSession } from "./useComparisonVehicles";
export function ComparisonPicker({ session }: { session: ComparisonSession }) {
  const { state: s, dispatch: d, candidates: q, options, modelValid } = session;
  const data = q.data;
  return (
    <section className="panel cv-section" aria-label="Candidate vehicles">
      <div className="cv-heading">
        <div>
          <p className="eyebrow">Select vehicles</p>
          <h2>Measured vehicles</h2>
        </div>
        <label className="cv-search">
          <span className="sr-only">Search vehicle serial or job</span>
          <input
            className="cv-input"
            placeholder="Search serial or job"
            value={s.search}
            onChange={(e) => d({ type: "search", value: e.target.value })}
          />
        </label>
      </div>
      {options.isPending ? (
        <LoadingState>Loading candidate options...</LoadingState>
      ) : options.isError ? (
        <p className="cv-empty">Vehicle options could not be loaded. Use Retry in the filters.</p>
      ) : !options.data?.available_months.length ? (
        <p className="cv-empty">No data in this measurement domain.</p>
      ) : !s.model ? (
        <p className="cv-empty">Choose one vehicle model to browse measured vehicles.</p>
      ) : !modelValid ? (
        <p className="cv-empty">
          No matching candidates for this model in the measured months. Your selection is retained.
        </p>
      ) : q.isPending ? (
        <LoadingState>Loading candidate vehicles...</LoadingState>
      ) : q.isError ? (
        <ApiErrorState error={q.error} retry={() => void q.refetch()} />
      ) : (
        <>
          <div className="cv-candidates">
            {data?.items.map((v, i) => (
              <article className="cv-candidate" key={v.vehicle_id}>
                <ComparisonIdentity vehicle={v} />
                <button
                  className="cv-button"
                  aria-label={`Add vehicle ${s.offset + i + 1}`}
                  disabled={s.selected.some((selected) => selected.vehicle_id === v.vehicle_id)}
                  onClick={() => d({ type: "add", vehicle: v })}
                >
                  {s.selected.some((selected) => selected.vehicle_id === v.vehicle_id)
                    ? "Selected"
                    : "Add"}
                </button>
              </article>
            ))}
          </div>
          {!data?.items.length && (
            <p className="cv-empty">
              No matching candidates. Adjust the measured filters or search.
            </p>
          )}
          <div className="cv-pagination">
            <span className="num">
              {data?.page.total
                ? `${data.page.offset + 1}–${data.page.offset + data.page.returned} of ${data.page.total}`
                : "0 vehicles"}
            </span>
            <button
              className="cv-button"
              disabled={s.offset === 0}
              onClick={() => d({ type: "offset", offset: Math.max(0, s.offset - 50) })}
            >
              Previous candidates
            </button>
            <button
              className="cv-button"
              disabled={!data || data.page.offset + data.page.returned >= data.page.total}
              onClick={() => d({ type: "offset", offset: s.offset + 50 })}
            >
              Next candidates
            </button>
          </div>
        </>
      )}
    </section>
  );
}
export function ComparisonTray({ session }: { session: ComparisonSession }) {
  const { state: s, dispatch: d } = session;
  return (
    <section className="panel cv-section" aria-label="Selected vehicles">
      <div className="cv-heading">
        <div>
          <p className="eyebrow">Your chosen order</p>
          <h2>
            Selected vehicles <span className="num">({s.selected.length})</span>
          </h2>
        </div>
        <p className="cv-muted">
          {s.selected.length === 1
            ? "Single vehicle inspection"
            : "Select any number; inspect eight at a time."}
        </p>
      </div>
      {!s.selected.length ? (
        <p className="cv-empty">Add measured vehicles to inspect their raw readings.</p>
      ) : (
        <ol className="cv-tray">
          {s.selected.map((v, i) => (
            <li key={v.vehicle_id} data-vehicle={v.vehicle_id}>
              <span className="num cv-index">{i + 1}</span>
              <ComparisonIdentity vehicle={v} />
              <div className="cv-actions">
                <button
                  className="cv-button"
                  disabled={i === 0}
                  aria-label={`Move vehicle ${i + 1} left`}
                  onClick={() => d({ type: "move", index: i, direction: -1 })}
                >
                  <ArrowLeft size={14} />
                </button>
                <button
                  className="cv-button"
                  disabled={i === s.selected.length - 1}
                  aria-label={`Move vehicle ${i + 1} right`}
                  onClick={() => d({ type: "move", index: i, direction: 1 })}
                >
                  <ArrowRight size={14} />
                </button>
                <button
                  className="cv-button"
                  aria-label={`Remove vehicle ${i + 1}`}
                  onClick={() => d({ type: "remove", id: v.vehicle_id })}
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
