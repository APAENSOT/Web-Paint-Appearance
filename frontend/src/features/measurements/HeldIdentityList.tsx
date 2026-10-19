import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { batchOptions } from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { canTeach, rowKey, useHeldAlias } from "./held-alias";
import { HeldAliasConfirmation } from "./HeldAliasConfirmation";
import { Button } from "@/components/ui/button";
import { PanelMatchDialog } from "./PanelMatchDialog";
import { disagreesWithMonth } from "./review-copy";
type HeldLabel = components["schemas"]["HeldLabelGroup"];
type DisplayGroup = HeldLabel["display_group"];

const selectClass =
  "mt-1 min-h-11 w-full rounded-[var(--radius-sm)] border border-border bg-[var(--surface-2)] px-3 text-xs";

const GROUP_HEADINGS: { group: DisplayGroup; heading: string }[] = [
  { group: "colour", heading: "Colour" },
  { group: "model", heading: "Model" },
  { group: "zone", heading: "Panel" },
  { group: "plant", heading: "Plant" },
  { group: "measure", heading: "Missing measurement" },
  { group: "empty_identity", heading: "Empty identity" },
  { group: "plant_offer", heading: "Plant list" },
  { group: "date", heading: "Date" },
  { group: "header", heading: "Header" },
  { group: "film_point", heading: "Film point" },
  { group: "film_model", heading: "Film model" },
];

