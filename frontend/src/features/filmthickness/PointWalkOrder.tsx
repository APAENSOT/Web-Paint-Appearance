import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { api, pointWalkOptions, refreshPointWalk } from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PointName } from "./PointEdit";
import { moveWalkPoint, placeWalkPointAfter, rebaseWalkDraft, type WalkDraft } from "./point-walk";

type Domain = components["schemas"]["PointWalkOut"]["domain"];
type Preview = components["schemas"]["PointWalkDryRunOut"];

export function PointWalkOrder({
  plant,
  model,
  domain,
  admin,
}: {
  plant: string;
  model: string;
  domain: Domain;
  admin: boolean;
}) {
  const query = useQuery(pointWalkOptions(plant, domain, model));
  const client = useQueryClient();
  const id = useId();
  const [draft, setDraft] = useState<WalkDraft | null>(null);
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<{ signature: string; result: Preview } | null>(null);
  const [conflict, setConflict] = useState(false);
  const [saved, setSaved] = useState(false);
  const items = query.data?.items ?? [];
  const savedCodes = items.map((point) => point.point_code);
  const codes = draft?.point_codes ?? savedCodes;
  const signature = JSON.stringify(codes);
  const changed = signature !== JSON.stringify(savedCodes);
  const stale = conflict || Boolean(draft && draft.expected_version_id !== query.data?.version_id);
  const previewCurrent = preview?.signature === signature;

  const check = useMutation({
    mutationFn: (point_codes: string[]) =>
      api().dryRunPointWalk(plant, domain, model, { point_codes, simulate_film_rules: false }),
    retry: false,
    onSuccess: (result, checkedCodes) =>
      setPreview({ signature: JSON.stringify(checkedCodes), result }),
  });
  const save = useMutation({
    mutationFn: () =>
      api().setPointWalk(plant, domain, model, {
        point_codes: [...codes],
        expected_version_id: draft ? draft.expected_version_id : (query.data?.version_id ?? null),
        reason: reason.trim(),
      }),
    retry: false,
    onSuccess: async (result) => {
      client.setQueryData(pointWalkOptions(plant, domain, model).queryKey, result);
      setDraft(null);
      setReason("");
      setPreview(null);
      setConflict(false);
      setSaved(true);
      await refreshPointWalk(client, plant, domain, model);
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(true);
        await query.refetch();
      }
    },
  });

  const edit = (next: string[]) => {
    setDraft({
      point_codes: next,
      expected_version_id: draft ? draft.expected_version_id : (query.data?.version_id ?? null),
    });
    setSaved(false);
    setPreview(null);
    check.reset();
  };
  const reset = () => {
    setDraft(null);
    setReason("");
    setPreview(null);
    setConflict(false);
    setSaved(false);
    save.reset();
    check.reset();
  };

  return (
    <section
      className="mt-5 min-w-0 space-y-3 rounded-md border border-border p-3 sm:p-4"
      aria-label={`${model} measuring order`}
      data-testid={`point-walk-${domain}`}
    >
      <h4 className="text-sm font-bold">Measuring order</h4>
      <p className="text-xs text-muted-foreground">
        The order this plant measures the points. Point names and numbers stay the same. Saving
        keeps the previous order and records your reason.
      </p>
      {query.isPending ? (
        <LoadingState>Loading measuring order...</LoadingState>
      ) : query.isError ? (
        <ApiErrorState error={query.error} retry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        <p className="text-sm">Add the first point to start this measuring order.</p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            {changed
              ? "Unsaved measuring order. The saved ranks below are kept until you save."
              : "Current measuring order."}
          </p>
          <ol className="max-h-[28rem] space-y-2 overflow-y-auto">
            {codes.map((code, index) => {
              const point = items.find((item) => item.point_code === code);
              if (!point)
                return (
                  <li key={code} className="break-all text-sm">
                    {code} — no longer on the live list
                  </li>
                );
              return (
                <li
                  key={code}
                  data-walk-code={code}
                  data-walk-rank={point.walk_rank}
                  className="flex min-w-0 flex-col gap-2 rounded border border-border p-2 sm:flex-row sm:items-center"
                >
                  <div className="min-w-0 flex-1 break-words text-sm">
                    <span className="mr-2 text-xs text-muted-foreground">
                      Saved rank {point.walk_rank}
                    </span>
                    <PointName label={point.label} code={code} />
                    <span className="ml-2 text-xs text-muted-foreground">
                      Point {point.point_no}
                    </span>
                  </div>
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="min-h-11"
                      aria-label={`Move up ${code}`}
                      disabled={index === 0 || save.isPending || stale}
                      onClick={() => edit(moveWalkPoint(codes, code, -1))}
                    >
                      ↑
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="min-h-11"
                      aria-label={`Move down ${code}`}
                      disabled={index === codes.length - 1 || save.isPending || stale}
                      onClick={() => edit(moveWalkPoint(codes, code, 1))}
                    >
                      ↓
                    </Button>
                    <select
                      aria-label={`Place after ${code}`}
                      value=""
                      disabled={save.isPending || stale}
                      className="min-h-11 min-w-0 max-w-full flex-1 rounded-md border border-border bg-background px-2 text-xs sm:w-44"
                      onChange={(event) => {
                        if (event.target.value)
                          edit(placeWalkPointAfter(codes, code, event.target.value));
                      }}
                    >
                      <option value="">Place after…</option>
                      {items
                        .filter((item) => item.point_code !== code)
                        .map((item) => (
                          <option key={item.point_code} value={item.point_code}>
                            {item.label}
                          </option>
                        ))}
                    </select>
                  </div>
                </li>
              );
            })}
          </ol>
          {stale && (
            <div role="alert" className="space-y-2 rounded border border-border p-3 text-sm">
              <p>
                The saved order changed while you were editing. Your draft is kept. Review the
                latest list before saving.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={reset}>
                  Use latest order
                </Button>
                <Button
                  variant="outline"
                  disabled={!draft || !query.data || !rebaseWalkDraft(draft, query.data)}
                  onClick={() => {
                    if (!draft || !query.data) return;
                    const rebased = rebaseWalkDraft(draft, query.data);
                    if (rebased) {
                      setDraft(rebased);
                      setConflict(false);
                      setPreview(null);
                      check.reset();
                      save.reset();
                    }
                  }}
                >
                  Keep draft on latest version
                </Button>
              </div>
            </div>
          )}
          <label htmlFor={id} className="block text-sm font-medium">
            Why does the measuring order change?
            <Input
              id={id}
              className="mt-1 min-h-11"
              value={reason}
              maxLength={500}
              disabled={save.isPending}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <p className="text-xs text-muted-foreground">
            At least 3 characters. Stored with your name and the time.
          </p>
          {admin && (
            <div className="space-y-2">
              <Button
                variant="outline"
                className="min-h-11"
                disabled={check.isPending || save.isPending || stale}
                onClick={() => check.mutate([...codes])}
              >
                Preview stored sheets
              </Button>
              {check.isPending && (
                <p role="status" className="text-sm">
                  Checking stored sheets...
                </p>
              )}
              {previewCurrent && preview && (
                <div role="status" className="space-y-1 text-sm" data-testid="point-walk-preview">
                  <p>
                    {preview.result.changed_sheets} of {preview.result.stored_sheets} stored sheets
                    would read differently.
                  </p>
                  <p>
                    {preview.result.changed_dispositions} row dispositions and{" "}
                    {preview.result.changed_vehicle_ids} vehicle ids would change.
                  </p>
                  {preview.result.held_sheets.length > 0 && (
                    <ul className="space-y-1">
                      {preview.result.held_sheets.map((sheet) => (
                        <li key={sheet.load_id} className="break-words">
                          {sheet.source_file} / {sheet.source_sheet}: {sheet.reasons.join(", ")}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {check.isError && <ApiErrorState error={check.error} />}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              className="min-h-11"
              disabled={
                !changed ||
                reason.trim().length < 3 ||
                save.isPending ||
                check.isPending ||
                stale ||
                (admin && !previewCurrent)
              }
              onClick={() => save.mutate()}
            >
              Save measuring order
            </Button>
            <Button
              variant="outline"
              className="min-h-11"
              disabled={save.isPending || !draft}
              onClick={reset}
            >
              Discard draft
            </Button>
          </div>
          {saved && (
            <p role="status" className="text-sm">
              Measuring order saved as a new version.
            </p>
          )}
          {save.isError && !stale && <ApiErrorState error={save.error} />}
        </>
      )}
    </section>
  );
}
