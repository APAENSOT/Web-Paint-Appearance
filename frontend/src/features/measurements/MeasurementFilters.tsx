import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { metaOptions } from "@/api/queries";
import { buildMeasurementQuery, type MeasurementListFilters } from "@/api/measurement-query";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";

const fieldClass =
  "mt-1 h-9 min-w-0 w-full rounded-[var(--radius-sm)] border border-border bg-[var(--surface-2)] px-3 text-xs focus-visible:outline-2 focus-visible:outline-ring";

export function MeasurementFilters({
  code,
  initialFilters = {},
  onApply,
}: {
  code: string;
  initialFilters?: MeasurementListFilters;
  onApply: (filters: MeasurementListFilters) => void;
}) {
  const metadata = useQuery(metaOptions);
  const [draft, setDraft] = useState<MeasurementListFilters>(initialFilters);
  const [validation, setValidation] = useState("");
  const fields = [
    { key: "model", label: "Model", options: metadata.data?.models.map((m) => m.model_code) },
    { key: "color", label: "Colour", options: metadata.data?.colors.map((c) => c.color_name) },
    { key: "checkzone", label: "Zone", options: metadata.data?.checkzones.map((z) => z.zone_code) },
  ] as const;
  return (
    <div>
      {metadata.isError && (
        <div className="panel mb-4">
          <ApiErrorState error={metadata.error} retry={() => void metadata.refetch()} />
        </div>
      )}
      <form
        className="panel px-5 py-4"
        onSubmit={(event) => {
          event.preventDefault();
          try {
            const {
              plant: _plant,
              limit: _limit,
              offset: _offset,
              ...filters
            } = buildMeasurementQuery(code, 0, draft);
            setValidation("");
            onApply(filters);
          } catch (error) {
            setValidation(error instanceof Error ? error.message : "Check the date range.");
          }
        }}
      >
        <h2 className="text-base font-semibold tracking-tight">Filters</h2>
        {metadata.isPending && <LoadingState>Loading filter options…</LoadingState>}
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {fields.map(({ key, label, options }) => (
            <div key={key}>
              <label
                htmlFor={`measurement-filter-${key}`}
                className="text-xs text-muted-foreground"
              >
                {label}
              </label>
              {options?.length ? (
                <select
                  id={`measurement-filter-${key}`}
                  name={key}
                  className={fieldClass}
                  value={draft[key] ?? ""}
                  onChange={(event) =>
                    setDraft((previous) => ({ ...previous, [key]: event.target.value }))
                  }
                >
                  <option value="">All</option>
                  {draft[key] && !options.includes(draft[key]) && (
                    <option value={draft[key]}>{draft[key]}</option>
                  )}
                  {[...new Set(options)].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              ) : (
                <>
                  <input
                    id={`measurement-filter-${key}`}
                    name={key}
                    className={fieldClass}
                    value={draft[key] ?? ""}
                    onChange={(event) =>
                      setDraft((previous) => ({ ...previous, [key]: event.target.value }))
                    }
                    placeholder="All (leave blank)"
                    aria-describedby={`measurement-help-${key}`}
                  />
                  <p id={`measurement-help-${key}`} className="mt-1 text-xs text-muted-foreground">
                    Enter an exact {label.toLowerCase()} {key === "color" ? "name" : "code"} if
                    options are unavailable.
                  </p>
                </>
              )}
            </div>
          ))}
          <label className="text-xs text-muted-foreground">
            From date
            <input
              name="date_from"
              type="date"
              min="2000-01-01"
              max="2100-12-31"
              className={fieldClass}
              value={draft.date_from ?? ""}
              onChange={(event) =>
                setDraft((previous) => ({ ...previous, date_from: event.target.value }))
              }
            />
          </label>
          <label className="text-xs text-muted-foreground">
            To date
            <input
              name="date_to"
              type="date"
              min="2000-01-01"
              max="2100-12-31"
              className={fieldClass}
              value={draft.date_to ?? ""}
              onChange={(event) =>
                setDraft((previous) => ({ ...previous, date_to: event.target.value }))
              }
            />
          </label>
        </div>
        {validation && (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {validation}
          </p>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button type="submit" size="sm">
            Apply filters
          </Button>
          <p className="text-xs text-muted-foreground">
            Results reflect the last applied filters for {code}.
          </p>
        </div>
      </form>
    </div>
  );
}