export function HeldIdentityList({
  loadId,
  plant,
  status,
  fileHash,
}: {
  loadId: number;
  plant: string;
  status: string;
  fileHash?: string;
}) {
  const review = useQuery(batchOptions(loadId));
  const alias = useHeldAlias({ loadId, plant, status, fileHash });
  const { ingest, choice, setChoice, rowErrors, teach } = alias;
  // FILM_MODEL only: the optional server-derived spelling to teach, chosen before the model.
  const [filmTokens, setFilmTokens] = useState<Record<string, string>>({});
  // T86: the model whose guided panel match is open, if any.
  const [matchModel, setMatchModel] = useState<string | null>(null);

  if (review.isPending) return <LoadingState>Loading held labels...</LoadingState>;
  if (review.isError)
    return <ApiErrorState error={review.error} retry={() => void review.refetch()} />;
  const labels = review.data.held_labels;
  if (!labels?.length) return null;

  return (
    <section aria-label="Held labels" className="space-y-3">
      {GROUP_HEADINGS.map(({ group, heading }) => {
        const items = labels.filter((item) => item.display_group === group);
        if (!items.length) return null;
        return (
          <div key={group} className="space-y-2">
            <h4 className="text-sm font-semibold">{heading}</h4>
            <ul className="space-y-3">
              {items.map((item, index) => {
                const key = rowKey(item);
                const selectId = `held-catalogue-${loadId}-${group}-${index}`;
                const error = rowErrors[key];
                const teachable = canTeach(item, ingest, status);
                return (
                  <li key={key} className="space-y-2 border border-border p-3 text-xs">
                    {/* RO17-FIX (D-RO17F-5): the banner above already says RO15's sentence. */}
                    {!disagreesWithMonth(item) && (
                      <p className="text-sm">{item.operator_message}</p>
                    )}
                    {/* T86: the panel question that cannot be answered one row
                        at a time is answered as a set instead. Offered for
                        every held panel name, so two rows that look the same
                        to a reviewer behave the same. */}
                    {group === "zone" && item.model_code && ingest && (
                      <Button
                        variant="outline"
                        className="min-h-11"
                        onClick={() => setMatchModel(item.model_code ?? null)}
                      >
                        Match the panel list
                      </Button>
                    )}
                    <p>
                      {item.raw_value ? `${item.raw_value} / ` : null}
                      Count {item.count}
                    </p>
                    {teachable && item.teachable_kind === "FILM_MODEL" && item.film_model && (
                      <div className="space-y-2">
                        <p className="text-muted-foreground">{item.film_model.detail}</p>
                        {(item.film_model.teachable_tokens?.length ?? 0) > 0 ? (
                          <label className="block text-xs" htmlFor={`${selectId}-token`}>
                            Also teach this spelling for future files (optional)
                            <select
                              id={`${selectId}-token`}
                              className={selectClass}
                              value={filmTokens[key] ?? ""}
                              disabled={teach.isPending}
                              onChange={(event) =>
                                setFilmTokens((current) => ({
                                  ...current,
                                  [key]: event.target.value,
                                }))
                              }
                            >
                              <option value="">This sheet only</option>
                              {item.film_model.teachable_tokens?.map((token) => (
                                <option key={token} value={token}>
                                  {token}
                                </option>
                              ))}
                            </select>
                          </label>
                        ) : (
                          <p className="text-muted-foreground">
                            The file and tab name point to different models, so this choice applies
                            to this sheet only.
                          </p>
                        )}
                        <label className="block text-xs" htmlFor={selectId}>
                          FilmThickness model for {item.film_model.source_sheet}
                          <select
                            id={selectId}
                            className={selectClass}
                            value={choice?.item === item ? choice.name : ""}
                            disabled={teach.isPending}
                            onChange={(event) => {
                              const name = event.target.value;
                              if (!name || teach.isPending) return;
                              setChoice({ item, name, token: filmTokens[key] || null });
                            }}
                          >
                            <option value="">Pick model</option>
                            {item.film_model.choices?.map((model) => (
                              <option key={model} value={model}>
                                {item.film_model?.candidates?.includes(model)
                                  ? `${model} (named in the file)`
                                  : model}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                    )}
                    {/* T89 (D-89-9): a decision somebody already made arrives
                        pre-selected and says where it came from. Confirming it
                        is still a person's click. */}
                    {teachable && item.carried_over && (
                      <div className="space-y-2" data-carried={item.carried_over.kind}>
                        <p role="status">
                          Carried over from an earlier decision: {item.carried_over.reason}
                        </p>
                        <Button
                          variant="outline"
                          className="min-h-11"
                          disabled={teach.isPending}
                          onClick={() =>
                            setChoice({
                              item,
                              name: item.carried_over?.zone_code ?? "",
                            })
                          }
                        >
                          Confirm {item.carried_over.zone_code} for {item.raw_value}
                        </Button>
                      </div>
                    )}
                    {teachable && item.teachable_kind !== "FILM_MODEL" && (
                      <label className="block text-xs" htmlFor={selectId}>
                        {group === "zone"
                          ? `Existing panel for ${item.model_code}`
                          : group === "model"
                            ? "Existing plant model"
                            : "Official catalogue colour name"}
                        <select
                          id={selectId}
                          className={selectClass}
                          value={
                            choice?.item === item
                              ? choice.name
                              : (item.carried_over?.zone_code ?? "")
                          }
                          disabled={teach.isPending}
                          onChange={(event) => {
                            const name = event.target.value;
                            if (!name || teach.isPending) return;
                            setChoice({ item, name });
                          }}
                        >
                          <option value="">
                            Pick{" "}
                            {group === "zone"
                              ? "panel"
                              : group === "model"
                                ? "model"
                                : "catalogue colour"}
                          </option>
                          {item.candidates?.map((candidate) => (
                            <option key={candidate} value={candidate}>
                              {candidate}
                            </option>
                          ))}
                          {/* T89 (D-89-6): panels this file already used --
                              shown last, disabled, each labelled with the
                              spelling that took it. The match screen's
                              picker shows exactly the same thing, because
                              both lists come from one backend call. */}
                          {item.blocked_candidates?.map((panel) => (
                            <option
                              key={`taken-${panel.zone_code}`}
                              value={panel.zone_code}
                              disabled
                            >
                              {panel.zone_code} - {panel.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {error && <ApiErrorState error={error} />}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      {teach.isSuccess && teach.variables?.item.teachable_kind === "FILM_MODEL" && (
        <p role="status" className="text-sm">
          Proposed {teach.variables.name} for {teach.variables.item.film_model?.source_sheet}. An
          Admin approves it under the sheet&apos;s mapping proposals; the sheet is then read again.
        </p>
      )}
      <HeldAliasConfirmation alias={alias} plant={plant} />
      {matchModel && (
        <PanelMatchDialog
          loadId={loadId}
          modelCode={matchModel}
          plant={plant}
          fileHash={fileHash}
          onClose={() => setMatchModel(null)}
        />
      )}
    </section>
  );
}
