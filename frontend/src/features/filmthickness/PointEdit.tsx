/**
 * RO17: the per-point pieces both Point Check sections draw.
 *
 * * `PointName` -- the plant's word first, the code beside it (D-RO17-1);
 * * `PointRename` -- a new label row, never an edit of the code (D-RO17-6);
 * * `PointRestore` -- clears a retired point's retire columns (D-RO17-9).
 *
 * Both writes keep the two-step shape Retire has: the button opens the form,
 * the form is where the reason is typed. A refusal (a clash, a held walk
 * number) is the server's sentence, shown as it is.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { PointDomain } from "@/api/client";
import { api } from "@/api/queries";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { POINT_EDIT_COPY, pointName, refreshPointWrite, refreshReplayed } from "./point-edit";

const testId = (code: string) => code.replace(/\s+/g, "-");

export function PointName({ label, code }: { label?: string | null; code: string }) {
  const name = pointName(label, code);
  return (
    <>
      <span data-point-label={code}>{name.word}</span>
      {name.code && (
        <span className="ml-2 font-mono text-[0.7rem] font-normal text-muted-foreground">
          code {name.code}
        </span>
      )}
    </>
  );
}

export function PointRename({
  plant,
  domain,
  model,
  code,
  label,
  disabled,
}: {
  plant: string;
  domain: PointDomain;
  model: string;
  code: string;
  label: string;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [word, setWord] = useState(label);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const close = () => {
    setAsking(false);
    setWord(label);
    setReason("");
  };
  const rename = useMutation({
    mutationFn: () =>
      api().renamePoint(plant, domain, model, {
        code,
        label: word.trim(),
        reason: reason.trim(),
      }),
    retry: false,
    onSuccess: async () => {
      close();
      await refreshPointWrite(client, plant, domain, model);
    },
  });
  const id = `${domain}-${testId(code)}`;

  if (!asking)
    return (
      <Button
        variant="outline"
        className="min-h-11"
        data-testid={`point-rename-${id}`}
        disabled={disabled}
        onClick={() => {
          setWord(label);
          setAsking(true);
        }}
      >
        {POINT_EDIT_COPY.rename}
      </Button>
    );
  return (
    <div
      className="min-w-56 space-y-2 border border-border p-2"
      data-testid={`point-rename-form-${id}`}
    >
      <label className="block text-xs font-medium" htmlFor={`rename-word-${id}`}>
        {POINT_EDIT_COPY.renameLabel}
        <Input
          id={`rename-word-${id}`}
          data-testid={`point-rename-label-${id}`}
          className="mt-1 min-h-11"
          value={word}
          maxLength={64}
          disabled={rename.isPending}
          onChange={(event) => setWord(event.target.value)}
        />
      </label>
      <p className="text-xs text-muted-foreground">{POINT_EDIT_COPY.renameHint}</p>
      <label className="block text-xs font-medium" htmlFor={`rename-why-${id}`}>
        {POINT_EDIT_COPY.renameReason}
        <Input
          id={`rename-why-${id}`}
          data-testid={`point-rename-reason-${id}`}
          className="mt-1 min-h-11"
          value={reason}
          disabled={rename.isPending}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <p className="text-xs text-muted-foreground">{POINT_EDIT_COPY.reasonHint}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          data-testid={`point-rename-submit-${id}`}
          disabled={
            !word.trim() || word.trim() === label || reason.trim().length < 3 || rename.isPending
          }
          onClick={() => rename.mutate()}
        >
          {POINT_EDIT_COPY.renameSubmit}
        </Button>
        <Button variant="outline" className="min-h-11" disabled={rename.isPending} onClick={close}>
          {POINT_EDIT_COPY.cancel}
        </Button>
      </div>
      {rename.isError && <ApiErrorState error={rename.error} />}
    </div>
  );
}

export function PointRestore({
  plant,
  domain,
  model,
  code,
}: {
  plant: string;
  domain: PointDomain;
  model: string;
  code: string;
}) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const close = () => {
    setAsking(false);
    setReason("");
  };
  const restore = useMutation({
    mutationFn: (): Promise<{ operator_message: string; replayed_load_ids?: number[] }> =>
      domain === "wavescan"
        ? api().restoreWsPoint(plant, model, { zone_code: code, reason: reason.trim() })
        : api().restoreFilmPoint(plant, model, { point_code: code, reason: reason.trim() }),
    retry: false,
    onSuccess: async (result) => {
      close();
      await Promise.all([
        refreshPointWrite(client, plant, domain, model),
        refreshReplayed(client, result.replayed_load_ids),
      ]);
    },
  });
  const id = `${domain}-${testId(code)}`;

  if (!asking)
    return (
      <Button
        variant="outline"
        className="mt-2 min-h-11"
        data-testid={`point-restore-${id}`}
        onClick={() => setAsking(true)}
      >
        {POINT_EDIT_COPY.restore}
      </Button>
    );
  return (
    <div
      className="mt-2 max-w-md space-y-2 border border-primary bg-[var(--primary-soft)] p-2 text-foreground"
      role="alert"
      data-testid={`point-restore-confirm-${id}`}
    >
      <p className="text-xs font-medium">{POINT_EDIT_COPY.restoreWarning}</p>
      <label className="block text-xs font-medium" htmlFor={`restore-why-${id}`}>
        {POINT_EDIT_COPY.restoreReason}
        <Input
          id={`restore-why-${id}`}
          data-testid={`point-restore-reason-${id}`}
          className="mt-1 min-h-11"
          value={reason}
          disabled={restore.isPending}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          data-testid={`point-restore-submit-${id}`}
          disabled={reason.trim().length < 3 || restore.isPending}
          onClick={() => restore.mutate()}
        >
          {POINT_EDIT_COPY.restoreSubmit}
        </Button>
        <Button variant="outline" className="min-h-11" disabled={restore.isPending} onClick={close}>
          {POINT_EDIT_COPY.cancel}
        </Button>
      </div>
      {restore.isError && <ApiErrorState error={restore.error} />}
    </div>
  );
}
