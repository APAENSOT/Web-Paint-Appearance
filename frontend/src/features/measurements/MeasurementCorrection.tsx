import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ZodError } from "zod";
import { ApiError } from "@/api/client";
import { api, measurementOptions, refreshActiveMeasurements } from "@/api/queries";
import { buildCorrection, correctionFields, correctionValues } from "@/api/correction-form";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ReasonPresets } from "./ReasonPresets";
import { CORRECT_REASON_PRESETS } from "./review-copy";

export function MeasurementCorrection({
  id,
  onClose,
  onNotice,
}: {
  id: number;
  onClose: () => void;
  onNotice: (notice: string | Error) => void;
}) {
  const current = useQuery({ ...measurementOptions(id), refetchOnWindowFocus: false });
  const client = useQueryClient();
  useEffect(() => {
    if (current.error instanceof ApiError && current.error.status === 404) {
      onNotice(current.error);
      void refreshActiveMeasurements(client);
    }
  }, [current.error, client, onNotice]);
  if (current.isPending) return <LoadingState>Loading current measurement...</LoadingState>;
  if (current.isError) return <ApiErrorState error={current.error} />;
  return <CorrectionForm row={current.data} onClose={onClose} onNotice={onNotice} />;
}

function CorrectionForm({
  row,
  onClose,
  onNotice,
}: {
  row: components["schemas"]["MeasurementOut"];
  onClose: () => void;
  onNotice: (notice: string | Error) => void;
}) {
  const [values, setValues] = useState(() => correctionValues(row));
  const [reason, setReason] = useState("");
  const [validation, setValidation] = useState("");
  const client = useQueryClient();
  const correction = useMutation({
    mutationFn: (body: components["schemas"]["CorrectionCreate"]) =>
      api().correct(row.measurement_id, body),
    retry: false,
    onSuccess: async (result) => {
      onNotice(
        `Correction created: measurement ${result.superseded_measurement_id} retired; measurement ${result.measurement.measurement_id} is now active. Original values retained.`,
      );
      await refreshActiveMeasurements(client);
      onClose();
    },
    onError: async (error) => {
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) {
        onNotice(error);
        await refreshActiveMeasurements(client);
      }
    },
  });
  const refused =
    correction.error instanceof ApiError && [403, 404, 409].includes(correction.error.status);
  return (
    <form
      aria-label={`Correct measurement ${row.measurement_id}`}
      className="mt-6 border-t border-border pt-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (correction.isPending || correction.isSuccess || refused) return;
        try {
          const body = buildCorrection(row, values, reason);
          setValidation("");
          correction.mutate(body);
        } catch (error) {
          setValidation(
            error instanceof ZodError
              ? error.issues
                  .map((issue) => `${issue.path.join(".") || "Reason"}: ${issue.message}`)
                  .join(" ")
              : (error as Error).message,
          );
        }
      }}
    >
      <h3 className="font-semibold">Correct measurement {row.measurement_id}</h3>
      <p className="mt-2 text-sm text-muted-foreground">
        Create a new measurement with a recorded reason. Only changed values are submitted; the
        original is retained.
      </p>
      <fieldset
        disabled={correction.isPending || correction.isSuccess || refused}
        className="mt-4 space-y-4"
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {correctionFields.map((key) => (
            <label key={key} className="block text-sm">
              <span className="mb-1 block">
                {key === "measured_date"
                  ? "Measured date"
                  : key === "serial_no"
                    ? "Serial number"
                    : key.toUpperCase()}
              </span>
              <Input
                name={key}
                type={key === "measured_date" ? "date" : "text"}
                min={key === "measured_date" ? "2000-01-01" : undefined}
                max={key === "measured_date" ? "2100-12-31" : undefined}
                maxLength={key === "serial_no" ? 64 : undefined}
                value={values[key]}
                onChange={(event) => setValues({ ...values, [key]: event.target.value })}
              />
              <span className="mt-1 block break-all text-xs text-muted-foreground">
                Current: {row[key] ?? "Not recorded"}
                {key === "b" ? " - Clear to remove B" : ""}
              </span>
            </label>
          ))}
        </div>
        <ReasonPresets
          label="Reason for correction"
          ariaLabel="Reason for correction"
          value={reason}
          onChange={setReason}
          presets={CORRECT_REASON_PRESETS}
        />
        {validation && (
          <p role="alert" className="text-sm text-destructive">
            {validation}
          </p>
        )}
        <div className="flex flex-wrap gap-3">
          <Button type="submit">
            {correction.isPending ? "Creating correction..." : "Create correction"}
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel correction
          </Button>
        </div>
      </fieldset>
      {correction.isError && <ApiErrorState error={correction.error} />}
    </form>
  );
}
