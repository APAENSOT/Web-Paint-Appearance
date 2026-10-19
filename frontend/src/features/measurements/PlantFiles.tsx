import { useCallback, useEffect, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, batchOptions, workbookInboxOptions, refreshPlantWorkbooks } from "@/api/queries";
import { ApiError } from "@/api/client";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { groupFiles } from "./file-buckets";
import { DataDomainFilter } from "./DataDomainFilter";
import { domainLabel, filterWorkbooks, workbookDomains, type DataDomain } from "./domain-tags";
import { FileCounts, FileRange, UploadedAt } from "./files-shared";
import { friendlySheetStatus, friendlyStatus } from "./friendly-status";
import { RemoveWorkbook } from "./RemoveWorkbook";
import { WorkbookDetail } from "./WorkbookDetail";
import { SkippedSheets } from "./WorkbookSections";
import { VehicleReviewDialog } from "./VehicleReviewDialog";
import { UploadProgressDialog } from "./UploadProgressDialog";
import { OdsQuickSummaryNotice } from "./OdsQuickSummaryNotice";
import { shouldAutoOpenReview, uploadAcceptedNotice, uploadPhase } from "./review-copy";
import {
  QUEUE_STATE_COPY,
  QUEUE_STATE_LABEL,
  newQueue,
  nextAttentionItem,
  queueRunning,
  queueSettled,
  resolvedQueueState,
  storedLoadId,
  type UploadQueueItem,
} from "./upload-queue";

