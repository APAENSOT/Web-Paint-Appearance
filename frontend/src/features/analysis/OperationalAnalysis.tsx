import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { metaOptions, previewOptions } from "../../api/queries";
import type { PreviewQuery } from "../../api/client";
import { buildPreviewQuery } from "../../api/preview-query";
import { Button } from "../../components/ui/button";
import { ApiErrorState, LoadingState } from "../../components/ApiState";
import { PreviewChart } from "./PreviewChart";
import { PreviewTable } from "./PreviewTable";
import { GradingUnavailable, TruncationNotice } from "./PreviewNotices";

const fieldClass =
  "mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring";

export function OperationalAnalysis() {
  const metadata = useQuery(metaOptions);
  const [draft, setDraft] = useState<PreviewQuery>({ dimension: "checkzone" });
  const [query, setQuery] = useState<PreviewQuery>({ dimension: "checkzone" });
  const [validation, setValidation] = useState("");
  const preview = useQuery(previewOptions(query));
  const filters = [
    { key: "plant", label: "Plant", options: metadata.data?.plants.map((p) => p.plant_code) },
    { key: "model", label: "Model", options: metadata.data?.models.map((m) => m.model_code) },
    { key: "color", label: "Colour", options: metadata.data?.colors.map((c) => c.color_name) },
    { key: "checkzone", label: "Zone", options: metadata.data?.checkzones.map((z) => z.zone_code) },
  ] as const;
  const data = preview.data;
  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Analysis</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Compare recorded CF across plants, models, colours and zones.
        </p>
      </header>
      {metadata.isError && (
        <ApiErrorState error={metadata.error} retry={() => void metadata.refetch()} />
      )}
      <form
        className="panel p-5"
        onSubmit={(event) => {
          event.preventDefault();
          try {
            const next = buildPreviewQuery(draft);
            setValidation("");
            setQuery(next);
          } catch (error) {
            setValidation(error instanceof Error ? error.message : "Check the date range.");
          }
        }}
      >
        <h2 className="text-lg font-semibold">Filters</h2>
        {metadata.isPending && <LoadingState>Loading filter options...</LoadingState>}
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {filters.map(({ key, label, options }) => (
            <label key={key} className="text-sm">
              {label}
              {options?.length ? (
                <select
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
                    name={key}
                    className={fieldClass}
                    placeholder="All (leave blank)"
                    value={draft[key] ?? ""}
                    onChange={(event) =>
                      setDraft((previous) => ({ ...previous, [key]: event.target.value }))
                    }
                  />
                  <span className="mt-1 block text-xs text-muted-foreground">
                    Enter an exact {label.toLowerCase()} {key === "color" ? "name" : "code"} if
                    options are unavailable.
                  </span>
                </>
              )}
            </label>
          ))}
          <label className="text-sm">
            From date
            <input
              name="date_from"
              value={draft.date_from ?? ""}
              onChange={(event) =>
                setDraft((previous) => ({ ...previous, date_from: event.target.value }))
              }
              type="date"
              min="2000-01-01"
              max="2100-12-31"
              className={fieldClass}
            />
          </label>
          <label className="text-sm">
            To date
            <input
              name="date_to"
              value={draft.date_to ?? ""}
              onChange={(event) =>
                setDraft((previous) => ({ ...previous, date_to: event.target.value }))
              }
              type="date"
              min="2000-01-01"
              max="2100-12-31"
              className={fieldClass}
            />
          </label>
          <div className="sm:col-span-2">
            <label className="text-sm">
              Display grouping
              <select
                name="dimension"
                value={draft.dimension}
                onChange={(event) =>
                  setDraft((previous) => ({
                    ...previous,
                    dimension: event.target.value === "color" ? "color" : "checkzone",
                  }))
                }
                className={fieldClass}
                aria-describedby="dimension-help"
              >
                <option value="checkzone">Zone</option>
                <option value="color">Colour</option>
              </select>
            </label>
            <p id="dimension-help" className="mt-1 text-xs text-muted-foreground">
              Display grouping only, not a grading key.
            </p>
          </div>
        </div>
        {validation && (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {validation}
          </p>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button type="submit">Apply filters</Button>
          <p className="text-xs text-muted-foreground">Results reflect the last applied filters.</p>
        </div>
      </form>
      {preview.isFetching ? (
        <LoadingState>Loading raw CF measurements...</LoadingState>
      ) : preview.isError ? (
        <ApiErrorState error={preview.error} retry={() => void preview.refetch()} />
      ) : data ? (
        <>
          <TruncationNotice {...data} />
          {data.series.some((s) => s.points.length > 0) ? (
            <>
              <PreviewChart series={data.series} />
              <PreviewTable key={JSON.stringify(query)} series={data.series} />
            </>
          ) : (
            <div className="panel p-8">
              <h2 className="text-lg font-semibold">No measurements match these filters.</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Try another plant, clear a filter or widen the date range.
              </p>
            </div>
          )}
        </>
      ) : (
        <LoadingState>Loading raw CF measurements...</LoadingState>
      )}
      <GradingUnavailable
        grading_note={!preview.isFetching && !preview.isError ? data?.grading_note : undefined}
      />
    </section>
  );
}
