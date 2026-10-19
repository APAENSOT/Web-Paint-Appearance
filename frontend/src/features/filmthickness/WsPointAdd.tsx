/**
 * T114 (D-114-6): add a Wave Scan point at the end of this plant's walk.
 *
 * One box: pick an existing zone code from the list (a `datalist` of the
 * server's `zone_choices`) or type a new one. Horizontal / Vertical is
 * **shown, never chosen** -- an existing code carries its own, a new code
 * takes the one its name gives (Hood, Roof or Floor is Horizontal). The
 * server reads it off the name again, and refuses a twin spelling, a code
 * already on the list, a retired one, or a model with no position left; this
 * form does not predict those refusals, it shows them.
 *
 * RO17 (D-RO17-7): an Admin may also make the point count towards complete
 * cars. Ticking it asks the server first how many stored cars that would
 * make incomplete, and the number is on screen before Add is pressed. Anyone
 * else sends false, which keeps today's extra point. On an offered model
 * with no list yet (D-RO17-10) this is how the first point goes on; the
 * server's sentence after the add says what that means for uploads.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, wsCompletenessImpactOptions } from "@/api/queries";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { refreshPointWrite } from "./point-edit";
import { WS_POINTS_COPY, addPreview, type WsZoneChoice } from "./ws-points";

export function WsPointAdd({
  plant,
  model,
  choices,
  horizontalWords,
  admin,
}: {
  plant: string;
  model: string;
  choices: WsZoneChoice[];
  horizontalWords: string[];
  admin: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [counted, setCounted] = useState(true);
  const [complete, setComplete] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const preview = addPreview(code, choices, horizontalWords);
  const inCompleteness = admin && complete;
  const impact = useQuery({
    ...wsCompletenessImpactOptions(plant, model, code.trim()),
    enabled: inCompleteness && Boolean(model && code.trim()),
  });

  const close = () => {
    setOpen(false);
    setCode("");
    setCounted(true);
    setComplete(false);
    setReason("");
  };
  const add = useMutation({
    mutationFn: () =>
      api().addWsPoint(plant, model, {
        zone_code: code.trim(),
        counted,
        counted_in_completeness: inCompleteness,
        reason: reason.trim(),
      }),
    retry: false,
    onSuccess: async () => {
      close();
      await refreshPointWrite(client, plant, "wavescan", model);
    },
  });

  if (!open)
    return (
      <div className="space-y-2">
        {add.isSuccess && (
          <p role="status" className="text-sm" data-testid="ws-point-add-done">
            {add.data.operator_message}
          </p>
        )}
        <Button
          variant="outline"
          className="min-h-11"
          data-testid="ws-point-add-open"
          onClick={() => {
            add.reset();
            setOpen(true);
          }}
        >
          {WS_POINTS_COPY.add}
        </Button>
      </div>
    );
  const listId = `ws-zone-choices-${model.replace(/\W+/g, "-")}`;
  return (
    <div
      className="space-y-3 border border-border p-3"
      data-testid="ws-point-add"
      aria-label={WS_POINTS_COPY.add}
    >
      <label className="block text-sm font-medium" htmlFor="ws-point-add-code">
        {WS_POINTS_COPY.addCode}
        <Input
          id="ws-point-add-code"
          data-testid="ws-point-add-code"
          className="mt-1 min-h-11 font-mono"
          list={listId}
          autoComplete="off"
          value={code}
          disabled={add.isPending}
          onChange={(event) => setCode(event.target.value)}
        />
      </label>
      <datalist id={listId}>
        {choices.map((choice) => (
          <option key={choice.zone_code} value={choice.zone_code}>
            {choice.tolerance_group}
          </option>
        ))}
      </datalist>
      <p className="text-xs text-muted-foreground">{WS_POINTS_COPY.addCodeHint}</p>
      {preview && (
        <dl
          className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm"
          data-testid="ws-point-add-preview"
        >
          <dt className="text-muted-foreground">{WS_POINTS_COPY.addHv}</dt>
          <dd data-testid="ws-point-add-hv" className="font-medium">
            {preview.tolerance}
          </dd>
          <dt className="sr-only">Code</dt>
          <dd className="col-span-2 text-xs text-muted-foreground" data-testid="ws-point-add-kind">
            {preview.isNew ? WS_POINTS_COPY.addNew : WS_POINTS_COPY.addExisting}
          </dd>
        </dl>
      )}
      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          type="checkbox"
          data-testid="ws-point-add-counted"
          className="size-5"
          checked={counted}
          disabled={add.isPending}
          onChange={(event) => setCounted(event.target.checked)}
        />
        {WS_POINTS_COPY.addCounted}
      </label>
      {admin && (
        <>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              data-testid="ws-point-add-complete"
              className="size-5"
              checked={complete}
              disabled={add.isPending}
              onChange={(event) => setComplete(event.target.checked)}
            />
            {WS_POINTS_COPY.addComplete}
          </label>
          <p className="text-xs text-muted-foreground">{WS_POINTS_COPY.addCompleteHint}</p>
          {inCompleteness && preview && (
            <div data-testid="ws-point-add-impact" role="status" className="text-sm font-medium">
              {impact.isPending ? (
                WS_POINTS_COPY.addImpactLoading
              ) : impact.isError ? (
                <ApiErrorState error={impact.error} retry={() => void impact.refetch()} />
              ) : (
                WS_POINTS_COPY.addImpact.replace("{n}", String(impact.data.cars_become_incomplete))
              )}
            </div>
          )}
        </>
      )}
      <label className="block text-sm font-medium" htmlFor="ws-point-add-reason">
        {WS_POINTS_COPY.addReason}
        <Input
          id="ws-point-add-reason"
          data-testid="ws-point-add-reason"
          className="mt-1 min-h-11"
          value={reason}
          disabled={add.isPending}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <p className="text-xs text-muted-foreground">{WS_POINTS_COPY.reasonHint}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          data-testid="ws-point-add-submit"
          disabled={
            !preview ||
            reason.trim().length < 3 ||
            add.isPending ||
            // D-RO17-7: the count is on screen before a counted add can go.
            (inCompleteness && !impact.isSuccess)
          }
          onClick={() => add.mutate()}
        >
          {WS_POINTS_COPY.addSubmit}
        </Button>
        <Button
          variant="outline"
          className="min-h-11"
          data-testid="ws-point-add-cancel"
          disabled={add.isPending}
          onClick={close}
        >
          {WS_POINTS_COPY.cancel}
        </Button>
      </div>
      {add.isError && <ApiErrorState error={add.error} />}
    </div>
  );
}
