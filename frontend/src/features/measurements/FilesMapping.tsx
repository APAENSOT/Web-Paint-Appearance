import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ProposalBody } from "@/api/client";
import {
  columnPayload,
  isApplicable,
  proposalKindLabel,
  isDiagnostic,
  isPlaceholder,
  modelAliasPayload,
  STAGED_FIELDS,
} from "@/api/mapping-state";
import {
  api,
  meOptions,
  proposalsOptions,
  refreshAfterApproval,
  refreshPlantWorkbooks,
} from "@/api/queries";
import { mayManagePlantFiles } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Proposal = components["schemas"]["ProposalOut"];
type Kind = "COLUMN" | "ALIAS_MODEL";

const selectClass =
  "mt-1 h-9 w-full rounded-[var(--radius-sm)] border border-border bg-[var(--surface-2)] px-3 text-xs";

export function FilesMapping({
  id,
  status,
  plant,
  fileHash,
  defaultKind = "COLUMN",
  compact = false,
}: {
  id: number;
  status: string;
  plant: string;
  fileHash?: string;
  defaultKind?: Kind;
  compact?: boolean;
}) {
  const client = useQueryClient();
  const identity = useQuery(meOptions);
  const isAdmin = !identity.isError && mayManagePlantFiles(identity.data?.principal);
  const replayable = status === "REJECTED_TEMPLATE" || status === "PENDING_REVIEW";
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState<Kind>(defaultKind);
  const [raw, setRaw] = useState("");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const [validation, setValidation] = useState("");
  const proposals = useQuery(proposalsOptions(id, offset));
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
    mutationKey: ["files-mapping-approve", id],
    mutationFn: (proposalId: string) => api().approve(proposalId),
    retry: false,
    onSuccess: async (result) => {
      await refreshAfterApproval(client, result);
      await refreshPlantWorkbooks(client, plant);
      if (fileHash) await client.invalidateQueries({ queryKey: ["worksheet", plant, fileHash] });
    },
    onError: async () => {
      await client.invalidateQueries({ queryKey: ["proposals", id] });
      await refreshPlantWorkbooks(client, plant);
    },
  });
  const busy = propose.isPending || approve.isPending || status === "RUNNING";

  function submit() {
    const payload =
      kind === "COLUMN"
        ? { raw_header: raw, logical_field: target, ...(note ? { note } : {}) }
        : { raw_value: raw, model_code: target, ...(note ? { note } : {}) };
    const parsed = (kind === "COLUMN" ? columnPayload : modelAliasPayload).safeParse(payload);
    if (!parsed.success) {
      setValidation(
        parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; "),
      );
      return;
    }
    if (kind === "ALIAS_MODEL" && isPlaceholder(raw)) {
      setValidation("Placeholders remain quarantined and cannot be resolved by an alias.");
      return;
    }
    setValidation("");
    propose.mutate({ kind, load_id: id, payload: parsed.data });
  }

  return (
    <section
      aria-label={compact ? "Map unknown model spelling" : `Mappings for sheet ${id}`}
      className="panel space-y-4 p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
        <div>
          <p className="label">{compact ? "Unknown model" : "Sheet mapping"}</p>
          <h4 className="mt-1 font-semibold">
            {compact ? "Map this spelling" : "Column and model proposals"}
          </h4>
        </div>
        <Button
          variant="outline"
          disabled={busy || proposals.isFetching}
          onClick={() => proposals.refetch()}
        >
          Refresh
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {compact
          ? "Propose an alias to an existing model code. Do not invent a new model. Approval replays stored bytes; commit stays separate. To keep garbage rows out of History, hold them back below and approve the rest."
          : "Approval replays stored bytes. Review the updated sheet before committing. Commit remains a separate action."}
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
          <ul className="space-y-2">
            {proposals.data.items.map((proposal) => (
              <ProposalItem
                key={proposal.id}
                proposal={proposal}
                canApprove={isAdmin && replayable && !busy}
                approving={approve.isPending && approve.variables === proposal.id}
                onApprove={() => approve.mutate(proposal.id)}
              />
            ))}
          </ul>
          {proposals.data.page.total > 10 && (
            <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3 text-xs">
              <Button
                variant="outline"
                size="sm"
                disabled={offset === 0 || busy}
                onClick={() => setOffset(Math.max(0, offset - 10))}
              >
                Previous proposals
              </Button>
              <span>
                {offset + 1}-{offset + proposals.data.page.returned} of {proposals.data.page.total}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={
                  offset + proposals.data.page.returned >= proposals.data.page.total || busy
                }
                onClick={() => setOffset(offset + 10)}
              >
                Next proposals
              </Button>
            </div>
          )}
        </>
      )}

      {isAdmin && replayable && (
        <form
          className="space-y-3 border-t border-border pt-4"
          aria-label="New mapping proposal"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy) submit();
          }}
        >
          <h5 className="text-sm font-semibold">
            {compact ? "Map model" : "New mapping proposal"}
          </h5>
          {!compact && (
            <label className="block text-xs">
              Mapping kind
              <select
                className={selectClass}
                aria-label="Mapping kind"
                value={kind}
                disabled={busy}
                onChange={(event) => {
                  setKind(event.target.value as Kind);
                  setRaw("");
                  setTarget("");
                  setValidation("");
                }}
              >
                <option value="COLUMN">Column header</option>
                <option value="ALIAS_MODEL">Model spelling</option>
              </select>
            </label>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs">
              {kind === "COLUMN" ? "Raw header" : "Raw model spelling"}
              <Input
                className="mt-1"
                required
                maxLength={200}
                value={raw}
                disabled={busy}
                onChange={(event) => setRaw(event.target.value)}
              />
            </label>
            <label className="block text-xs">
              {kind === "COLUMN" ? "Logical field" : "Existing model code"}
              {kind === "COLUMN" ? (
                <select
                  className={selectClass}
                  required
                  aria-label="Logical field"
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
              ) : (
                <Input
                  className="mt-1"
                  required
                  maxLength={64}
                  aria-label="Existing model code"
                  value={target}
                  disabled={busy}
                  onChange={(event) => setTarget(event.target.value)}
                />
              )}
            </label>
          </div>
          <label className="block text-xs">
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
            <p role="alert" className="text-sm">
              {validation}
            </p>
          )}
          <Button type="submit" size="sm" disabled={busy}>
            {propose.isPending
              ? "Proposing..."
              : compact
                ? "Propose model mapping"
                : "Propose mapping"}
          </Button>
        </form>
      )}
      {propose.isSuccess && (
        <p role="status" className="text-xs">
          Proposal recorded. Approval and replay are separate from commit.
        </p>
      )}
      {approve.isSuccess && (
        <p role="status" className="text-xs">
          Approved and replay requested. Commit remains a separate action.
        </p>
      )}
      {propose.isError && <ApiErrorState error={propose.error} />}
      {approve.isError && <ApiErrorState error={approve.error} />}
    </section>
  );
}

