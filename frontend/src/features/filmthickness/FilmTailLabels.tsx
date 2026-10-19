/**
 * RO17 (D-RO17-12): a Film list's tail labels -- the words a file writes
 * below the walk that are not points (a total, a note), so a reading under
 * them is not a point's reading.
 *
 * Everyone who sees Point Check reads the list, live and retired. Only an
 * Admin adds or retires one, each with a reason. The server refuses a word
 * that reads as a live point (a reading would vanish), and that sentence is
 * shown as it is.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TAIL_COPY } from "./film-points";
import { refreshPointWrite } from "./point-edit";

type TailLabel = components["schemas"]["FilmTailLabelItem"];

export function FilmTailLabels({
  plant,
  model,
  labels,
  admin,
}: {
  plant: string;
  model: string;
  labels: TailLabel[];
  admin: boolean;
}) {
  return (
    <section
      className="mt-6"
      aria-label={`${model} ${TAIL_COPY.heading}`}
      data-testid="film-tail-labels"
    >
      <h4 className="text-sm font-bold">{TAIL_COPY.heading}</h4>
      <p className="mt-1 text-xs text-muted-foreground">{TAIL_COPY.explain}</p>
      {labels.length === 0 ? (
        <p className="mt-2 text-xs" data-testid="film-tail-labels-none">
          {TAIL_COPY.none}
        </p>
      ) : (
        <ul className="mt-2 space-y-1 text-xs">
          {labels.map((label) => (
            <li
              key={label.label_norm}
              data-film-tail={label.label_norm}
              className={`border-t border-border py-2 ${label.retired_at ? "opacity-70" : ""}`}
            >
              <span className="font-mono font-medium">{label.label_norm}</span>
              <span className="ml-2 text-muted-foreground">
                {label.retired_at ? TAIL_COPY.retired : TAIL_COPY.live}
              </span>
              <span className="block text-muted-foreground">
                {label.retired_at
                  ? `${label.retired_reason ?? "-"} · ${label.retired_at.slice(0, 10)}`
                  : `${label.note ?? "-"} · ${label.created_at.slice(0, 10)}`}
              </span>
              {admin && !label.retired_at && (
                <TailWrite plant={plant} model={model} retire={label.label_norm} />
              )}
            </li>
          ))}
        </ul>
      )}
      {admin && <TailWrite plant={plant} model={model} />}
    </section>
  );
}

/** Add (no `retire`) or retire one tail label: the button, then the reason. */
function TailWrite({ plant, model, retire }: { plant: string; model: string; retire?: string }) {
  const [asking, setAsking] = useState(false);
  const [label, setLabel] = useState("");
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const close = () => {
    setAsking(false);
    setLabel("");
    setReason("");
  };
  const write = useMutation({
    mutationFn: () => {
      const body = { label: retire ?? label.trim(), reason: reason.trim() };
      return retire
        ? api().retireFilmTailLabel(plant, model, body)
        : api().addFilmTailLabel(plant, model, body);
    },
    retry: false,
    onSuccess: async () => {
      close();
      await refreshPointWrite(client, plant, "film", model);
    },
  });
  const id = retire ? `retire-${retire.replace(/\s+/g, "-")}` : "add";

  if (!asking)
    return (
      <Button
        variant="outline"
        className="mt-2 min-h-11"
        data-testid={`film-tail-${id}`}
        onClick={() => setAsking(true)}
      >
        {retire ? TAIL_COPY.retire : TAIL_COPY.add}
      </Button>
    );
  return (
    <div
      className="mt-2 max-w-md space-y-2 border border-border p-2"
      data-testid={`film-tail-${id}-form`}
    >
      {!retire && (
        <label className="block text-xs font-medium" htmlFor="film-tail-add-label">
          {TAIL_COPY.addLabel}
          <Input
            id="film-tail-add-label"
            data-testid="film-tail-add-label"
            className="mt-1 min-h-11 font-mono"
            value={label}
            maxLength={64}
            disabled={write.isPending}
            onChange={(event) => setLabel(event.target.value)}
          />
        </label>
      )}
      <label className="block text-xs font-medium" htmlFor={`film-tail-${id}-reason`}>
        {retire ? TAIL_COPY.retireReason : TAIL_COPY.addReason}
        <Input
          id={`film-tail-${id}-reason`}
          data-testid={`film-tail-${id}-reason`}
          className="mt-1 min-h-11"
          value={reason}
          disabled={write.isPending}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          data-testid={`film-tail-${id}-submit`}
          disabled={(!retire && !label.trim()) || reason.trim().length < 3 || write.isPending}
          onClick={() => write.mutate()}
        >
          {retire ? TAIL_COPY.retireSubmit : TAIL_COPY.addSubmit}
        </Button>
        <Button variant="outline" className="min-h-11" disabled={write.isPending} onClick={close}>
          {TAIL_COPY.cancel}
        </Button>
      </div>
      {write.isError && <ApiErrorState error={write.error} />}
    </div>
  );
}
