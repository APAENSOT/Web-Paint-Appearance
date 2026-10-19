import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, meOptions, proposalsOptions, refreshAfterApproval } from "@/api/queries";
import { mayIngest, mayApproveMapping } from "@/api/roles";
import {
  columnPayload,
  modelAliasPayload,
  isApplicable,
  proposalKindLabel,
  isDiagnostic,
  isPlaceholder,
  STAGED_FIELDS,
} from "@/api/mapping-state";
import type { components } from "@/api/types";
import type { ProposalBody } from "@/api/client";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Proposal = components["schemas"]["ProposalOut"];
const selectClass =
  "mt-1 h-10 w-full min-w-0 rounded-sm border border-input bg-background px-3 text-sm";

export function MappingReview({ id, status }: { id: number; status: string }) {
  const identity = useQuery(meOptions);
  const canPropose = !identity.isError && mayIngest(identity.data?.principal);
  const canApprove = !identity.isError && mayApproveMapping(identity.data?.principal);
  const replayable = status === "REJECTED_TEMPLATE" || status === "PENDING_REVIEW";
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState<"COLUMN" | "ALIAS_MODEL">("COLUMN");
  const [raw, setRaw] = useState("");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const [validation, setValidation] = useState("");
  const client = useQueryClient();
  const proposals = useQuery(proposalsOptions(id, offset));
  const previousStatus = useRef(status);
  useEffect(() => {
    if (previousStatus.current === "RUNNING" && status !== "RUNNING") {
      // A failed replay creates a fresh diagnostic. Fetch it once, then stop.
      setOffset(0);
      void client.invalidateQueries({ queryKey: ["proposals", id] });
      void client.invalidateQueries({ queryKey: ["batches"] });
    }
    previousStatus.current = status;
  }, [status, client, id]);
  const propose = useMutation({
    mutationFn: (body: ProposalBody) => api().propose(body),
    retry: false,
    onSuccess: async () => {
      setOffset(0);
      setRaw("");
      setTarget("");
      setNote("");
      await client.invalidateQueries({ queryKey: ["proposals", id] });
    },
  });
  const approve = useMutation({
    mutationKey: ["mapping-approve", id],
    mutationFn: (proposalId: string) => api().approve(proposalId),
    retry: false,
    onSuccess: (result) => refreshAfterApproval(client, result),
    onError: () => {
      void client.invalidateQueries({ queryKey: ["batch", id] });
      void client.invalidateQueries({ queryKey: ["proposals", id] });
    },
  });
  const busy = propose.isPending || approve.isPending || status === "RUNNING";
  return (
    <section
      aria-label={`Mappings for batch ${id}`}
      className="mt-6 space-y-4 border-t border-border pt-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h4 className="font-semibold">Mapping review</h4>
        <Button
          variant="outline"
          disabled={proposals.isFetching || busy}
          onClick={() => void proposals.refetch()}
        >
          Refresh proposals
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        An Engineer proposes a spelling; an Admin approves it for future files and replays this
        sheet. Review the result before committing.
      </p>
      {proposals.isPending ? (
        <LoadingState>Loading proposals...</LoadingState>
      ) : proposals.isError ? (
        <ApiErrorState error={proposals.error} retry={() => void proposals.refetch()} />
      ) : (
        <>
          {proposals.data.items.length === 0 && (
            <p className="text-sm text-muted-foreground">No mapping proposals for this sheet.</p>
          )}
          <ul className="space-y-3">
            {proposals.data.items.map((proposal) => (
              <li
                key={proposal.id}
                className="min-w-0 space-y-3 rounded-sm border border-border p-4"
              >
                <div className="flex flex-wrap justify-between gap-2 text-sm font-medium">
                  <span>
                    {isDiagnostic(proposal)
                      ? "Header diagnostic"
                      : proposalKindLabel(proposal.kind)}
                  </span>
                  <span>{proposal.status}</span>
                </div>
                {isDiagnostic(proposal) ? (
                  <>
                    <p className="text-xs text-muted-foreground">
                      Recorded {proposal.created_at}. Current sheet status and counts are shown
                      above.
                    </p>
                    {proposal.payload.after_replay === true && (
                      <p className="text-sm font-medium">
                        After replay - headers still need review
                      </p>
                    )}
                    <p className="break-words text-sm">
                      Missing required:{" "}
                      {strings(proposal.payload.missing_required).join(", ") || "None listed"}
                    </p>
                    <div className="text-sm">
                      Unrecognised headers:
                      <ul className="mt-2 flex flex-wrap gap-2">
                        {strings(proposal.payload.unrecognised_headers).map((header, index) => (
                          <li key={`${header}-${index}`} className="min-w-0 max-w-full">
                            {canPropose && status === "REJECTED_TEMPLATE" ? (
                              <button
                                type="button"
                                className="max-w-full break-all rounded border border-border px-2 py-1 text-left text-primary underline underline-offset-4 disabled:opacity-50"
                                disabled={busy}
                                onClick={() => {
                                  setKind("COLUMN");
                                  setRaw(header);
                                  setTarget("");
                                  setValidation("");
                                  propose.reset();
                                }}
                              >
                                {header}
                              </button>
                            ) : (
                              <span className="break-all">{header}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      This is a header diff, not an applicable mapping. Create a new column proposal
                      using the file's header.
                    </p>
                  </>
                ) : (
                  <dl className="space-y-1 text-sm">
                    {Object.entries(proposal.payload).map(([key, value]) => (
                      <div key={key} className="break-words">
                        <dt className="inline text-muted-foreground">{key}: </dt>
                        <dd className="inline">
                          {typeof value === "string" ? value : JSON.stringify(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
                {proposal.similarity !== null && (
                  <p className="text-xs text-muted-foreground">
                    Similarity (advisory only): {proposal.similarity}
                  </p>
                )}
                <ProposalDetails proposal={proposal} />
                {canApprove && isApplicable(proposal) && (
                  <Button
                    disabled={!replayable || busy || proposals.isFetching || proposals.isError}
                    onClick={() => approve.mutate(proposal.id)}
                  >
                    {approve.isPending && approve.variables === proposal.id
                      ? "Approving..."
                      : "Approve & replay"}
                  </Button>
                )}
              </li>
            ))}
          </ul>
          {proposals.data.page.total > 10 && (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <Button
                variant="outline"
                disabled={offset === 0 || proposals.isFetching || busy}
                onClick={() => setOffset(Math.max(0, offset - 10))}
              >
                Previous proposals
              </Button>
              <span>
                {offset + 1}-{offset + proposals.data.page.returned} of {proposals.data.page.total}
              </span>
              <Button
                variant="outline"
                disabled={
                  offset + proposals.data.page.returned >= proposals.data.page.total ||
                  proposals.isFetching ||
                  busy
                }
                onClick={() => setOffset(offset + 10)}
              >
                Next proposals
              </Button>
            </div>
          )}
        </>
      )}
      {canPropose && replayable && (
        <form
          className="space-y-4 rounded-sm border border-border bg-muted/20 p-4"
          aria-label="New mapping proposal"
          onSubmit={(event) => {
            event.preventDefault();
            if (busy) return;
            const payload =
              kind === "COLUMN"
                ? { raw_header: raw, logical_field: target, ...(note ? { note } : {}) }
                : { raw_value: raw, model_code: target, ...(note ? { note } : {}) };
            const parsed = (kind === "COLUMN" ? columnPayload : modelAliasPayload).safeParse(
              payload,
            );
            if (!parsed.success) {
              setValidation(
                parsed.error.issues
                  .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
                  .join("; "),
              );
              return;
            }
            if (kind === "ALIAS_MODEL" && (isPlaceholder(raw) || !target.trim())) {
              setValidation(
                "Enter an actual model spelling and an existing model code. Placeholders remain quarantined.",
              );
              return;
            }
            setValidation("");
            propose.mutate({ kind, load_id: id, payload: parsed.data });
          }}
        >
          <h5 className="font-medium">New mapping proposal</h5>
          <label className="block text-sm">
            Mapping kind
            <select
              className={selectClass}
              value={kind}
              disabled={busy}
              onChange={(event) => {
                setKind(event.target.value as typeof kind);
                setRaw("");
                setTarget("");
                setValidation("");
                propose.reset();
              }}
            >
              <option value="COLUMN">Column header</option>
              <option value="ALIAS_MODEL">Model spelling</option>
            </select>
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block min-w-0 text-sm">
              {kind === "COLUMN" ? "Raw header" : "Raw model spelling"}
              <Input
                className="mt-1"
                required
                maxLength={200}
                value={raw}
                disabled={busy}
                onChange={(event) => {
                  setRaw(event.target.value);
                  propose.reset();
                }}
              />
            </label>
            {kind === "COLUMN" ? (
              <label className="block min-w-0 text-sm">
                Logical field
                <select
                  className={selectClass}
                  required
                  value={target}
                  disabled={busy}
                  onChange={(event) => setTarget(event.target.value)}
                >
                  <option value="">Choose a field</option>
                  {STAGED_FIELDS.map((field) => (
                    <option key={field} value={field}>
                      {field}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label className="block min-w-0 text-sm">
                Existing model code
                <Input
                  className="mt-1"
                  required
                  maxLength={64}
                  value={target}
                  disabled={busy}
                  onChange={(event) => setTarget(event.target.value)}
                />
              </label>
            )}
          </div>
          {kind === "ALIAS_MODEL" && (
            <p className="text-xs text-muted-foreground">
              Copy the spelling from the workbook. The code must already exist; proposing cannot
              create a model. Empty cells, (none), n/a and other placeholders remain quarantined and
              cannot be resolved by an alias.
            </p>
          )}
          <label className="block text-sm">
            Note (optional)
            <Input
              className="mt-1"
              maxLength={2000}
              value={note}
              disabled={busy}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
          {validation && (
            <p role="alert" className="break-words text-sm">
              {validation}
            </p>
          )}
          <Button type="submit" disabled={busy}>
            {propose.isPending ? "Proposing..." : "Propose mapping"}
          </Button>
        </form>
      )}
      {propose.isSuccess && (
        <p role="status" className="text-sm">
          Proposal recorded as PROPOSED. An Admin must approve before anything is applied.
        </p>
      )}
      {approve.isSuccess && (
        <p role="status" className="text-sm">
          Approved.{" "}
          {status === "RUNNING"
            ? "Replaying stored bytes; this review updates automatically."
            : "Replay review updated. Check the sheet's status and counts."}{" "}
          Commit remains a separate action.
        </p>
      )}
      {propose.isError && <ApiErrorState error={propose.error} />}
      {approve.isError && <ApiErrorState error={approve.error} />}
    </section>
  );
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function ProposalDetails({ proposal }: { proposal: Proposal }) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: ["proposal", proposal.id, proposal.status],
    queryFn: ({ signal }) => api().proposal(proposal.id, signal),
    enabled: open,
  });
  return (
    <details
      className="text-xs text-muted-foreground"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer">Proposal details</summary>
      {open &&
        (detail.isPending ? (
          <LoadingState>Loading proposal...</LoadingState>
        ) : detail.isError ? (
          <ApiErrorState error={detail.error} retry={() => void detail.refetch()} />
        ) : (
          <div className="mt-2 space-y-1 break-all">
            <p>ID: {detail.data.id}</p>
            <p>
              Proposed by: {detail.data.proposed_by ?? "Not recorded"} | {detail.data.created_at}
            </p>
            <p>
              Decided by: {detail.data.decided_by ?? "Not decided"} |{" "}
              {detail.data.decided_at ?? "-"}
            </p>
            <pre className="whitespace-pre-wrap break-all">
              {JSON.stringify(detail.data.payload, null, 2)}
            </pre>
          </div>
        ))}
    </details>
  );
}
