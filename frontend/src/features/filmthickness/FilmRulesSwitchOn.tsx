/**
 * RO17 (D-RO17-11): Admin-only "Switch on the point rules" for a Film list
 * that has none.
 *
 * It writes through the existing settings route (T99, append-only), so it
 * shows first exactly what it would write: every live point counted, at the
 * H / V the list already carries. A point with no H / V stops it here --
 * the screen names those points and sends nothing, rather than guess one.
 * Once on, the list's Counted and H / V can be changed as at any plant
 * with rules.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/queries";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SWITCH_ON_COPY, type Point } from "./film-points";
import { refreshPointWrite, switchOnRows } from "./point-edit";

export function FilmRulesSwitchOn({
  plant,
  model,
  points,
}: {
  plant: string;
  model: string;
  points: Point[];
}) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const { rows, missing } = switchOnRows(points);
  const close = () => {
    setAsking(false);
    setReason("");
  };
  const save = useMutation({
    mutationFn: () =>
      api().changeFilmPointSetting(plant, model, { points: rows, reason: reason.trim() }),
    retry: false,
    onSuccess: async () => {
      close();
      await refreshPointWrite(client, plant, "film", model);
    },
  });

  if (points.length === 0) return null;
  if (!asking)
    return (
      <Button
        variant="outline"
        className="min-h-11"
        data-testid="film-rules-switch-on"
        onClick={() => setAsking(true)}
      >
        {SWITCH_ON_COPY.open}
      </Button>
    );
  return (
    <div
      className="space-y-3 border border-primary bg-[var(--primary-soft)] p-3"
      role="alert"
      data-testid="film-rules-switch-on-confirm"
    >
      <p className="text-sm font-medium">{SWITCH_ON_COPY.warning.replace("{plant}", plant)}</p>
      {missing.length > 0 ? (
        <p className="text-sm" data-testid="film-rules-switch-on-missing">
          {SWITCH_ON_COPY.missing} {missing.join(", ")}
        </p>
      ) : (
        <>
          <p className="text-xs">{SWITCH_ON_COPY.preview}</p>
          <ul
            className="max-h-64 overflow-y-auto border border-border bg-background text-xs"
            data-testid="film-rules-switch-on-rows"
          >
            {rows.map((row) => (
              <li
                key={row.point_code}
                className="border-t border-border px-2 py-1 first:border-t-0"
              >
                <span className="font-mono">{row.point_code}</span> · counted · {row.orientation}
              </li>
            ))}
          </ul>
          <label className="block text-sm font-medium" htmlFor="film-rules-switch-on-reason">
            {SWITCH_ON_COPY.reason}
            <Input
              id="film-rules-switch-on-reason"
              data-testid="film-rules-switch-on-reason"
              className="mt-1 min-h-11"
              value={reason}
              disabled={save.isPending}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
        </>
      )}
      <div className="flex flex-wrap gap-2">
        {missing.length === 0 && (
          <Button
            className="min-h-11"
            data-testid="film-rules-switch-on-submit"
            disabled={reason.trim().length < 3 || save.isPending}
            onClick={() => save.mutate()}
          >
            {SWITCH_ON_COPY.submit} {rows.length}
          </Button>
        )}
        <Button variant="outline" className="min-h-11" disabled={save.isPending} onClick={close}>
          {SWITCH_ON_COPY.cancel}
        </Button>
      </div>
      {save.isError && <ApiErrorState error={save.error} />}
    </div>
  );
}
