import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  workbookOptions,
  refreshActiveMeasurements,
  refreshPlantWorkbooks,
} from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { FileCounts, FileRange, UploadedAt } from "./files-shared";
import { WorkbookIssues, WorkbookRows, WorkbookHistory, SkippedSheets } from "./WorkbookSections";
import { FilesMapping } from "./FilesMapping";
import { HeldIdentityList } from "./HeldIdentityList";

type Sheet = components["schemas"]["WorkbookSheetOut"];
export function WorkbookDetail({
  code,
  hash,
  onBack,
}: {
  code: string;
  hash: string;
  onBack: () => void;
}) {
  const [confirmed, setConfirmed] = useState("");
  const [section, setSection] = useState("Summary");
  const [outcomes, setOutcomes] = useState<{ id: number; name: string; error?: Error }[]>([]);
  const client = useQueryClient();
  const detail = useQuery(workbookOptions(code, hash));
  const commit = useMutation({
    mutationFn: async (sheets: Sheet[]) => {
      setOutcomes([]);
      for (const sheet of sheets) {
        try {
          await api().commit(sheet.batch.load_id);
          setOutcomes((previous) => [
            ...previous,
            { id: sheet.batch.load_id, name: sheet.batch.source_sheet },
          ]);
        } catch (error) {
          setOutcomes((previous) => [
            ...previous,
            {
              id: sheet.batch.load_id,
              name: sheet.batch.source_sheet,
              error: error instanceof Error ? error : new Error(String(error)),
            },
          ]);
        }
      }
    },
    retry: false,
    onSettled: async () => {
      await refreshActiveMeasurements(client);
      await refreshPlantWorkbooks(client, code);
    },
  });
  const results = (
    <div className="space-y-3">
      {confirmed && (
        <p role="status" className="p-4 text-sm">
          {confirmed}
        </p>
      )}
      {outcomes.map((outcome) => (
        <div key={outcome.id} role="status">
          {outcome.error ? (
            <>
              <p className="text-sm">{outcome.name}: not committed</p>
              <ApiErrorState error={outcome.error} />
            </>
          ) : (
            <p className="text-sm">{outcome.name}: committed</p>
          )}
        </div>
      ))}
    </div>
  );
  if (detail.isPending) return <LoadingState>Loading workbook...</LoadingState>;
  if (detail.isError)
    return (
      <div className="panel">
        <Button variant="ghost" onClick={onBack}>
          Back to files
        </Button>
        {results}
        <ApiErrorState error={detail.error} retry={() => void detail.refetch()} />
      </div>
    );
  const workbook = detail.data.workbook;
  const allSkipped = workbook.operational_summary === "SKIPPED";
  const eligible = workbook.sheets.filter((sheet) => sheet.committable);
  return (
    <div className="panel min-w-0 overflow-hidden">
      <header className="space-y-3 border-b border-border p-5">
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back to files
        </Button>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="min-w-0 break-all text-lg font-semibold">{workbook.source_file}</h3>
          <strong className="rounded-sm border border-border px-2 py-1 text-xs">
            {allSkipped ? "Skipped sheets kept as evidence" : workbook.operational_summary}
          </strong>
        </div>
        <FileRange workbook={workbook} />
        {workbook.superseded && (
          <p className="text-sm font-semibold">
            Superseded: these sheets have left active reads. Original records are retained here.
          </p>
        )}
        <p className="break-all text-[10px] text-muted-foreground">SHA-256 {hash}</p>
      </header>
      <nav
        aria-label="Workbook sections"
        className="flex flex-wrap gap-2 border-b border-border p-3"
      >
        {["Summary", "Issues", "Data rows", "History"].map((tab) => (
          <Button
            key={tab}
            variant={section === tab ? "default" : "ghost"}
            size="sm"
            aria-pressed={section === tab}
            onClick={() => setSection(tab)}
          >
            {tab}
          </Button>
        ))}
      </nav>
      <div className="min-w-0 space-y-4 p-5">
        {results}
        {section === "Summary" && (
          <>
            <FileCounts counts={workbook.counts} />
            <SkippedSheets workbook={workbook} />
            <p className="text-xs text-muted-foreground">
              <UploadedAt uploadedAt={workbook.uploaded_at} />
            </p>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h4 className="font-semibold">Sheets / {workbook.sheet_count}</h4>
              {!allSkipped && (
                <Button
                  size="sm"
                  disabled={!eligible.length || commit.isPending || detail.isFetching}
                  onClick={() => commit.mutate(eligible)}
                >
                  {commit.isPending ? "Committing..." : "Commit all eligible"}
                </Button>
              )}
            </div>
            {!allSkipped && (
              <p className="text-xs text-muted-foreground">
                Each sheet commits independently. Blocked sheets remain in review.
              </p>
            )}
            {workbook.sheets.map((sheet) => (
              <article
                key={sheet.batch.load_id}
                aria-label={`Sheet ${sheet.batch.load_id}`}
                className="min-w-0 space-y-3 rounded-sm border border-border p-4"
              >
                <div className="flex flex-wrap justify-between gap-3">
                  <h5 className="break-all font-semibold">{sheet.batch.source_sheet}</h5>
                  <span className="text-xs font-semibold">{sheet.batch.status}</span>
                </div>
                <FileCounts counts={sheet.batch.counts} />
                <p className="text-xs">
                  Committable: {sheet.committable ? "Yes" : "No"} / fixture_verified:{" "}
                  {String(sheet.batch.fixture_verified ?? false)}
                </p>
                {sheet.commit_blockers.length > 0 && (
                  <p className="break-words text-xs">
                    Commit blockers: {sheet.commit_blockers.join(", ")}
                  </p>
                )}
                {sheet.required_acknowledgements.length > 0 && (
                  <p className="text-xs">
                    Required acknowledgements:{" "}
                    {sheet.required_acknowledgements
                      .map(
                        (category) =>
                          `${category} (${sheet.acknowledged.includes(category) ? "acknowledged" : "review in Issues"})`,
                      )
                      .join(", ")}
                  </p>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!sheet.committable || commit.isPending || detail.isFetching}
                  onClick={() => commit.mutate([sheet])}
                >
                  Commit sheet
                </Button>
                {sheet.batch.status === "COMMITTED" && (
                  <SupersedeSheet sheet={sheet} code={code} onConfirmed={setConfirmed} />
                )}
                {sheet.batch.sheet_class === "WAVESCAN" &&
                  (sheet.batch.status === "PENDING_REVIEW" ||
                    sheet.batch.status === "REJECTED_TEMPLATE" ||
                    sheet.batch.status === "COMMITTED") && (
                    <HeldIdentityList
                      loadId={sheet.batch.load_id}
                      plant={code}
                      status={sheet.batch.status}
                    />
                  )}
                {(sheet.batch.status === "REJECTED_TEMPLATE" ||
                  sheet.batch.status === "PENDING_REVIEW" ||
                  sheet.batch.status === "RUNNING") && (
                  <details>
                    <summary className="cursor-pointer text-xs font-semibold">
                      Mapping review
                    </summary>
                    <FilesMapping
                      id={sheet.batch.load_id}
                      status={sheet.batch.status}
                      plant={code}
                    />
                  </details>
                )}
              </article>
            ))}
            <h4 className="font-semibold">Template profiles</h4>
            {detail.data.profiles.length === 0 && (
              <p className="text-xs text-muted-foreground">No template profile recorded.</p>
            )}
            {detail.data.profiles.map((profile) => (
              <div
                className="space-y-2 rounded-sm border border-border p-3 text-xs"
                key={profile.profile_id}
              >
                <p>
                  Profile {profile.profile_id} / version {profile.version} / fixture_verified:{" "}
                  {String(profile.fixture_verified)}
                </p>
                <p>
                  Sheets: {profile.load_ids.join(", ")} / fill_missing_plant:{" "}
                  {String(profile.fill_missing_plant)}
                </p>
                <p className="break-all">Fingerprint: {profile.template_fingerprint}</p>
                {profile.notes && <p>{profile.notes}</p>}
              </div>
            ))}
            {detail.data.possible_replacements.length > 0 && (
              <p className="text-xs">
                POSSIBLE_REPLACEMENT: overlapping workbook dates are advisory only. This does not
                block commit or supersede anything automatically. Review Issues; supersede is a
                separate sheet control.
              </p>
            )}
          </>
        )}
        {section === "Issues" && (
          <WorkbookIssues code={code} hash={hash} sheets={workbook.sheets} />
        )}
        {section === "Data rows" && <WorkbookRows code={code} hash={hash} />}
        {section === "History" && <WorkbookHistory code={code} hash={hash} />}
      </div>
    </div>
  );
}
function SupersedeSheet({
  sheet,
  code,
  onConfirmed,
}: {
  sheet: Sheet;
  code: string;
  onConfirmed: (notice: string) => void;
}) {
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const supersede = useMutation({
    mutationFn: () => api().supersede(sheet.batch.load_id, { reason: reason.trim() }),
    onSuccess: () =>
      onConfirmed(
        `Sheet ${sheet.batch.load_id} superseded. Original records retained; the sheet has left active reads.`,
      ),
    retry: false,
    onSettled: async () => {
      await refreshActiveMeasurements(client);
      await refreshPlantWorkbooks(client, code);
    },
  });
  return (
    <details className="border-t border-border pt-3">
      <summary className="cursor-pointer text-xs font-semibold">Supersede sheet</summary>
      <form
        className="mt-3 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (reason.trim() && !supersede.isPending) supersede.mutate();
        }}
      >
        <p className="text-xs text-muted-foreground">
          This sheet will leave active reads. Original records are retained. This action is separate
          from committing a replacement.
        </p>
        <label className="block text-xs">
          Reason (required)
          <textarea
            required
            maxLength={2000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="mt-1 block min-h-20 w-full rounded-sm border border-border bg-background p-2"
          />
        </label>
        <Button
          size="sm"
          variant="outline"
          type="submit"
          disabled={!reason.trim() || supersede.isPending}
        >
          Confirm supersede
        </Button>
        {supersede.isError && <ApiErrorState error={supersede.error} />}
      </form>
    </details>
  );
}
