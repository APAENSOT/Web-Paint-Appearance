import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, meOptions } from "@/api/queries";
import { mayManagePlantFiles } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { profilePublishAvailable, showsFillMissingPlant } from "./review-copy";

type Sheet = components["schemas"]["WorkbookSheetOut"];

export function TemplatePublishDialog({
  code,
  hash,
  sheet,
}: {
  code: string;
  hash: string;
  sheet: Sheet;
}) {
  const identity = useQuery(meOptions);
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [namedOwner, setNamedOwner] = useState("");
  const [notes, setNotes] = useState("");
  const [fillMissingPlant, setFillMissingPlant] = useState(false);
  const headers = sheet.batch.unreviewed_headers ?? [];
  const [reasons, setReasons] = useState<Record<string, string>>(() =>
    Object.fromEntries(headers.map((header) => [header, ""])),
  );
  const canFillPlant = showsFillMissingPlant(sheet);
  const owner = namedOwner.trim();
  const proofNotes = notes.trim();
  const validReasons = headers.every((header) => {
    const reason = reasons[header]?.trim() ?? "";
    return reason.length >= 1 && reason.length <= 2000;
  });
  const valid =
    owner.length >= 1 &&
    owner.length <= 200 &&
    proofNotes.length >= 1 &&
    proofNotes.length <= 2000 &&
    validReasons;
  const publish = useMutation({
    mutationFn: () =>
      api().publishTemplateProfile(code, {
        file_hash: hash,
        source_sheet: sheet.batch.source_sheet,
        named_owner: owner,
        notes: proofNotes,
        fill_missing_plant: canFillPlant && fillMissingPlant,
        ...(headers.length
          ? {
              ignored_headers: headers.map((header) => ({
                header,
                reason: reasons[header].trim(),
              })),
            }
          : {}),
      }),
    retry: false,
    onSuccess: async (result) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["workbooks", code] }),
        client.invalidateQueries({ queryKey: ["workbook", code, hash] }),
        client.invalidateQueries({ queryKey: ["worksheet", code, hash] }),
        ...(result.replayed_load_ids ?? []).map((loadId) =>
          client.invalidateQueries({ queryKey: ["batch", loadId] }),
        ),
      ]);
    },
  });

  if (
    !identity.isSuccess ||
    !mayManagePlantFiles(identity.data.principal) ||
    !profilePublishAvailable(sheet)
  )
    return null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          Publish verified layout
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl">
        <DialogTitle>Publish verified layout</DialogTitle>
        <DialogDescription>
          This records that a named owner verified this layout. Stored sheets with the same contract
          will be replayed. Nothing is written as measurements until someone approves a sheet.
        </DialogDescription>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid && !publish.isPending) publish.mutate();
          }}
        >
          <label className="block text-sm font-medium">
            Named owner
            <input
              aria-label="Named owner"
              autoComplete="off"
              maxLength={200}
              value={namedOwner}
              onChange={(event) => setNamedOwner(event.target.value)}
              className="mt-1 block w-full border border-border bg-background p-2"
            />
          </label>
          <p className="text-xs text-muted-foreground">
            Enter the plant or quality owner who checked the workbook. The signed-in Admin is not
            filled in automatically.
          </p>
          <label className="block text-sm font-medium">
            Notes
            <textarea
              aria-label="Notes"
              maxLength={2000}
              rows={3}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="mt-1 block w-full border border-border bg-background p-2"
            />
          </label>
          {headers.length > 0 && (
            <section aria-label="Ignored header reasons" className="space-y-3 border-t pt-4">
              <h3 className="text-sm font-semibold">Headers to mark ignored</h3>
              <p className="text-xs text-muted-foreground">
                Each header needs its own reason. Nothing is ignored automatically.
              </p>
              {headers.map((header) => (
                <label key={header} className="block text-sm font-medium">
                  Reason for ignoring {header}
                  <textarea
                    aria-label={`Reason for ignoring ${header}`}
                    maxLength={2000}
                    rows={2}
                    value={reasons[header] ?? ""}
                    onChange={(event) =>
                      setReasons((previous) => ({
                        ...previous,
                        [header]: event.target.value,
                      }))
                    }
                    className="mt-1 block w-full border border-border bg-background p-2"
                  />
                </label>
              ))}
            </section>
          )}
          {canFillPlant && (
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                aria-label="Fill missing Plant column"
                checked={fillMissingPlant}
                onChange={(event) => setFillMissingPlant(event.target.checked)}
              />
              Fill missing Plant column from this upload's plant
            </label>
          )}
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">Publish details</summary>
            <p className="mt-2 break-all">Stored workbook: {hash}</p>
            <p>Source sheet: {sheet.batch.source_sheet}</p>
            <p>semantic_signature: {sheet.batch.semantic_signature ?? "not available"}</p>
          </details>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={!valid || publish.isPending}>
              {publish.isPending ? "Publishing..." : "Publish layout"}
            </Button>
            <p className="text-xs text-muted-foreground">Publishing does not approve this sheet.</p>
          </div>
        </form>
        {publish.isError && <ApiErrorState error={publish.error} />}
        {publish.data && (
          <section role="status" className="space-y-2 border-t border-border pt-4 text-sm">
            <p className="font-semibold">Replay finished. Nothing was approved as measurements.</p>
            <details>
              <summary className="cursor-pointer">Published profile details</summary>
              <div className="mt-2 space-y-1 break-all text-xs text-muted-foreground">
                <p>
                  Profile {publish.data.profile_id} / version {publish.data.version}
                </p>
                <p>
                  replayed load IDs: {(publish.data.replayed_load_ids ?? []).join(", ") || "none"}
                </p>
                <p>audit_action: {publish.data.audit_action}</p>
              </div>
            </details>
          </section>
        )}
      </DialogContent>
    </Dialog>
  );
}
