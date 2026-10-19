import { Database, RefreshCw } from "lucide-react";
import type { components } from "@/api/types";
import { type MeasurementListFilters } from "@/api/measurement-query";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { MeasurementFilters } from "./MeasurementFilters";
import { MeasurementTable } from "./MeasurementTable";

type MeasurementPage = components["schemas"]["MeasurementPage"];

type MeasurementListQuery = {
  isPending: boolean;
  isFetching: boolean;
  isError: boolean;
  error: Error | null;
  data: MeasurementPage | undefined;
  refetch: () => void;
};

export function PlantDataPane({
  code,
  filters,
  canCorrect,
  filtered,
  offset,
  setOffset,
  notice,
  setNotice,
  measurements,
  onApplyFilters,
}: {
  code: string;
  filters: MeasurementListFilters;
  canCorrect: boolean;
  filtered: boolean;
  offset: number;
  setOffset: (next: number) => void;
  notice: string | Error;
  setNotice: (notice: string | Error) => void;
  measurements: MeasurementListQuery;
  onApplyFilters: (filters: MeasurementListFilters) => void;
}) {
  const data = measurements.data;
  return (
    <section aria-label="Plant data" className="min-w-0 space-y-3">
      <MeasurementFilters initialFilters={filters} code={code} onApply={onApplyFilters} />
      {notice &&
        (notice instanceof Error ? (
          <div className="panel">
            <ApiErrorState error={notice} />
          </div>
        ) : (
          <p role="status" className="panel p-4 text-sm">
            {notice}
          </p>
        ))}
      <div
        className="panel overflow-hidden"
        style={{ boxShadow: "inset 0 2px 0 var(--color-primary), var(--shadow-panel)" }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h2 className="flex items-center gap-2 font-semibold">
              <Database aria-hidden="true" className="size-4 text-muted-foreground" /> Raw WaveScan
              values
            </h2>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              Active measurements only. Values are shown as recorded; grading is unavailable.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-sm border border-border px-2 py-1 text-xs text-muted-foreground">
              {canCorrect ? "Corrections available" : "Read only"}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={measurements.isFetching}
              onClick={() => void measurements.refetch()}
            >
              <RefreshCw aria-hidden="true" className="size-4" />
              {measurements.isFetching ? "Refreshing…" : "Refresh"}
            </Button>
          </div>
        </div>
        {measurements.isPending || measurements.isFetching ? (
          <LoadingState>Loading measurements for {code}…</LoadingState>
        ) : measurements.isError ? (
          <ApiErrorState
            error={measurements.error ?? new Error("Request unsuccessful")}
            retry={() => void measurements.refetch()}
          />
        ) : (
          data && (
            <>
              {data.items.length === 0 ? (
                <div role="status" className="px-6 py-14 text-center">
                  <Database
                    aria-hidden="true"
                    className="mx-auto mb-4 size-7 text-muted-foreground"
                  />
                  <h3 className="text-lg font-semibold">
                    {data.page.total === 0
                      ? filtered
                        ? "No measurements match these filters"
                        : "No active measurements"
                      : "No measurements on this page"}
                  </h3>
                  <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
                    {data.page.total === 0
                      ? filtered
                        ? "Try clearing a filter or widening the date range for this plant."
                        : "The API returned no active rows for this plant. Measurements will appear here after a batch is committed. Refresh to check again."
                      : "The available rows may have changed. Return to the first page to continue."}
                  </p>
                  {offset > 0 && (
                    <Button className="mt-5" variant="outline" onClick={() => setOffset(0)}>
                      First page
                    </Button>
                  )}
                </div>
              ) : (
                <MeasurementTable rows={data.items} onNotice={setNotice} />
              )}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4">
                <p aria-live="polite" className="text-xs text-muted-foreground">
                  <span className="num text-foreground">{data.page.returned}</span> returned ·{" "}
                  <span className="num text-foreground">{data.page.total}</span> matching rows ·
                  offset <span className="num text-foreground">{data.page.offset}</span>
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={data.page.offset === 0 || measurements.isFetching}
                    onClick={() => setOffset(Math.max(0, data.page.offset - data.page.limit))}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={
                      data.page.offset + data.page.returned >= data.page.total ||
                      measurements.isFetching
                    }
                    onClick={() => setOffset(data.page.offset + data.page.limit)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          )
        )}
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        Expand a row for additional parameters and source details. Scroll the table horizontally on
        smaller screens.
      </p>
    </section>
  );
}
