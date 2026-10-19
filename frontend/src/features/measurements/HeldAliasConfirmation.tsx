import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import type { useHeldAlias } from "./held-alias";

export function HeldAliasConfirmation({
  alias,
  plant,
}: {
  alias: ReturnType<typeof useHeldAlias>;
  plant: string;
}) {
  const { choice, setChoice, teach } = alias;
  return (
    <Dialog
      open={choice !== null}
      onOpenChange={(open) => {
        if (!open && !teach.isPending) setChoice(null);
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogTitle>
          {choice?.item.teachable_kind === "FILM_MODEL" ? "Propose Film model" : "Confirm alias"}
        </DialogTitle>
        {choice && (
          <>
            <DialogDescription>
              {choice.item.teachable_kind === "FILM_MODEL"
                ? `Propose ${choice.name} for sheet ${choice.item.film_model?.source_sheet ?? ""}. ${
                    choice.token
                      ? `Approving also teaches "${choice.token}" as ${choice.name} at ${plant} for future files.`
                      : "This applies to this sheet only and teaches nothing."
                  } Nothing changes until an Admin approves; the sheet is then read again.`
                : `This spelling will always mean ${choice.name} at ${plant}. It cannot be undone from this card.`}
            </DialogDescription>
            <div className="flex flex-wrap gap-2">
              <Button
                className="min-h-11"
                disabled={teach.isPending}
                aria-label={
                  choice.item.teachable_kind === "FILM_MODEL"
                    ? `Propose ${choice.name} for ${choice.item.film_model?.source_sheet ?? "this sheet"}`
                    : `Confirm alias ${choice.item.raw_value} as ${choice.name}`
                }
                onClick={() => teach.mutate(choice)}
              >
                {choice.item.teachable_kind === "FILM_MODEL" ? "Propose" : "Confirm"}
              </Button>
              <Button
                variant="outline"
                className="min-h-11"
                disabled={teach.isPending}
                onClick={() => setChoice(null)}
              >
                Cancel
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
