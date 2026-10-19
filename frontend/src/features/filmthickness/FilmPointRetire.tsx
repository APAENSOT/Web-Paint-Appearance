/**
 * T109 (D-109-4): retire one point, in its own row.
 *
 * Two steps on purpose, the same shape the Save warning has (D-100-6): the
 * button opens the warning, and the warning is where the reason is typed. The
 * warning is the owner's sentence -- it stops counting on the dashboard for
 * **every** month, and the readings stay in History -- because that is the
 * part a person cannot undo from this screen alone (RO17 restore is a second
 * write, with its own reason).
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/queries";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { POINT_CHECK_COPY, type Point } from "./film-points";
import { refreshPointWrite } from "./point-edit";

export function FilmPointRetire({
  plant,
  model,
  point,
  disabled,
}: {
  plant: string;
  model: string;
  point: Point;
  disabled: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const retire = useMutation({
    mutationFn: () =>
      api().retireFilmPoint(plant, model, {
        point_code: point.point_code,
        reason: reason.trim(),
      }),
    retry: false,
    onSuccess: async () => {
      setAsking(false);
      setReason("");
      await refreshPointWrite(client, plant, "film", model);
    },
  });

  if (!asking)
    return (
      <Button
        variant="outline"
        className="min-h-11"
        data-testid={`film-point-retire-${point.point_code}`}
        disabled={disabled}
        onClick={() => setAsking(true)}
      >
        {POINT_CHECK_COPY.retire}
      </Button>
    );
  return (
    <div
      className="min-w-56 space-y-2 border border-primary bg-[var(--primary-soft)] p-2"
      role="alert"
      data-testid={`film-point-retire-confirm-${point.point_code}`}
    >
      <p className="text-xs font-medium">{POINT_CHECK_COPY.retireWarning}</p>
      <label className="block text-xs font-medium" htmlFor={`retire-why-${point.point_code}`}>
        {POINT_CHECK_COPY.retireReason}
        <Input
          id={`retire-why-${point.point_code}`}
          data-testid={`film-point-retire-reason-${point.point_code}`}
          className="mt-1 min-h-11"
          value={reason}
          disabled={retire.isPending}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          data-testid={`film-point-retire-submit-${point.point_code}`}
          disabled={reason.trim().length < 3 || retire.isPending}
          onClick={() => retire.mutate()}
        >
          {POINT_CHECK_COPY.retireSubmit}
        </Button>
        <Button
          variant="outline"
          className="min-h-11"
          data-testid={`film-point-retire-cancel-${point.point_code}`}
          disabled={retire.isPending}
          onClick={() => {
            setAsking(false);
            setReason("");
          }}
        >
          {POINT_CHECK_COPY.cancel}
        </Button>
      </div>
      {retire.isError && <ApiErrorState error={retire.error} />}
    </div>
  );
}
