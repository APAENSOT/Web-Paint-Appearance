/**
 * T109 (D-109-5): add a point to this plant's walk for the model.
 *
 * The name is the one a file writes -- number **and** panel word (D-99-1) --
 * RO19: the server uses that number when free, otherwise the next free
 * catalogue number. Placement in the measuring order is chosen separately.
 *
 * H / V is left empty on purpose: empty means "take what this list's own
 * points of the same word carry" (the T100 rule, server-side), and the
 * server asks for a choice only where it cannot propose one.
 *
 * RO17 (D-RO17-10, -11): it works on a list without the point rules too,
 * and on an offered model with no list yet. Without the rules there is no
 * Counted to give (the server would ignore it), so the box is not shown; the
 * H / V goes on the list row. The server's sentence after the add says so.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, pointWalkOptions, refreshPointWalk } from "@/api/queries";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { POINT_CHECK_COPY } from "./film-points";
import { refreshPointWrite, refreshReplayed } from "./point-edit";

export function FilmPointAdd({
  plant,
  model,
  hasSetting,
  hasPoints = true,
}: {
  plant: string;
  model: string;
  hasSetting: boolean;
  hasPoints?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [orientation, setOrientation] = useState("");
  const [counted, setCounted] = useState(true);
  const [reason, setReason] = useState("");
  const [placeAfter, setPlaceAfter] = useState("");
  const walk = useQuery({
    ...pointWalkOptions(plant, "FILMTHICKNESS", model),
    enabled: open && hasPoints,
  });
  const client = useQueryClient();

  const close = () => {
    setOpen(false);
    setName("");
    setOrientation("");
    setCounted(true);
    setReason("");
    setPlaceAfter("");
  };
  const add = useMutation({
    mutationFn: () =>
      api().addFilmPoint(plant, model, {
        point_code: name.trim(),
        counted,
        orientation: orientation === "H" || orientation === "V" ? orientation : null,
        reason: reason.trim(),
        place_after: placeAfter || null,
      }),
    retry: false,
    onSuccess: async (result) => {
      close();
      await Promise.all([
        refreshPointWrite(client, plant, "film", model),
        refreshPointWalk(client, plant, "FILMTHICKNESS", model),
        refreshReplayed(client, result.replayed_load_ids),
      ]);
    },
  });

  if (!open)
    return (
      <div className="space-y-2">
        {add.isSuccess && (
          <p role="status" className="text-sm" data-testid="film-point-add-done">
            {add.data.operator_message}
          </p>
        )}
        <Button
          variant="outline"
          className="min-h-11"
          data-testid="film-point-add-open"
          onClick={() => {
            add.reset();
            setOpen(true);
          }}
        >
          {POINT_CHECK_COPY.add}
        </Button>
      </div>
    );
  return (
    <div
      className="space-y-3 border border-border p-3"
      data-testid="film-point-add"
      aria-label={POINT_CHECK_COPY.add}
    >
      <label className="block text-sm font-medium" htmlFor="film-point-add-name">
        {POINT_CHECK_COPY.addName}
        <Input
          id="film-point-add-name"
          data-testid="film-point-add-name"
          className="mt-1 min-h-11 font-mono"
          value={name}
          disabled={add.isPending}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <p className="text-xs text-muted-foreground">
        Use the point name the file writes. If its number is already taken, the server gives it the
        next free point number.
      </p>
      <label className="block text-sm font-medium" htmlFor="film-point-add-place-after">
        Place in the measuring order
        <select
          id="film-point-add-place-after"
          data-testid="film-point-add-place-after"
          className="mt-1 min-h-11 w-full min-w-0 rounded-md border border-border bg-background px-2 text-sm"
          value={placeAfter}
          disabled={add.isPending || (hasPoints && (walk.isPending || walk.isError))}
          onChange={(event) => setPlaceAfter(event.target.value)}
        >
          <option value="">After the last point</option>
          {(walk.data?.items ?? []).map((point) => (
            <option key={point.point_code} value={point.point_code}>
              After {point.label}
              {point.label !== point.point_code ? ` (${point.point_code})` : ""}
            </option>
          ))}
        </select>
      </label>
      {hasPoints && walk.isError && (
        <ApiErrorState error={walk.error} retry={() => void walk.refetch()} />
      )}
      <label className="block max-w-xs text-sm font-medium" htmlFor="film-point-add-orientation">
        {POINT_CHECK_COPY.addOrientation}
        <select
          id="film-point-add-orientation"
          data-testid="film-point-add-orientation"
          className="mt-1 min-h-11 w-full rounded-md border border-border bg-background px-2 text-sm"
          value={orientation}
          disabled={add.isPending}
          onChange={(event) => setOrientation(event.target.value)}
        >
          <option value="">{POINT_CHECK_COPY.addOrientationAuto}</option>
          <option value="H">H</option>
          <option value="V">V</option>
        </select>
      </label>
      {hasSetting && (
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            data-testid="film-point-add-counted"
            className="size-5"
            checked={counted}
            disabled={add.isPending}
            onChange={(event) => setCounted(event.target.checked)}
          />
          {POINT_CHECK_COPY.addCounted}
        </label>
      )}
      <label className="block text-sm font-medium" htmlFor="film-point-add-reason">
        {POINT_CHECK_COPY.addReason}
        <Input
          id="film-point-add-reason"
          data-testid="film-point-add-reason"
          className="mt-1 min-h-11"
          value={reason}
          disabled={add.isPending}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <p className="text-xs text-muted-foreground">{POINT_CHECK_COPY.reasonHint}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          data-testid="film-point-add-submit"
          disabled={
            name.trim().length === 0 ||
            reason.trim().length < 3 ||
            add.isPending ||
            (hasPoints && (walk.isPending || walk.isError))
          }
          onClick={() => add.mutate()}
        >
          {POINT_CHECK_COPY.addSubmit}
        </Button>
        <Button
          variant="outline"
          className="min-h-11"
          data-testid="film-point-add-cancel"
          disabled={add.isPending}
          onClick={close}
        >
          {POINT_CHECK_COPY.cancel}
        </Button>
      </div>
      {add.isError && <ApiErrorState error={add.error} />}
    </div>
  );
}
