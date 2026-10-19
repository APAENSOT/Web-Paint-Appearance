import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  workbookIssuesOptions,
  workbookRowsOptions,
  workbookHistoryOptions,
  refreshPlantWorkbooks,
  meOptions,
} from "@/api/queries";
import { isAdmin } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { ReasonPresets } from "./ReasonPresets";
import {
  ACK_NOTE_PRESETS,
  howFileWasReadLabel,
  informationalIssues,
  issueGroupsToShow,
  tokenHeadline,
} from "./review-copy";

type Issue = components["schemas"]["IssueOut"];
type Ack = components["schemas"]["AcknowledgementCreate"];
type Sheet = components["schemas"]["WorkbookSheetOut"];
export function SkippedSheets({ workbook }: { workbook: components["schemas"]["WorkbookOut"] }) {
  if (!workbook.skipped_sheet_count) return null;
  return (
    <details className="min-w-0 max-w-full text-xs">
      <summary className="cursor-pointer break-all font-semibold">
        Skipped sheets of {workbook.source_file} ({workbook.skipped_sheet_count})
      </summary>
      <ul className="mt-2 min-w-0 space-y-2">
        {(workbook.skipped_sheets ?? []).map((sheet, index) => (
          <li key={`${sheet.source_sheet}-${index}`} className="min-w-0 break-all">
            <span className="font-medium" title={sheet.source_sheet}>
              {sheet.source_sheet}
            </span>
            <p className="mt-1 break-words text-muted-foreground">{sheet.reason}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}
const resolutionCopy: Record<NonNullable<Issue["resolution"]>, string> = {
  mapping:
    "Review the mapping controls on Summary. Only approved column or model aliases replay stored bytes. Replay does not commit.",
  corrected_source:
    "Correct the source workbook and upload new bytes. Existing evidence is retained.",
  blocked_identity:
    "Vehicle identity or verified profile evidence is missing. This cannot be resolved by acknowledging a warning; owner onboarding is required.",
  acknowledge:
    "Review the affected rows, then acknowledge this category for the current review revision.",
  wait_for_worker: "Wait for the worker to finish, then review the updated result.",
  supersede_separate:
    "Possible replacement is advisory and does not block commit. Supersede is a separate Admin action with a reason on the committed sheet.",
};
function ackCategory(token: string): Ack["category"] | undefined {
  if (
    token === "REJECTED_ROWS" ||
    token === "QUARANTINED_MODELS" ||
    token === "DUPLICATE_ROWS" ||
    token === "POSSIBLE_REPLACEMENT"
  )
    return token;
}
export function WorkbookIssues({
  code,
  hash,
  sheets,
}: {
  code: string;
  hash: string;
  sheets: Sheet[];
}) {
  const issues = useQuery(workbookIssuesOptions(code, hash));
  if (issues.isPending) return <LoadingState>Loading issues...</LoadingState>;
  if (issues.isError)
    return <ApiErrorState error={issues.error} retry={() => void issues.refetch()} />;
  const groups = issueGroupsToShow(issues.data.issues);
  const readNotes = informationalIssues(issues.data.issues);
  return (
    <div className="space-y-4">
      {groups.length === 0 && <p className="text-sm">No issues reported.</p>}
      {groups.map((group) => (
        <section key={group.level} className="space-y-3">
          <h4 className="eyebrow">{group.level}</h4>
          {group.items.map((issue, index) => {
            const sheet = sheets.find((item) => item.batch.load_id === issue.load_id);
            const category = ackCategory(issue.token);
            return (
              <article
                key={`${issue.token}-${issue.load_id}-${index}`}
                className="space-y-2 rounded-sm border border-border p-4"
              >
                <div className="flex flex-wrap justify-between gap-2">
                  <h5 className="text-sm font-semibold">{tokenHeadline(issue.token)}</h5>
                  <span className="text-xs">
                    {issue.count} affected / {issue.load_id ? `Sheet ${issue.load_id}` : "Workbook"}
                  </span>
                </div>
                {issue.resolution && (
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {resolutionCopy[issue.resolution]}
                  </p>
                )}
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer">Technical detail</summary>
                  <p className="mt-1">{issue.token}</p>
                </details>
                {issue.sample_rows.length > 0 && (
                  <details className="text-xs">
                    <summary className="cursor-pointer">Sample row pointers</summary>
                    <pre className="mt-2 whitespace-pre-wrap break-all">
                      {JSON.stringify(issue.sample_rows, null, 2)}
                    </pre>
                    <p>Open Data rows for the full evidence.</p>
                  </details>
                )}
                {issue.acked && (
                  <p className="text-xs font-semibold">Acknowledged for the current revision</p>
                )}
                {group.level === "WARNING" &&
                  category &&
                  sheet &&
                  sheet.required_acknowledgements.includes(category) &&
                  category !== "POSSIBLE_REPLACEMENT" &&
                  !issue.acked &&
                  sheet.batch.status === "PENDING_REVIEW" && (
                    <Acknowledge
                      key={`${sheet.batch.load_id}-${category}`}
                      code={code}
                      hash={hash}
                      sheet={sheet}
                      category={category}
                    />
                  )}
              </article>
            );
          })}
        </section>
      ))}
      {readNotes.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">How this file was read</summary>
          <ul className="mt-2 list-disc space-y-1 pl-4">
            {readNotes.map((issue, index) => (
              <li key={`${issue.token}-${issue.load_id}-${index}`}>
                {howFileWasReadLabel(issue.token)}
                {issue.load_id ? ` / Sheet ${issue.load_id}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
export function Acknowledge({
  code,
  hash,
  sheet,
  category,
}: {
  code: string;
  hash: string;
  sheet: Sheet;
  category: Ack["category"];
}) {
  const [note, setNote] = useState("");
  const client = useQueryClient();
  const required = category === "REJECTED_ROWS" || category === "QUARANTINED_MODELS";
  const revision = sheet.batch.review_revision;
  useEffect(() => {
    setNote("");
  }, [revision]);
  const valid = !!revision && /^[0-9a-f]{64}$/.test(revision) && (!required || !!note.trim());
  const ack = useMutation({
    mutationFn: () =>
      api().acknowledge(code, hash, {
        load_id: sheet.batch.load_id,
        category,
        review_revision: revision!,
        ...(note.trim() ? { note: note.trim() } : {}),
      }),
    retry: false,
    onSettled: () => refreshPlantWorkbooks(client, code),
  });
  const presets = ACK_NOTE_PRESETS[category];
  // RO12 (D-RO12-4): acknowledgement is an Admin route; other roles are not offered it.
  const identity = useQuery(meOptions);
  if (!identity.isSuccess || !isAdmin(identity.data.principal)) return null;
  return (
    <form
      className="space-y-2 border-t border-border pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid && !ack.isPending) ack.mutate();
      }}
    >
      {presets ? (
        <ReasonPresets
          label={
            category === "QUARANTINED_MODELS"
              ? "Hold back unknown-model rows"
              : "Acknowledgement note"
          }
          ariaLabel={
            required ? "Acknowledgement note (required)" : "Acknowledgement note (optional)"
          }
          value={note}
          onChange={setNote}
          presets={presets}
          required={required}
        />
      ) : (
        <label className="block text-xs">
          Acknowledgement note ({required ? "required" : "optional"})
          <textarea
            required={required}
            maxLength={2000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            className="mt-1 block min-h-20 w-full rounded-sm border border-border bg-background p-2"
          />
        </label>
      )}
      <Button
        type="submit"
        size="sm"
        variant="outline"
        disabled={!valid || ack.isPending}
        aria-label={
          category === "QUARANTINED_MODELS"
            ? "Hold back unknown-model rows"
            : `Acknowledge ${category}`
        }
      >
        {category === "QUARANTINED_MODELS"
          ? "Hold back unknown-model rows"
          : `Acknowledge ${category}`}
      </Button>
      {ack.isError && (
        <>
          <ApiErrorState error={ack.error} />
          <p className="text-xs">
            Review re-read requested. If the revision changed, review the current warnings before
            acknowledging again.
          </p>
        </>
      )}
    </form>
  );
}
export function WorkbookRows({ code, hash }: { code: string; hash: string }) {
  const [offset, setOffset] = useState(0);
  const [disposition, setDisposition] = useState<
    components["schemas"]["WorkbookRowOut"]["disposition"] | ""
  >("");
  const rows = useQuery(
    workbookRowsOptions(code, hash, { offset, limit: 50, ...(disposition ? { disposition } : {}) }),
  );
  return (
    <div className="space-y-4">
      <label className="text-xs">
        Disposition{" "}
        <select
          aria-label="Disposition"
          value={disposition}
          onChange={(event) => {
            setDisposition(event.target.value as typeof disposition);
            setOffset(0);
          }}
          className="ml-2 rounded-sm border border-border bg-background p-2"
        >
          <option value="">All</option>
          {["LOAD", "DUPLICATE", "REJECT", "QUARANTINE"].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      <p className="text-xs text-muted-foreground">
        File evidence includes superseded facts. Correct is available only on active Measurements.
      </p>
      {rows.isPending ? (
        <LoadingState>Loading rows...</LoadingState>
      ) : rows.isError ? (
        <ApiErrorState error={rows.error} retry={() => void rows.refetch()} />
      ) : (
        <>
          {rows.data.items.length === 0 && <p className="text-sm">No rows for this selection.</p>}
          {rows.data.items.map((row) => (
            <details
              key={`${row.load_id}-${row.source_row}-${row.measurement_id}`}
              className="rounded-sm border border-border p-3"
            >
              <summary className="cursor-pointer break-words text-xs">
                {row.source_sheet} / row {row.source_row} / {row.disposition}
                {row.reason ? ` / ${row.reason}` : ""}
              </summary>
              <div className="mt-3 space-y-3">
                {row.detail && <p className="text-xs">{row.detail}</p>}
                {row.projection_missing && (
                  <p className="text-xs font-semibold">
                    Review projection missing. Stored facts are shown; raw source is unavailable.
                    Excel was not re-read.
                  </p>
                )}
                <p className="break-all text-xs text-muted-foreground">
                  Profile {row.profile_id ?? "not recorded"} / measurement{" "}
                  {row.measurement_id ?? "not committed"}
                </p>
                <div className="grid min-w-0 gap-3 md:grid-cols-2">
                  <div>
                    <h5 className="mb-2 text-xs font-semibold">Raw source</h5>
                    <pre className="whitespace-pre-wrap break-all rounded-sm bg-muted/30 p-3 text-xs">
                      {row.raw ? JSON.stringify(row.raw, null, 2) : "Not available"}
                    </pre>
                  </div>
                  <div>
                    <h5 className="mb-2 text-xs font-semibold">Canonical values</h5>
                    <dl className="space-y-1 text-xs">
                      {Object.entries(row.canonical ?? {}).map(([key, value]) => (
                        <div
                          key={key}
                          className={`break-all p-1 ${row.normalized_fields.includes(key) ? "border-l-2 border-primary bg-primary/10" : ""}`}
                        >
                          <dt className="inline font-semibold">
                            {key}
                            {row.normalized_fields.includes(key) ? " (normalized)" : ""}:{" "}
                          </dt>
                          <dd className="inline">{JSON.stringify(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                </div>
              </div>
            </details>
          ))}
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <Button
              variant="outline"
              size="sm"
              disabled={!offset || rows.isFetching}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Previous rows
            </Button>
            <span>
              {rows.data.page.total} rows / page {Math.floor(offset / 50) + 1}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + rows.data.page.returned >= rows.data.page.total || rows.isFetching}
              onClick={() => setOffset(offset + 50)}
            >
              Next rows
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
export function WorkbookHistory({ code, hash }: { code: string; hash: string }) {
  const history = useQuery(workbookHistoryOptions(code, hash));
  if (history.isPending) return <LoadingState>Loading history...</LoadingState>;
  if (history.isError)
    return <ApiErrorState error={history.error} retry={() => void history.refetch()} />;
  return (
    <ol className="space-y-3">
      {history.data.events.length === 0 && <li className="text-sm">No history recorded.</li>}
      {history.data.events.map((event) => (
        <li key={event.id} className="space-y-2 border-l-2 border-border pl-4 text-xs">
          <p className="font-semibold">{event.action}</p>
          <p className="break-all text-muted-foreground">
            {event.occurred_at} / {event.actor_user_id ?? event.actor_type}
          </p>
          <pre className="whitespace-pre-wrap break-all rounded-sm bg-muted/30 p-3">
            {JSON.stringify(event.after, null, 2)}
          </pre>
        </li>
      ))}
    </ol>
  );
}
