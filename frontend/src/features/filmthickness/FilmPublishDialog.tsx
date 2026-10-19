import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/queries";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { RuleSources, RuleValues } from "./FilmRulePresentation";
import {
  draftFrom,
  layers,
  limitFields,
  sameValues,
  validateTriple,
  type FilmStandardPublishIn,
  type Layer,
  type Resolved,
  type TripleDraft,
} from "./film-standards";

export function FilmPublishDialog({
  plant,
  layer,
  color,
  h,
  v,
  onClose,
  onFocusReturn,
  onPublished,
}: {
  plant: string;
  layer: Layer;
  color: string | null;
  h: Resolved;
  v: Resolved;
  onClose: () => void;
  onFocusReturn: () => void;
  onPublished: () => void;
}) {
  const [horizontal, setHorizontal] = useState(() => draftFrom(h.rule));
  const [vertical, setVertical] = useState(() => draftFrom(v.rule));
  const [same, setSame] = useState(() => sameValues(h.rule, v.rule));
  const [document, setDocument] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [body, setBody] = useState<FilmStandardPublishIn | null>(null);
  const locked = useRef(false);
  const mutation = useMutation({
    mutationFn: (payload: FilmStandardPublishIn) => api().publishFilmStandard(payload),
    onSuccess: onPublished,
    onSettled: () => {
      locked.current = false;
    },
  });
  const pending = mutation.isPending;
  const scope = color ?? "Plant-wide";
  const review = () => {
    const next: Record<string, string> = {};
    const hr = validateTriple(horizontal, layer),
      vr = validateTriple(same ? horizontal : vertical, layer);
    for (const [key, message] of Object.entries(hr.errors)) next[`h-${key}`] = message;
    for (const [key, message] of Object.entries(vr.errors))
      next[`${same ? "h" : "v"}-${key}`] = message;
    if (!note.trim() || note.trim().length > 500)
      next.note = "Source note is required and must be at most 500 characters after trimming.";
    if (document.trim().length > 128)
      next.document = "Document reference must be at most 128 characters.";
    setErrors(next);
    if (Object.keys(next).length) return;
    setBody({
      plant_code: plant,
      layer_code: layer,
      color_name: color,
      h: hr.values,
      v: vr.values,
      source_note: note.trim(),
      ...(document.trim() ? { source_document: document.trim() } : {}),
    });
  };
  const fields = (
    orientation: "h" | "v",
    draft: TripleDraft,
    setDraft: (next: TripleDraft) => void,
  ) => (
    <fieldset className="min-w-0 space-y-3 rounded border border-border p-3">
      <legend className="px-1 font-semibold">
        {orientation === "h" ? "Horizontal" : "Vertical"} (µm)
      </legend>
      {limitFields(layer).map(([field, label]) => {
        const id = `${orientation}-${field}`;
        return (
          <div key={field}>
            <label htmlFor={id} className="text-sm">
              {label}
            </label>
            <Input
              id={id}
              inputMode="decimal"
              className="mt-1 min-h-11"
              value={draft[field]}
              aria-invalid={Boolean(errors[id])}
              aria-describedby={errors[id] ? `${id}-error` : undefined}
              onChange={(e) => setDraft({ ...draft, [field]: e.target.value })}
            />
            {errors[id] && (
              <p id={`${id}-error`} role="alert" className="mt-1 text-sm">
                {orientation === "h" ? "Horizontal" : "Vertical"} {label}: {errors[id]}
              </p>
            )}
          </div>
        );
      })}
    </fieldset>
  );
  const proposed = (orientation: "h" | "v"): Resolved => ({
    inherited: false,
    rule: body
      ? {
          lo: body[orientation].lo ?? null,
          hi: body[orientation].hi ?? null,
          target: body[orientation].target ?? null,
          source_document: null,
          source_note: "",
          created_at: "",
        }
      : null,
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !locked.current) onClose();
      }}
    >
      <DialogContent
        className={`max-h-[90dvh] w-[calc(100%-2rem)] max-w-3xl overflow-y-auto [&>button]:min-h-11 [&>button]:min-w-11 ${pending ? "[&>button]:pointer-events-none [&>button]:opacity-40" : ""}`}
        onEscapeKeyDown={(e) => {
          if (locked.current) e.preventDefault();
        }}
        onInteractOutside={(e) => {
          if (locked.current) e.preventDefault();
        }}
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          onFocusReturn();
        }}
      >
        <DialogTitle>{body ? "Review publish" : "Edit Film standard"}</DialogTitle>
        <DialogDescription>
          {plant} · {layers.find(([code]) => code === layer)?.[1]} · {scope} · µm
        </DialogDescription>
        {body ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <section
                aria-label="Current values"
                className="space-y-4 rounded border border-border p-3"
              >
                <h3 className="font-semibold">Current</h3>
                <RuleValues layer={layer} orientation="Horizontal" resolved={h} />
                <RuleValues layer={layer} orientation="Vertical" resolved={v} />
              </section>
              <section
                aria-label="Proposed values"
                className="space-y-4 rounded border border-border p-3"
              >
                <h3 className="font-semibold">Proposed</h3>
                <RuleValues layer={layer} orientation="Horizontal" resolved={proposed("h")} />
                <RuleValues layer={layer} orientation="Vertical" resolved={proposed("v")} />
              </section>
            </div>
            <p className="break-words text-sm">
              Document reference: {body.source_document ?? "Not provided"}
            </p>
            <p className="whitespace-pre-wrap break-words text-sm">
              Source note: {body.source_note}
            </p>
            {color === null ? (
              <p className="text-sm">
                Colour-specific overrides keep precedence over this plant-wide publication.
              </p>
            ) : (
              <p className="text-sm">
                This publish creates its own Horizontal and Vertical rules.
                {h.inherited && " Horizontal changes from inheritance to its own rule."}
                {v.inherited && " Vertical changes from inheritance to its own rule."}
              </p>
            )}
            <p className="text-sm">
              This publishes new Horizontal and Vertical rules immediately. Previous versions remain
              stored. To correct these values, publish another version.
            </p>
            {mutation.isError && <ApiErrorState error={mutation.error} />}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                className="min-h-11"
                disabled={pending}
                onClick={() => setBody(null)}
              >
                Back to edit
              </Button>
              <Button variant="outline" className="min-h-11" disabled={pending} onClick={onClose}>
                Cancel
              </Button>
              <Button
                className="min-h-11"
                disabled={pending}
                onClick={() => {
                  if (locked.current) return;
                  locked.current = true;
                  mutation.mutate(body);
                }}
              >
                {pending ? "Publishing..." : "Publish new version"}
              </Button>
            </div>
          </>
        ) : (
          <>
            <div>
              <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={same}
                  className="size-5"
                  onChange={(e) => {
                    setVertical({ ...horizontal });
                    setSame(e.target.checked);
                    setErrors({});
                  }}
                />
                Same for Horizontal and Vertical
              </label>
              <p className="text-xs text-muted-foreground">
                Checking replaces Vertical with Horizontal. Shared inputs apply to both
                orientations; unchecking starts Vertical from the shared values.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {fields("h", horizontal, setHorizontal)}
              {!same && fields("v", vertical, setVertical)}
            </div>
            <div>
              <label htmlFor="document" className="text-sm">
                Source document (optional, maximum 128 characters)
              </label>
              <Input
                id="document"
                className="mt-1 min-h-11"
                value={document}
                onChange={(e) => setDocument(e.target.value)}
                aria-invalid={Boolean(errors.document)}
                aria-describedby={errors.document ? "document-error" : undefined}
              />
              {errors.document && (
                <p id="document-error" role="alert" className="text-sm">
                  {errors.document}
                </p>
              )}
            </div>
            <div>
              <label htmlFor="note" className="text-sm">
                Source note (required, maximum 500 characters)
              </label>
              <textarea
                id="note"
                rows={3}
                className="mt-1 w-full rounded border border-border bg-background p-3 text-sm"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                aria-invalid={Boolean(errors.note)}
                aria-describedby={errors.note ? "note-error" : undefined}
              />
              {errors.note && (
                <p id="note-error" role="alert" className="text-sm">
                  {errors.note}
                </p>
              )}
            </div>
            <div>
              <p className="text-sm font-semibold">Current sources for reference</p>
              <RuleSources h={h} v={v} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" className="min-h-11" onClick={onClose}>
                Cancel
              </Button>
              <Button className="min-h-11" onClick={review}>
                Review publish
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
