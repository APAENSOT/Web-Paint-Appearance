import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { type UploadPhase, uploadProgressCopy, uploadProgressValue } from "./review-copy";

export function UploadProgressDialog({
  open,
  plant,
  phase,
  error,
  sheets,
  busy,
  canRetry,
  onOpenStored,
  onClose,
  onRetry,
}: {
  open: boolean;
  plant: string;
  phase: UploadPhase;
  error?: Error | null;
  sheets: { filename: string; sheet: string; status: string }[];
  busy: boolean;
  canRetry: boolean;
  onOpenStored?: () => void;
  onClose: () => void;
  onRetry: () => void;
}) {
  const copy = uploadProgressCopy(phase, plant);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !busy) onClose();
      }}
    >
      <DialogContent
        aria-busy={busy}
        className={`max-w-lg ${busy ? "[&>button.absolute]:hidden" : ""}`}
        onPointerDownOutside={(event) => {
          if (busy) event.preventDefault();
        }}
        onEscapeKeyDown={(event) => {
          if (busy) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (busy) event.preventDefault();
        }}
      >
        <DialogTitle>Upload Data</DialogTitle>
        <DialogDescription>Workbook upload status for {plant}.</DialogDescription>
        <Progress value={uploadProgressValue(phase)} />
        <p role="status" className="text-sm">
          {copy}
        </p>
        {sheets.map((item) => (
          <p key={`${item.filename}-${item.sheet}`} className="text-xs">
            {item.filename} / {item.sheet}: {item.status}
          </p>
        ))}
        {error && <ApiErrorState error={error} />}
        {!busy && (
          <div className="flex flex-wrap gap-2">
            {canRetry && (
              <Button type="button" className="min-h-11" onClick={onRetry}>
                Retry upload
              </Button>
            )}
            {onOpenStored && (
              <Button type="button" className="min-h-11" onClick={onOpenStored}>
                Open the stored workbook
              </Button>
            )}
            <Button type="button" variant="outline" className="min-h-11" onClick={onClose}>
              Close
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
