import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { attentionOptions } from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";

/** Ingest-queue attention only — not a WaveScan product grade. */
const ATTENTION_TONE: Record<string, string> = {
  RUNNING: "var(--signal)",
  PENDING_REVIEW: "var(--primary)",
  REJECTED_TEMPLATE: "var(--caution)",
  FAILED: "var(--critical)",
};

const stripChrome = {
  background: "linear-gradient(180deg, var(--primary-soft) 0%, var(--color-panel) 18%)",
  boxShadow: "inset 0 2px 0 var(--color-primary), var(--shadow-panel)",
} as const;

export function BatchAttention() {
  const batches = useQuery(attentionOptions);
  const attention =
    batches.data?.items.filter((batch) =>
      ["RUNNING", "PENDING_REVIEW", "REJECTED_TEMPLATE", "FAILED"].includes(batch.status),
    ) ?? [];
  return (
    <section
      aria-label="Batch attention"
      className="panel overflow-hidden animate-rise"
      style={stripChrome}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <h2 className="font-semibold">Batch attention</h2>
        <Button
          variant="ghost"
          size="sm"
          disabled={batches.isFetching}
          onClick={() => void batches.refetch()}
        >
          Refresh attention
        </Button>
      </div>
      {batches.isPending ? (
        <LoadingState>Loading recent batches…</LoadingState>
      ) : batches.isError ? (
        <ApiErrorState error={batches.error} retry={() => void batches.refetch()} />
      ) : (
        <>
          <p className="px-4 py-2.5 text-[10px] leading-relaxed text-muted-foreground">
            {batches.data.page.total > batches.data.items.length
              ? `Latest ${batches.data.items.length} of ${batches.data.page.total} batches, requested up to 50. This is a recent window; older batches may also need attention.`
              : "Recent batches checked for processing, review, template and worker issues."}
          </p>
          {attention.length === 0 ? (
            <p className="px-4 pb-4 text-sm">No batches need attention in this window.</p>
          ) : (
            <ul className="divide-y divide-border border-t border-border">
              {attention.map((batch) => {
                const tone = ATTENTION_TONE[batch.status] ?? "var(--color-border)";
                return (
                  <li
                    key={batch.load_id}
                    className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="break-words text-sm font-medium">{batch.source_file}</p>
                      <p className="mt-0.5 break-words text-[10px] text-muted-foreground">
                        {batch.source_sheet} · Batch {batch.load_id}
                        {batch.plant_code ? ` · ${batch.plant_code}` : ""}
                      </p>
                    </div>
                    <span
                      className="rounded-[var(--radius-sm)] border px-2 py-0.5 text-[10px] font-medium"
                      style={{
                        color: tone,
                        borderColor: tone,
                        backgroundColor: "var(--surface-2)",
                      }}
                    >
                      {batch.status}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
      <Link
        to="/batches"
        className="block border-t border-border px-4 py-2.5 text-sm font-medium text-primary hover:bg-secondary"
      >
        Open Data intake
      </Link>
    </section>
  );
}
