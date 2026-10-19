/**
 * T114 (D-114-4): retire one Wave Scan point, in its own row.
 *
 * The same two steps Film's retire has (T109): the button opens the warning,
 * and the warning is where the reason is typed. No reason, no retire.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/queries";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { refreshPointWrite } from "./point-edit";
import { WS_POINTS_COPY, type WsPoint } from "./ws-points";

export function WsPointRetire({
  plant,
  model,
  point,
  disabled,
}: {
  plant: string;
  model: string;
  point: WsPoint;
  disabled: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const retire = useMutation({
    mutationFn: () =>
      api().retireWsPoint(plant, model, { zone_code: point.zone_code, reason: reason.trim() }),
    retry: false,
    onSuccess: async () => {
      setAsking(false);
      setReason("");
      await refreshPointWrite(client, plant, "wavescan", model);
    },
  });

  if (!asking)
    return (
      <Button
        variant="outline"
        className="min-h-11"
        data-testid={`ws-point-retire-${point.zone_code}`}
        disabled={disabled}
        onClick={() => setAsking(true)}
      >
        {WS_POINTS_COPY.retire}
      </Button>
    );
  return (
    <div
      className="min-w-56 space-y-2 border border-primary bg-[var(--primary-soft)] p-2"
      role="alert"
      data-testid={`ws-point-retire-confirm-${point.zone_code}`}
    >
      <p className="text-xs font-medium">{WS_POINTS_COPY.retireWarning}</p>
      <label className="block text-xs font-medium" htmlFor={`ws-retire-why-${point.point_no}`}>
        {WS_POINTS_COPY.retireReason}
        <Input
          id={`ws-retire-why-${point.point_no}`}
          data-testid={`ws-point-retire-reason-${point.zone_code}`}
          className="mt-1 min-h-11"
          value={reason}
          disabled={retire.isPending}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          data-testid={`ws-point-retire-submit-${point.zone_code}`}
          disabled={reason.trim().length < 3 || retire.isPending}
          onClick={() => retire.mutate()}
        >
          {WS_POINTS_COPY.retireSubmit}
        </Button>
        <Button
          variant="outline"
          className="min-h-11"
          data-testid={`ws-point-retire-cancel-${point.zone_code}`}
          disabled={retire.isPending}
          onClick={() => {
            setAsking(false);
            setReason("");
          }}
        >
          {WS_POINTS_COPY.cancel}
        </Button>
      </div>
      {retire.isError && <ApiErrorState error={retire.error} />}
    </div>
  );
}
