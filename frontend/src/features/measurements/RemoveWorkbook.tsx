import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, meOptions, refreshPlantWorkbooks, refreshActiveMeasurements } from "@/api/queries";
import { ApiError } from "@/api/client";
import { mayManagePlantFiles } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { ReasonPresets } from "./ReasonPresets";
import { RETIRE_REASON_PRESETS } from "./review-copy";

export function RemoveWorkbook({
  code,
  workbook,
  disabled = false,
  initialOpen = false,
  hideTrigger = false,
  onClosed,
  onSelect,
  onNotice,
}: {
  disabled?: boolean;
  initialOpen?: boolean;
  hideTrigger?: boolean;
  onClosed?: () => void;
  onSelect?: (workbook: components["schemas"]["WorkbookOut"]) => void;
  onNotice?: (message: string) => void;
  code: string;
  workbook: components["schemas"]["WorkbookOut"];
}) {
  const [open, setOpen] = useState(initialOpen);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  // RO12 (D-RO12-4): purge is an Admin route; other roles are not offered it.
  const identity = useQuery(meOptions);
  const live = workbook.sheets.filter(
    (sheet) => !["ABANDONED", "SUPERSEDED"].includes(sheet.batch.status),
  );
  const running = live.some((sheet) => sheet.batch.status === "RUNNING");
  const remove = useMutation({
    mutationFn: () => api().purgeWorkbook(code, workbook.file_hash, { reason: reason.trim() }),
    retry: false,
    onSuccess: async () => {
      await refreshActiveMeasurements(client);
      await refreshPlantWorkbooks(client, code);
      onNotice?.(
        "Workbook and its rows permanently deleted from the database. Re-upload is a new file; mapping is needed again if the layout is still unknown. Published plant templates stay.",
      );
      if (onClosed) {
        onClosed();
        return;
      }
      setReason("");
      setOpen(false);
    },
  });
  if (!identity.isSuccess || !mayManagePlantFiles(identity.data.principal)) return null;
  if (!live.length && !open) return null;
  return (
    <>
      {!hideTrigger && (
        <Button
          variant="ghost"
          size="sm"
          className="min-h-11 min-w-11"
          aria-label={`Delete ${workbook.source_file}`}
          disabled={running || disabled}
          title={running ? "Wait for processing to finish" : "Permanently delete workbook rows"}
          onClick={() => (onSelect ? onSelect(workbook) : setOpen(true))}
        >
          X
        </Button>
      )}
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!remove.isPending) {
            setOpen(value);
            if (!value) {
              setReason("");
              remove.reset();
              onClosed?.();
            }
          }
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto">
          <DialogTitle>Delete {workbook.source_file}</DialogTitle>
          <DialogDescription>
            This permanently deletes this workbook and its rows from the database. Re-upload is a
            new file; mapping is needed again if the layout is still unknown. Published plant
            templates stay.
          </DialogDescription>
          <ReasonPresets
            label="Removal reason"
            ariaLabel="Removal reason"
            value={reason}
            onChange={setReason}
            presets={RETIRE_REASON_PRESETS}
          />
          <Button
            disabled={
              !reason.trim() ||
              reason.trim().length > 2000 ||
              running ||
              disabled ||
              remove.isPending ||
              !live.length
            }
            onClick={() => remove.mutate()}
          >
            Permanently delete workbook
          </Button>
          {remove.isError && <ApiErrorState error={remove.error} />}
          {remove.error instanceof ApiError &&
            remove.error.status === 409 &&
            remove.error.body?.message && (
              <p role="alert" className="text-sm">
                {remove.error.body.message}
              </p>
            )}
        </DialogContent>
      </Dialog>
    </>
  );
}