function ProposalItem({
  proposal,
  canApprove,
  approving,
  onApprove,
}: {
  proposal: Proposal;
  canApprove: boolean;
  approving: boolean;
  onApprove: () => void;
}) {
  const diagnostic = isDiagnostic(proposal);
  return (
    <li className="space-y-2 border border-border bg-[var(--surface-2)] p-3 text-xs">
      <div className="flex flex-wrap justify-between gap-2 font-semibold">
        <span>{diagnostic ? "Header diagnostic" : proposalKindLabel(proposal.kind)}</span>
        <span>{proposal.status}</span>
      </div>
      {diagnostic ? (
        <div className="space-y-1">
          {proposal.payload.after_replay === true && (
            <p>After replay - headers still need review</p>
          )}
          <p>
            Missing required:{" "}
            {strings(proposal.payload.missing_required).join(", ") || "None listed"}
          </p>
          <p className="break-all">
            Unrecognised headers:{" "}
            {strings(proposal.payload.unrecognised_headers).join(", ") || "None listed"}
          </p>
          <p className="text-muted-foreground">
            Diagnostic evidence cannot be approved as a mapping.
          </p>
        </div>
      ) : (
        <dl className="space-y-1">
          {Object.entries(proposal.payload).map(([key, value]) => (
            <div key={key}>
              <dt className="inline text-muted-foreground">{key}: </dt>
              <dd className="inline break-all">
                {typeof value === "string" ? value : JSON.stringify(value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {proposal.similarity !== null && (
        <p className="text-muted-foreground">Similarity (advisory only): {proposal.similarity}</p>
      )}
      {canApprove && isApplicable(proposal) && (
        <Button size="sm" disabled={approving} onClick={onApprove}>
          {approving ? "Approving..." : "Approve & replay"}
        </Button>
      )}
    </li>
  );
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}
