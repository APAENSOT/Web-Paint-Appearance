import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, meOptions, refreshActiveMeasurements } from "@/api/queries";
import { supersedeSchema } from "@/api/correction-form";
import { maySupersede } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function BatchSupersede({
  batch,
  refreshing,
  onSuperseded,
}: {
  batch: components["schemas"]["BatchOut"];
  refreshing: boolean;
  onSuperseded: (result: components["schemas"]["SupersedeResult"]) => void;
}) {
  const identity = useQuery(meOptions);
  const admin = !identity.isError && maySupersede(identity.data?.principal);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [validation, setValidation] = useState("");
  const client = useQueryClient();
  const supersede = useMutation({
    mutationFn: (body: components["schemas"]["SupersedeCreate"]) =>
      api().supersede(batch.load_id, body),
    retry: false,
    onSuccess: async (result) => {
      onSuperseded(result);
      await Promise.all([
        refreshActiveMeasurements(client),
        client.invalidateQueries({ queryKey: ["batches"] }),
        client.invalidateQueries({ queryKey: ["batch", batch.load_id] }),
      ]);
    },
    onError: () => {
      void client.invalidateQueries({ queryKey: ["batch", batch.load_id] });
    },
  });
  if (!admin) return null;
  return (
    <div className="mt-5">
      {batch.status === "COMMITTED" &&
        !supersede.isSuccess &&
        (open ? (
          <form
            aria-label={`Supersede batch ${batch.load_id}`}
            className="space-y-4 rounded-sm border border-border border-l-2 border-l-destructive bg-muted/20 p-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (refreshing || supersede.isPending) return;
              const parsed = supersedeSchema.safeParse({ reason });
              if (!parsed.success) {
                setValidation(parsed.error.issues.map((issue) => issue.message).join(" "));
                return;
              }
              setValidation("");
              supersede.mutate(parsed.data);
            }}
          >
            <h4 className="font-semibold">Supersede batch {batch.load_id}</h4>
            <p className="text-sm text-muted-foreground">
              This batch's measurements will leave active reads. Original records are retained. No
              replacement batch will be named.
            </p>
            <label className="block text-sm">
              Reason for superseding
              <Textarea
                className="mt-1"
                maxLength={2000}
                value={reason}
                disabled={supersede.isPending}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            {validation && (
              <p role="alert" className="text-sm text-destructive">
                {validation}
              </p>
            )}
            <div className="flex flex-wrap gap-3">
              <Button
                type="submit"
                variant="destructive"
                disabled={refreshing || supersede.isPending}
              >
                {supersede.isPending ? "Superseding..." : "Confirm supersede"}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={supersede.isPending}
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <Button variant="outline" disabled={refreshing} onClick={() => setOpen(true)}>
            Supersede batch
          </Button>
        ))}
      {supersede.isError && <ApiErrorState error={supersede.error} />}
    </div>
  );
}