export function PlantFiles({
  code,
  inactive,
  file,
  sheet,
  domain,
  onDomainChange,
  onOpen,
}: {
  code: string;
  inactive: boolean;
  file?: string;
  sheet?: number;
  domain: DataDomain;
  onDomainChange: (domain: DataDomain) => void;
  onOpen: (file?: string, sheet?: number) => void;
}) {
  const [notice, setNotice] = useState("");
  const [removing, setRemoving] = useState<components["schemas"]["WorkbookOut"]>();
  const [queue, setQueue] = useState<UploadQueueItem[]>([]);
  const [run, setRun] = useState(0);
  const [autoOpened, setAutoOpened] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const [lastFiles, setLastFiles] = useState<File[]>([]);
  const client = useQueryClient();
  const files = useQuery(workbookInboxOptions(code, "all"));
  const latestRemoving = files.data?.items.find((item) => item.file_hash === removing?.file_hash);
  const patch = useCallback(
    (id: number, next: Partial<UploadQueueItem>) =>
      setQueue((items) => items.map((item) => (item.id === id ? { ...item, ...next } : item))),
    [],
  );
  const polled = queue.flatMap((item) => item.sheets.map((entry) => ({ id: item.id, entry })));
  const batches = useQueries({ queries: polled.map((item) => batchOptions(item.entry.load_id)) });
  const accepted = polled.map((item) => item.entry);
  const single = queue.length === 1 ? queue[0] : undefined;
  const settled = queueSettled(queue);
  const running = queueRunning(queue);
  const upload = useMutation({
    mutationFn: (workbook: File) => api().upload({ files: [workbook], expected_plant: code }),
    retry: false,
  });
  const uploadOne = upload.mutateAsync;
  const duplicate = single?.state === "duplicate" ? storedLoadId(single.message ?? "") : undefined;
  const storedWorkbook = duplicate
    ? files.data?.items.find((item) =>
        item.sheets.some((entry) => entry.batch.load_id === duplicate),
      )
    : undefined;
  const phase = single
    ? uploadPhase({
        pending: single.state === "waiting" || single.state === "uploading",
        hasError: single.state === "duplicate" || single.state === "refused",
        acceptedCount: single.sheets.length,
        finished: single.state !== "processing",
        failed: single.state === "failed",
        openReview: shouldAutoOpenReview(single.sheets),
      })
    : null;
  const busy = phase === "uploading" || phase === "processing";
  const resetProgress = () => {
    setProgressOpen(false);
    setQueue([]);
    setLastFiles([]);
    setAutoOpened(false);
    upload.reset();
  };
  const startUpload = (selected: File[]) => {
    setNotice("");
    setAutoOpened(false);
    setLastFiles(selected);
    setProgressOpen(true);
    setQueue(newQueue(selected));
    setRun((value) => value + 1);
    upload.reset();
  };
  useEffect(() => {
    if (!run || !lastFiles.length) return;
    let current = true;
    const send = async () => {
      for (let index = 0; index < lastFiles.length; index += 1) {
        if (!current) return;
        patch(index, { state: "uploading" });
        try {
          const result = await uploadOne(lastFiles[index]);
          if (!current) return;
          patch(index, {
            state: result.batches.length ? "processing" : "ready",
            sheets: result.batches,
          });
        } catch (error) {
          if (!current) return;
          const failure = error instanceof Error ? error : new Error(String(error));
          const refusal = error instanceof ApiError ? error : undefined;
          patch(index, {
            state: refusal?.status === 409 ? "duplicate" : "refused",
            message: failure.message,
            correlationId: refusal?.body?.correlationId ?? undefined,
            storedLoadId: storedLoadId(failure.message),
            error: failure,
          });
        }
      }
      if (current) await refreshPlantWorkbooks(client, code);
    };
    void send();
    return () => {
      current = false;
    };
    // One run token drives the whole queue; depending on the queue itself would re-send files.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);
  useEffect(() => {
    for (const item of queue) {
      if (item.state !== "processing") continue;
      const own = polled
        .map((entry, index) => ({ id: entry.id, query: batches[index] }))
        .filter((entry) => entry.id === item.id);
      if (!own.length) continue;
      const finished = own.every(
        ({ query }) => query.isError || (query.data && query.data.batch.status !== "RUNNING"),
      );
      if (!finished) continue;
      patch(item.id, {
        state: resolvedQueueState({
          sheets: item.sheets,
          batchStatuses: own.map(({ query }) => query.data?.batch.status ?? ""),
          errored: own.every(({ query }) => query.isError),
        }),
        hash: own.find(({ query }) => query.data)?.query.data?.batch.file_hash,
      });
    }
  }, [queue, polled, batches, patch]);
  useEffect(() => {
    if (!settled || autoOpened) return;
    const next = nextAttentionItem(queue);
    const allReady = queue.every((item) => item.state === "ready");
    if (!next && !allReady) return;
    setAutoOpened(true);
    setProgressOpen(false);
    if (next) {
      patch(next.id, { opened: true });
      onOpen(next.hash);
    } else {
      setNotice(uploadAcceptedNotice(accepted, true));
    }
    void refreshPlantWorkbooks(client, code);
    // `accepted` is derived from the queue, which already gates this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled, autoOpened, queue, client, code, onOpen, patch]);
  const notOnboarded = inactive || files.data?.plant_is_active === false;
  const selectedWorkbook = files.data?.items.find((item) => item.file_hash === file);
  const nextAttention = settled && !file ? nextAttentionItem(queue) : undefined;
  return (
    <section aria-label="Upload Data" className="min-w-0 space-y-3">
      <div className="panel flex flex-wrap items-start justify-between gap-4 border-t-2 border-t-primary p-5">
        <div>
          <p className="eyebrow">{code} / Setting / Data</p>
          <h2 className="mt-1 text-xl font-semibold">Upload Data</h2>
          <p className="mt-2 text-xs text-muted-foreground">
            Attach one workbook or several, then check each file before loading. Every file is sent
            on its own, so a refused file does not stop the others. Open any uploaded workbook below
            to review it again.
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Film Thickness .ods files need usable Quick Summary data in the workbook. Other tabs are
            retained as evidence and do not create Film measurements.
          </p>
        </div>
        <div className="flex max-w-full flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            className="min-h-11"
            disabled={files.isFetching}
            onClick={() => void refreshPlantWorkbooks(client, code)}
          >
            Refresh uploads
          </Button>
          <label className="max-w-full text-xs font-semibold">
            Attach workbook
            <input
              aria-label="Attach workbook"
              aria-describedby="plant-workbook-formats"
              type="file"
              multiple
              accept=".xlsx,.xlsm,.ods"
              disabled={notOnboarded || !files.isSuccess || running}
              className="mt-2 block min-h-11 w-full max-w-[260px] text-xs file:mr-2 file:min-h-11 file:rounded-sm file:border file:border-border file:bg-background file:px-3 file:py-2"
              onChange={(event) => {
                const selected = Array.from(event.currentTarget.files ?? []);
                if (selected.length) startUpload(selected);
                event.currentTarget.value = "";
              }}
            />
            <span
              id="plant-workbook-formats"
              className="mt-1 block text-xs font-normal text-muted-foreground"
            >
              Accepted formats: .xlsx, .xlsm, .ods
            </span>
          </label>
        </div>
      </div>
      {queue.length > 1 && (
        <UploadQueue
          items={queue}
          workbooks={files.data?.items ?? []}
          nextAttention={queue.some((item) => item.opened) ? nextAttention : undefined}
          onOpenAttention={(item) => {
            patch(item.id, { opened: true });
            onOpen(item.hash);
          }}
          onOpenStored={onOpen}
        />
      )}
      {notOnboarded && (
        <p className="panel p-4 text-sm">
          {code} is not onboarded. Workbooks remain visible; uploads are unavailable.
        </p>
      )}
      {notice && (
        <p role="status" className="panel p-4 text-sm">
          {notice}
        </p>
      )}
      {phase && (
        <UploadProgressDialog
          open={progressOpen && !file && phase !== "ready" && phase !== "restored"}
          plant={code}
          phase={phase}
          error={single?.error}
          sheets={accepted.map((item, index) => ({
            filename: item.filename,
            sheet: item.sheet,
            status: batches[index]?.data?.batch.status ?? item.status,
          }))}
          busy={busy}
          canRetry={phase === "error" && lastFiles.length > 0}
          onOpenStored={
            storedWorkbook
              ? () => {
                  resetProgress();
                  onOpen(storedWorkbook.file_hash);
                }
              : undefined
          }
          onClose={resetProgress}
          onRetry={() => startUpload(lastFiles)}
        />
      )}
      {files.isPending ? (
        <LoadingState>Loading workbooks...</LoadingState>
      ) : files.isError && !files.data ? (
        <ApiErrorState error={files.error} retry={() => void files.refetch()} />
      ) : (
        files.data && (
          <>
            {files.isError && (
              <ApiErrorState error={files.error} retry={() => void files.refetch()} />
            )}
            {!file && (
              <>
                <div className="panel p-4">
                  <DataDomainFilter value={domain} onChange={onDomainChange} />
                </div>
                <InboxCards
                  items={filterWorkbooks(files.data.items, domain)}
                  domain={domain}
                  code={code}
                  busy={files.isError || files.isFetching}
                  onOpen={onOpen}
                  onRemove={setRemoving}
                />
              </>
            )}
          </>
        )
      )}
      {removing && (
        <RemoveWorkbook
          key={removing.file_hash}
          code={code}
          workbook={latestRemoving ?? removing}
          disabled={!latestRemoving || files.isFetching || files.isError}
          initialOpen
          hideTrigger
          onNotice={setNotice}
          onClosed={() => setRemoving(undefined)}
        />
      )}
      {file && selectedWorkbook?.operational_summary === "SKIPPED" ? (
        <WorkbookDetail code={code} hash={file} onBack={() => onOpen()} />
      ) : (
        file && (
          <VehicleReviewDialog
            key={file}
            code={code}
            hash={file}
            sheetId={sheet}
            onSheet={(id) => onOpen(file, id)}
            onClose={() => onOpen()}
            onApproved={setNotice}
          />
        )
      )}
    </section>
  );
}

function UploadQueue({
  items,
  workbooks,
  nextAttention,
  onOpenAttention,
  onOpenStored,
}: {
  items: UploadQueueItem[];
  workbooks: components["schemas"]["WorkbookOut"][];
  nextAttention?: UploadQueueItem;
  onOpenAttention: (item: UploadQueueItem) => void;
  onOpenStored: (file?: string) => void;
}) {
  const stored = (item: UploadQueueItem) =>
    item.storedLoadId === undefined
      ? undefined
      : workbooks.find((workbook) =>
          workbook.sheets.some((sheet) => sheet.batch.load_id === item.storedLoadId),
        );
  return (
    <section aria-label="Chosen files" className="panel min-w-0 p-4">
      <h3 className="text-sm font-semibold">Chosen files ({items.length})</h3>
      <p className="mt-1 text-xs text-muted-foreground">
        Each file is sent on its own request, in order. Nothing is answered or loaded for you.
      </p>
      <ol className="mt-3 space-y-2">
        {items.map((item, index) => (
          <li key={item.id} className="min-w-0 rounded-sm border border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 break-all text-xs font-semibold">
                {index + 1}. {item.filename}
              </span>
              <span className="rounded-sm border border-border bg-[var(--surface-2)] px-2 py-1 text-[10px] font-semibold">
                {QUEUE_STATE_LABEL[item.state]}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{QUEUE_STATE_COPY[item.state]}</p>
            {item.message && <p className="mt-1 break-words text-xs">{item.message}</p>}
            {item.correlationId && (
              <p className="mt-1 break-all text-[11px] text-muted-foreground">
                Correlation id {item.correlationId}
              </p>
            )}
            {stored(item) && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-2 min-h-11"
                onClick={() => onOpenStored(stored(item)?.file_hash)}
              >
                Open the stored workbook
              </Button>
            )}
          </li>
        ))}
      </ol>
      {nextAttention && (
        <Button
          type="button"
          className="mt-3 min-h-11"
          onClick={() => onOpenAttention(nextAttention)}
        >
          Next file needing attention
        </Button>
      )}
    </section>
  );
}

function InboxCards({
  items,
  domain,
  code,
  busy,
  onOpen,
  onRemove,
}: {
  items: components["schemas"]["WorkbookOut"][];
  domain: DataDomain;
  code: string;
  busy: boolean;
  onOpen: (file?: string, sheet?: number) => void;
  onRemove: (workbook: components["schemas"]["WorkbookOut"]) => void;
}) {
  const groups = groupFiles(items);
  if (!groups.length)
    return (
      <p className="panel p-5 text-sm text-muted-foreground">
        {domain === "both"
          ? "No uploaded workbooks yet."
          : `No ${domainLabel(domain)} workbooks for this filter.`}
      </p>
    );
  const now = new Date();
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return groups.map((group, index) => (
    <div key={`${group.month}-${group.week}`} className="space-y-3">
      {(index === 0 || groups[index - 1].month !== group.month) && (
        <h3 className="pt-3 text-lg font-semibold">{group.month}</h3>
      )}
      {group.month === currentMonth && (
        <p className="eyebrow">
          {group.week === 0 ? "Awaiting measured dates" : `Week ${group.week}`}
        </p>
      )}
      <div className="grid gap-3 xl:grid-cols-2">
        {group.files.map((workbook) => (
          <article key={workbook.file_hash} className="panel min-w-0 p-4">
            {workbookDomains(workbook).length > 0 && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {workbookDomains(workbook).map((item) => (
                  <span
                    key={item}
                    className="rounded-sm border border-border bg-[var(--surface-2)] px-2 py-1 text-[10px] font-semibold"
                  >
                    {domainLabel(item)}
                  </span>
                ))}
              </div>
            )}
            <div className="flex items-start justify-between gap-2">
              <button
                type="button"
                onClick={() => onOpen(workbook.file_hash)}
                className="min-h-11 min-w-0 text-left font-semibold hover:text-primary"
              >
                <span className="break-all">{workbook.source_file}</span>
                <span className="mt-2 block text-xs font-medium">
                  {workbook.operational_summary === "SKIPPED"
                    ? "Skipped sheets kept as evidence"
                    : friendlyStatus(workbook)}
                </span>
              </button>
              <RemoveWorkbook code={code} workbook={workbook} onSelect={onRemove} disabled={busy} />
            </div>
            <OdsQuickSummaryNotice workbook={workbook} className="mt-3" />
            <button
              type="button"
              aria-label={`Review ${workbook.source_file}`}
              onClick={() => onOpen(workbook.file_hash)}
              className="mt-3 min-h-11 min-w-0 w-full max-w-full space-y-3 text-left"
            >
              <FileRange workbook={workbook} />
              {workbook.measured_dates_span_months && (
                <p className="text-xs font-semibold">Measurements span calendar months.</p>
              )}
              <FileCounts counts={workbook.counts} />
              <p className="text-xs">
                {workbook.sheet_count} sheets / {workbook.vehicle_set_count} vehicle sets
              </p>
              <div className="flex flex-wrap gap-2">
                {workbook.sheets.map((item) => (
                  <span
                    key={item.batch.load_id}
                    data-sheet-chip="true"
                    title={item.batch.source_sheet}
                    className="min-w-0 max-w-full break-all rounded-sm border border-border px-2 py-1 text-[10px]"
                  >
                    {item.batch.source_sheet}: {friendlySheetStatus(item)}
                  </span>
                ))}
              </div>
              <p className="break-all text-[11px] text-muted-foreground">
                <UploadedAt uploadedAt={workbook.uploaded_at} />
              </p>
            </button>
            <div className="mt-3 min-w-0">
              <SkippedSheets workbook={workbook} />
            </div>
          </article>
        ))}
      </div>
    </div>
  ));
}
