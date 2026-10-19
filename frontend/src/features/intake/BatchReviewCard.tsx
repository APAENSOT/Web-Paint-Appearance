import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { api, batchOptions } from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { MappingReview } from "./MappingReview";
import { BatchSupersede } from "./BatchSupersede";

export function BatchReviewCard({
  id,
  accepted,
  canMutate,
}: {
  id: number;
  accepted?: components["schemas"]["UploadedSheet"];
  canMutate: boolean;
}) {
  const review = useQuery(batchOptions(id));
  // Keep the confirmed POST outcome even if the subsequent review read fails.
  const [retirement, setRetirement] = useState<components["schemas"]["SupersedeResult"]>();
  const approving = useIsMutating({ mutationKey: ["mapping-approve", id] }) > 0;
  const client = useQueryClient();
  const commit = useMutation({
    mutationFn: () => api().commit(id),
    retry: false,
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["measurements"] }),
        client.invalidateQueries({ queryKey: ["batches"] }),
        client.invalidateQueries({ queryKey: ["batch", id] }),
      ]);
    },
    onError: () => {
      void client.invalidateQueries({ queryKey: ["batch", id] });
    },
  });
  const data = review.data;
  const batch = data?.batch;
  const ready =
    !review.isError &&
    !review.isFetching &&
    data?.committable === true &&
    batch?.counts.balanced === true &&
    batch.status === "PENDING_REVIEW";
  return (
    <article aria-label={`Batch ${id}`} className="panel overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border bg-muted/20 px-5 py-4">
        <div className="min-w-0">
          <h3 className="break-words text-lg font-semibold">
            {batch?.source_file ?? accepted?.filename ?? `Batch ${id}`}
          </h3>
          <p className="mt-1 break-words text-sm text-muted-foreground">
            Sheet: {batch?.source_sheet ?? accepted?.sheet ?? "Loading..."} | Batch {id}
            {batch?.plant_code ? ` | ${batch.plant_code}` : ""}
          </p>
          {accepted && (
            <p className="mt-2 text-xs text-muted-foreground">
              Accepted as {accepted.status}. {accepted.detail}
            </p>
          )}
        </div>
        {batch && (
          <span
            className="num rounded-sm border border-border bg-muted/30 px-2 py-1 text-xs"
            role="status"
            aria-label="Batch status"
          >
            {retirement?.status ?? batch.status}
          </span>
        )}
      </div>
      {retirement && (
        <p role="status" className="border-b border-border bg-muted/20 px-5 py-4 text-sm">
          Superseded. {retirement.measurements_hidden} measurements left active reads. Original
          records retained.
        </p>
      )}
      {review.isPending ? (
        <LoadingState>Loading sheet review...</LoadingState>
      ) : review.isError ? (
        <ApiErrorState error={review.error} retry={() => void review.refetch()} />
      ) : (
        batch &&
        data && (
          <div className="p-5">
            <dl className="panel-sunken grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 xl:grid-cols-6">
              {(
                [
                  ["Rows in file", batch.counts.rows_in_file],
                  ["To load", batch.counts.rows_loaded],
                  ["Duplicate", batch.counts.rows_duplicate],
                  ["Rejected", batch.counts.rows_rejected],
                  ["Quarantine", batch.counts.rows_quarantine],
                  ["Balanced", batch.counts.balanced ? "Yes" : "No"],
                ] as const
              ).map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="num mt-1 text-lg">{value}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-5 space-y-2 border-t border-border pt-4 text-sm">
              <p>
                Unidentified rows: <span className="num">{data.unidentified_rows}</span> | Staged
                rows: <span className="num">{data.staged_rows}</span>
              </p>
              <p>Committable: {data.committable ? "Yes" : "No"}</p>
              <p>Worker: {batch.job?.status ?? "No job recorded"}</p>
              {batch.job?.last_error && (
                <p role="alert" className="break-words">
                  Worker error: {batch.job.last_error}
                </p>
              )}
              {Object.keys(data.reject_reasons).length > 0 ? (
                <div>
                  <h4 className="font-medium">Reject reasons</h4>
                  <ul className="mt-1 space-y-1">
                    {Object.entries(data.reject_reasons).map(([reason, count]) => (
                      <li key={reason} className="break-words">
                        {reason}: <span className="num">{count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-muted-foreground">No reject reasons recorded.</p>
              )}
              {batch.status === "RUNNING" &&
                batch.job?.status !== "FAILED" &&
                batch.job?.status !== "DONE" && (
                  <p role="status" className="text-muted-foreground">
                    Processing sheet. This review updates automatically while open.
                  </p>
                )}
              {!data.committable &&
                batch.status !== "RUNNING" &&
                batch.status !== "COMMITTED" &&
                batch.status !== "SUPERSEDED" && (
                  <p className="text-muted-foreground">
                    This sheet cannot be committed. Review the mapping proposals and recorded issues
                    below.
                  </p>
                )}
            </div>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              {canMutate && batch.status !== "COMMITTED" && batch.status !== "SUPERSEDED" && (
                <Button
                  disabled={!ready || approving || commit.isPending || commit.isSuccess}
                  onClick={() => commit.mutate()}
                >
                  {commit.isPending ? "Committing..." : "Commit sheet"}
                </Button>
              )}
              <Button
                variant="outline"
                disabled={review.isFetching}
                onClick={() => void review.refetch()}
              >
                Refresh sheet
              </Button>
              {batch.status === "COMMITTED" && batch.plant_code && (
                <Link
                  to="/plant/$code"
                  params={{ code: batch.plant_code }}
                  className="text-sm font-medium text-primary underline underline-offset-4"
                >
                  View {batch.plant_code} measurements
                </Link>
              )}
            </div>
            {commit.isSuccess && !retirement && batch.status === "COMMITTED" && (
              <p role="status" className="mt-4 text-sm">
                Committed. {commit.data.measurements_inserted} measurements inserted.
              </p>
            )}
            {batch.status === "SUPERSEDED" && (
              <p className="mt-4 text-sm text-muted-foreground">
                This batch has left active reads. Original records are retained.
                {batch.superseded_by != null ? ` Replacement batch: ${batch.superseded_by}.` : ""}
              </p>
            )}
            {!retirement && (
              <BatchSupersede
                batch={batch}
                refreshing={review.isFetching}
                onSuperseded={setRetirement}
              />
            )}
            <MappingReview id={id} status={batch.status} />
          </div>
        )
      )}
      {commit.isError && <ApiErrorState error={commit.error} />}
    </article>
  );
}
