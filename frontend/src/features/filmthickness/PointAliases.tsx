/**
 * RO17 (D-RO17-13): every other spelling that reads as a point of one plant x
 * model x domain -- plant maps, taught answers, location maps, a point's
 * earlier names, and the Wave Scan spellings every plant shares.
 *
 * Engineers read it. An Admin may retire a spelling (append-only: a retire
 * column, a reason, an audit row). A shared spelling is marked as such and
 * has no control here. The server refuses a retire that would leave stored
 * readings with a spelling that no longer reads, and says how many; that
 * sentence is shown as it is. Repoint is retire, then teach again where the
 * spelling is taught.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { PointDomain } from "@/api/client";
import { api, pointAliasesOptions } from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PointName } from "./PointEdit";
import { ALIAS_KIND, POINT_EDIT_COPY, refreshPointWrite, type PointAlias } from "./point-edit";

export function PointAliases({
  plant,
  domain,
  model,
  admin,
}: {
  plant: string;
  domain: PointDomain;
  model: string;
  admin: boolean;
}) {
  const aliases = useQuery(pointAliasesOptions(plant, domain, model));
  const items = aliases.data?.items ?? [];
  return (
    <section
      className="mt-6"
      aria-label={`${model} ${POINT_EDIT_COPY.aliasesHeading}`}
      data-testid={`point-aliases-${domain}`}
    >
      <h4 className="text-sm font-bold">
        {POINT_EDIT_COPY.aliasesHeading}
        {items.length > 0 && (
          <span className="ml-2 font-normal text-muted-foreground">{items.length}</span>
        )}
      </h4>
      <p className="mt-1 text-xs text-muted-foreground">{POINT_EDIT_COPY.aliasesExplain}</p>
      {aliases.isPending ? (
        <LoadingState>Loading spellings...</LoadingState>
      ) : aliases.isError ? (
        <ApiErrorState error={aliases.error} retry={() => void aliases.refetch()} />
      ) : items.length === 0 ? (
        <p className="mt-2 text-xs" data-testid={`point-aliases-none-${domain}`}>
          {POINT_EDIT_COPY.aliasesNone}
        </p>
      ) : (
        <div className="mt-2 overflow-x-auto rounded-md border border-border">
          <table className="w-full min-w-[640px] text-left text-xs">
            <caption className="sr-only">{model} spellings and the point each one reads as</caption>
            <thead className="bg-[var(--surface-2)] text-muted-foreground">
              <tr>
                {["Spelling", "Kind", "Reads as", "State", "Stored readings", "Retire"].map(
                  (head) => (
                    <th key={head} scope="col" className="px-3 py-2 font-medium">
                      {head}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={`${item.kind}:${item.alias_id}`}
                  className={`border-t border-border ${item.live ? "" : "opacity-70"}`}
                  data-point-alias={`${item.kind}:${item.alias_id}`}
                >
                  <th scope="row" className="px-3 py-2 font-mono font-medium">
                    {item.spelling}
                  </th>
                  <td className="px-3 py-2">
                    {ALIAS_KIND[item.kind]}
                    {item.shared && (
                      <span
                        title={POINT_EDIT_COPY.sharedTitle}
                        data-testid={`point-alias-shared-${item.alias_id}`}
                        className="ml-2 rounded-sm border border-border px-1 text-[0.7rem] text-muted-foreground"
                      >
                        {POINT_EDIT_COPY.shared}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-medium">
                    {item.not_a_point ? (
                      <span className="text-muted-foreground">-</span>
                    ) : (
                      <PointName label={item.code_label} code={item.code} />
                    )}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {item.live ? POINT_EDIT_COPY.live : POINT_EDIT_COPY.retired}
                    {item.retired_at && (
                      <span className="block">
                        {item.retired_reason ?? "-"} · {item.retired_at.slice(0, 10)}
                      </span>
                    )}
                  </td>
                  <td className="num px-3 py-2">{item.stored_facts}</td>
                  <td className="px-3 py-2">
                    {admin && item.live && item.retirable && !item.shared ? (
                      <AliasRetire plant={plant} domain={domain} model={model} item={item} />
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AliasRetire({
  plant,
  domain,
  model,
  item,
}: {
  plant: string;
  domain: PointDomain;
  model: string;
  item: PointAlias;
}) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const close = () => {
    setAsking(false);
    setReason("");
  };
  const retire = useMutation({
    mutationFn: () =>
      api().retirePointAlias(plant, domain, model, {
        kind: item.kind,
        alias_id: item.alias_id,
        reason: reason.trim(),
      }),
    retry: false,
    onSuccess: async () => {
      close();
      await refreshPointWrite(client, plant, domain, model);
    },
  });
  const id = `${item.kind}-${item.alias_id}`.replace(/\s+/g, "-");

  if (!asking)
    return (
      <Button
        variant="outline"
        className="min-h-11"
        data-testid={`point-alias-retire-${id}`}
        onClick={() => setAsking(true)}
      >
        {POINT_EDIT_COPY.aliasRetire}
      </Button>
    );
  return (
    <div
      className="min-w-56 space-y-2 border border-primary bg-[var(--primary-soft)] p-2"
      role="alert"
      data-testid={`point-alias-retire-confirm-${id}`}
    >
      <p className="text-xs font-medium">{POINT_EDIT_COPY.aliasRetireWarning}</p>
      <label className="block text-xs font-medium" htmlFor={`alias-why-${id}`}>
        {POINT_EDIT_COPY.aliasRetireReason}
        <Input
          id={`alias-why-${id}`}
          data-testid={`point-alias-retire-reason-${id}`}
          className="mt-1 min-h-11"
          value={reason}
          disabled={retire.isPending}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          data-testid={`point-alias-retire-submit-${id}`}
          disabled={reason.trim().length < 3 || retire.isPending}
          onClick={() => retire.mutate()}
        >
          {POINT_EDIT_COPY.aliasRetireSubmit}
        </Button>
        <Button variant="outline" className="min-h-11" disabled={retire.isPending} onClick={close}>
          {POINT_EDIT_COPY.cancel}
        </Button>
      </div>
      {retire.isError && <ApiErrorState error={retire.error} />}
    </div>
  );
}
