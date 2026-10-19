import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, batchesOptions, meOptions } from "@/api/queries";
import { mayIngest } from "@/api/roles";
import { AccessDenied } from "@/features/shell/AccessDenied";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { BatchReviewCard } from "./BatchReviewCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function ReviewQueue() {
  const identity = useQuery(meOptions);
  const canMutate = !identity.isError && mayIngest(identity.data?.principal);
  if (identity.isPending) return <LoadingState>Loading session...</LoadingState>;
  if (identity.isError)
    return <ApiErrorState error={identity.error} retry={() => void identity.refetch()} />;
  if (!canMutate) return <AccessDenied requiredRole="Engineer" />;
  return (
    <section className="mx-auto max-w-[1440px] space-y-3">
      <div className="panel border-t-2 border-t-primary px-5 py-4">
        <p className="eyebrow mb-2">WaveScan / Upload and review</p>
        <h1 className="text-lg font-semibold tracking-tight">Data intake</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Review each sheet before adding its measurements to the plant Data table.
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          Newest-first queue across plants. For rows isolated to one plant, open that plant's Data
          page.
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span>{identity.data.principal.display_name}</span>
          {identity.data.principal.auth_source === "dev-bypass" && (
            <span className="rounded-sm border border-border px-2">Dev bypass</span>
          )}
        </div>
      </div>
      <BatchQueue canMutate={canMutate} />
    </section>
  );
}

function BatchQueue({ canMutate }: { canMutate: boolean }) {
  const [offset, setOffset] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [pickerKey, setPickerKey] = useState(0);
  const [accepted, setAccepted] = useState<components["schemas"]["UploadedSheet"][]>([]);
  const client = useQueryClient();
  const batches = useQuery(batchesOptions(offset));
  const upload = useMutation({
    mutationFn: (): ReturnType<ReturnType<typeof api>["upload"]> =>
      Promise.reject(new Error("Open plant Files to upload with the route plant.")),
    retry: false,
    onSuccess: (result) => {
      setAccepted((previous) => [...result.batches, ...previous]);
      setFiles([]);
      setPickerKey((key) => key + 1);
      setOffset(0);
    },
    // A multi-file request can fail after earlier files were accepted. Reload persisted batches.
    onSettled: () => client.invalidateQueries({ queryKey: ["batches"] }),
  });
  const acceptedIds = new Set(accepted.map((sheet) => sheet.load_id));
  return (
    <>
      {canMutate && (
        <form
          className="panel p-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (files.length && !upload.isPending) upload.mutate();
          }}
        >
          <label htmlFor="workbooks" className="block font-semibold">
            Workbooks
          </label>
          <p id="workbooks-help" className="mt-1 text-sm text-muted-foreground">
            Choose one or more .xlsx, .xlsm or .ods files. Each sheet has its own review and commit.
          </p>
          <div className="mt-4 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
            <Input
              key={pickerKey}
              id="workbooks"
              type="file"
              accept=".xlsx,.xlsm,.ods"
              multiple
              aria-describedby="workbooks-help"
              disabled={upload.isPending}
              className="h-auto min-w-0 flex-1 cursor-pointer py-2"
              onChange={(event) => {
                setFiles(Array.from(event.target.files ?? []));
                upload.reset();
              }}
            />
            <Button type="submit" disabled={!files.length || upload.isPending}>
              {upload.isPending ? "Uploading..." : "Upload workbooks"}
            </Button>
          </div>
          {files.length > 0 && (
            <p className="mt-3 text-xs text-muted-foreground">{files.length} file(s) selected</p>
          )}
        </form>
      )}
      {upload.isError && (
        <div className="panel mt-4">
          <ApiErrorState error={upload.error} />
        </div>
      )}
      {accepted.length > 0 && (
        <section aria-label="Accepted sheets" className="mt-6 space-y-4">
          <h2 className="text-lg font-semibold">Accepted sheets</h2>
          <p className="text-sm text-muted-foreground">
            Upload accepted. Wait for processing, then review and commit each sheet.
          </p>
          {accepted.map((sheet) => (
            <BatchReviewCard
              key={sheet.load_id}
              id={sheet.load_id}
              accepted={sheet}
              canMutate={canMutate}
            />
          ))}
        </section>
      )}
      <section aria-label="Persisted batches" className="mt-6 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Batch history</h2>
          <Button
            variant="outline"
            disabled={batches.isFetching}
            onClick={() => void batches.refetch()}
          >
            Refresh batches
          </Button>
        </div>
        {batches.isPending ? (
          <LoadingState>Loading batches...</LoadingState>
        ) : batches.isError ? (
          <div className="panel">
            <ApiErrorState error={batches.error} retry={() => void batches.refetch()} />
          </div>
        ) : (
          <>
            {batches.data.items.length === 0 && (
              <p className="panel p-6 text-sm text-muted-foreground">
                No batches on this page. Upload a workbook to start a review.
              </p>
            )}
            {batches.data.items
              .filter((batch) => !acceptedIds.has(batch.load_id))
              .map((batch) => (
                <BatchReviewCard key={batch.load_id} id={batch.load_id} canMutate={canMutate} />
              ))}
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
              <p className="text-muted-foreground">
                {batches.data.page.returned} batches | {batches.data.page.total} total | offset{" "}
                {batches.data.page.offset}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  disabled={offset === 0 || batches.isFetching}
                  onClick={() => setOffset(Math.max(0, offset - 10))}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  disabled={
                    batches.isFetching ||
                    offset + batches.data.page.returned >= batches.data.page.total
                  }
                  onClick={() => setOffset(offset + 10)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </section>
    </>
  );
}
