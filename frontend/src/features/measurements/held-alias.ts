import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  checkzoneAliasPayload,
  colorAliasPayload,
  filmModelPayload,
  isPlaceholder,
  modelAliasPayload,
} from "@/api/mapping-state";
import { api, meOptions, refreshPlantWorkbooks } from "@/api/queries";
import { mayCorrect, mayIngest } from "@/api/roles";
import type { components } from "@/api/types";
type HeldLabel = components["schemas"]["HeldLabelGroup"];
type DisplayGroup = HeldLabel["display_group"];
const TEACH_GROUPS = new Set<DisplayGroup>(["colour", "model", "zone", "plant_offer"]);
/** One held-label choice. `token` is only used by FILM_MODEL (optional teachable token). */
export type HeldChoice = { item: HeldLabel; name: string; token?: string | null };

export function rowKey(item: HeldLabel) {
  return `${item.reason}\u0000${item.column}\u0000${item.raw_value}\u0000${item.model_code ?? ""}`;
}

/**
 * T61 (backend T78 part D): a Film sheet held FILM_MODEL_UNRESOLVED can be given a model.
 * The Engineer proposes; nothing applies until an Admin approves and the sheet replays.
 */
export function canChooseFilmModel(item: HeldLabel, ingest: boolean, status: string) {
  return (
    ingest &&
    (status === "PENDING_REVIEW" || status === "REJECTED_TEMPLATE") &&
    item.teachable_kind === "FILM_MODEL" &&
    !!item.film_model &&
    (item.film_model.choices?.length ?? 0) > 0
  );
}

export function canTeach(item: HeldLabel, ingest: boolean, status: string) {
  if (item.teachable_kind === "FILM_MODEL") return canChooseFilmModel(item, ingest, status);
  return (
    ingest &&
    (status === "PENDING_REVIEW" ||
      status === "REJECTED_TEMPLATE" ||
      (status === "COMMITTED" &&
        (item.teachable_kind === "ALIAS_COLOR" || item.teachable_kind === "ALIAS_CHECKZONE"))) &&
    TEACH_GROUPS.has(item.display_group) &&
    (item.teachable_kind === "ALIAS_COLOR" ||
      item.teachable_kind === "ALIAS_MODEL" ||
      item.teachable_kind === "ALIAS_CHECKZONE") &&
    (item.teachable_kind !== "ALIAS_CHECKZONE" || !!item.model_code) &&
    !isPlaceholder(item.raw_value) &&
    (item.candidates?.length ?? 0) > 0
  );
}

export function heldAliasProposal(
  next: HeldChoice,
  plant: string,
  loadId: number,
  status: string,
): components["schemas"]["ProposalCreate"] {
  if (next.item.teachable_kind === "FILM_MODEL") {
    const options = next.item.film_model;
    if (!options || !options.choices?.includes(next.name))
      throw new Error("Choose one of this plant's FilmThickness models.");
    const token = next.token || null;
    if (token !== null && !options.teachable_tokens?.includes(token))
      throw new Error("Choose a spelling from this file, or this sheet only.");
    const parsed = filmModelPayload.safeParse({
      plant: options.plant_code,
      load_id: options.load_id,
      source_sheet: options.source_sheet,
      model_code: next.name,
      ...(token === null ? {} : { raw_token: token }),
    });
    if (!parsed.success) {
      throw new Error(
        parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; "),
      );
    }
    return { kind: "FILM_MODEL", load_id: options.load_id, payload: parsed.data };
  }
  if (next.item.teachable_kind === "ALIAS_COLOR") {
    const parsed = colorAliasPayload.safeParse({
      raw_value: next.item.raw_value,
      color_name: next.name,
      plant_code: plant,
    });
    if (!parsed.success) {
      throw new Error(
        parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; "),
      );
    }
    return {
      kind: "ALIAS_COLOR",
      load_id: status === "COMMITTED" ? undefined : loadId,
      payload: {
        raw_value: parsed.data.raw_value,
        color_name: parsed.data.color_name,
        plant_code: parsed.data.plant_code,
      },
    };
  }
  if (next.item.teachable_kind === "ALIAS_CHECKZONE") {
    const parsed = checkzoneAliasPayload.safeParse({
      raw_value: next.item.raw_value,
      zone_code: next.name,
      plant_code: plant,
      model_code: next.item.model_code,
    });
    if (!parsed.success) throw new Error(parsed.error.message);
    return {
      kind: "ALIAS_CHECKZONE",
      load_id: status === "COMMITTED" ? undefined : loadId,
      payload: parsed.data,
    };
  }
  const parsed = modelAliasPayload.safeParse({
    raw_value: next.item.raw_value,
    model_code: next.name,
  });
  if (!parsed.success) {
    throw new Error(
      parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; "),
    );
  }
  return {
    kind: "ALIAS_MODEL",
    load_id: loadId,
    payload: {
      raw_value: parsed.data.raw_value,
      model_code: parsed.data.model_code,
    },
  };
}

export function useHeldAlias({
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
  const client = useQueryClient();
  const identity = useQuery(meOptions);
  const ingest =
    !identity.isError &&
    mayIngest(identity.data?.principal) &&
    mayCorrect(identity.data?.principal);
  const [choice, setChoice] = useState<HeldChoice | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, Error>>({});
  const teach = useMutation({
    mutationFn: (next: HeldChoice) => {
      const allowed =
        next.item.teachable_kind === "FILM_MODEL"
          ? next.item.film_model?.choices
          : next.item.candidates;
      if (!canTeach(next.item, ingest, status) || !allowed?.includes(next.name))
        throw new Error("Choose an available catalogue name.");
      return api().propose(heldAliasProposal(next, plant, loadId, status));
    },
    retry: false,
    onSuccess: async (_result, next) => {
      setRowErrors((current) => {
        const rest = { ...current };
        delete rest[rowKey(next.item)];
        return rest;
      });
      setChoice(null);
      await client.invalidateQueries({ queryKey: ["batch", loadId] });
      await refreshPlantWorkbooks(client, plant);
      if (fileHash) await client.invalidateQueries({ queryKey: ["worksheet", plant, fileHash] });
      // A FILM_MODEL proposal waits for an Admin: show it in the sheet's proposal list.
      await client.invalidateQueries({ queryKey: ["proposals", loadId] });
    },
    onError: (error, next) => {
      setRowErrors((current) => ({
        ...current,
        [rowKey(next.item)]: error instanceof Error ? error : new Error(String(error)),
      }));
      setChoice(null);
    },
  });
  return { ingest, choice, setChoice, rowErrors, teach };
}
