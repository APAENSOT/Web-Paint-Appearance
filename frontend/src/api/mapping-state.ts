import { z } from "zod";
import type { components } from "./types";

// backend/app/domain/reader.py STAGED_FIELDS (including MEASURE_ALL).
export const STAGED_FIELDS = [
  "date",
  "month",
  "year",
  "plant",
  "model",
  "checkzone",
  "color",
  "tolerance_group",
  "paintline",
  "serial_no",
  "lw",
  "sw",
  "cf",
  "doi",
  "du",
  "wa",
  "wb",
  "wc",
  "wd",
  "we",
  "b",
] as const;

// Intentional free-object exception: exact keys/limits from
// backend/app/schemas/mappings.py ColumnPayload / ModelAliasPayload.
const note = z.string().max(2000).nullable().optional();
export const columnPayload = z
  .object({
    raw_header: z
      .string()
      .min(1)
      .max(200)
      .refine((value) => value.replaceAll("_", " ").trim().length > 0, "Enter a header."),
    logical_field: z.enum(STAGED_FIELDS),
    note,
  })
  .strict();
export const modelAliasPayload = z
  .object({
    raw_value: z.string().min(1).max(200),
    model_code: z.string().min(1).max(64),
    suggested_model: z.string().max(64).nullable().optional(),
    note,
  })
  .strict();
// backend/app/schemas/mappings.py FilmModelPayload (T78 / T61). model_code must be one of
// the held label's film_model.choices and raw_token one of its teachable_tokens; the
// server re-validates both, so the client never sends free text.
export const filmModelPayload = z
  .object({
    plant: z.string().min(1).max(16),
    load_id: z.number().int().min(1),
    source_sheet: z.string().min(1).max(200),
    model_code: z.string().min(1).max(64),
    raw_token: z.string().min(1).max(64).nullable().optional(),
    note,
  })
  .strict();
export const colorAliasPayload = z
  .object({
    raw_value: z.string().min(1).max(200),
    color_name: z.string().min(1).max(64),
    plant_code: z.string().min(1).max(16),
    note,
  })
  .strict();
export const checkzoneAliasPayload = z
  .object({
    raw_value: z.string().min(1).max(200),
    zone_code: z.string().min(1).max(64),
    plant_code: z.string().min(1).max(16),
    model_code: z.string().min(1).max(64),
    note,
  })
  .strict();

// backend/app/schemas/mappings.py ZonePanelMatchPayload (T86). It is a ZONE
// payload, told apart from T29's owner-proved pack by carrying `matches`
// where that one carries `mappings`. No proof hash: a match set proves
// nothing and mints nothing -- it records N pairs a person confirmed, who
// decided them, and the block the owner says they supersede.
export const panelMatchRow = z
  .object({
    raw_zone_text: z.string().min(1).max(200),
    raw_position: z.number().int().min(1).max(40).nullable().optional(),
    zone_code: z.string().min(1).max(64),
  })
  .strict();
export const panelRetirePayload = z
  .object({
    zone_codes: z.array(z.string().min(1).max(64)).min(1),
    reason: z.string().min(1).max(2000),
  })
  .strict();
/**
 * T90 (D-90-3). One pair of a confirmed walk, with how specific its name is.
 *
 * `specificity` comes from the server's `walk.rows[].specificity` and is
 * never decided here: a ROUGH name shares its core with another name of the
 * same sheet, so its NUMBER is what identifies it, and the backend refuses
 * a `matches` row whose walk entry says rough. The rough half of a walk is
 * recorded on the batch (D-90-11) and nowhere else.
 */
const walkPairRow = z
  .object({
    raw_zone_text: z.string().min(1).max(200),
    zone_code: z.string().min(1).max(64),
    specificity: z.enum(["rough", "specific"]),
    rule: z.enum(["group_ordinal", "walk_number", "none"]).optional(),
    attention: z.enum(["yellow", "red"]).optional(),
  })
  .strict();

/** T90 (D-90-11): the whole walk a person confirmed, recorded on the batch. */
export const walkConfirmation = z
  .object({
    fingerprint: z.string().min(1).max(2000),
    pairs: z.array(walkPairRow).min(1),
  })
  .strict();

export const panelMatchPayload = z
  .object({
    plant_code: z.string().min(1).max(16),
    model_code: z.string().min(1).max(64),
    load_id: z.number().int().min(1),
    // T90 (D-90-3): may be empty when `walk` carries the confirmation
    // instead -- a walk every name of which is rough has no permanent
    // alias to write. A set that records neither is refused.
    matches: z.array(panelMatchRow),
    retire: panelRetirePayload.nullable().optional(),
    walk: walkConfirmation.nullable().optional(),
    decided_by: z.string().min(1).max(200),
    method: z.string().min(1).max(2000),
    note: z.string().min(1).max(2000),
  })
  .strict();

export function isPlaceholder(value: string) {
  return ["", "(none)", "none", "n/a", "na", "nan", "null", "-", "unknown"].includes(
    value.trim().toLowerCase(),
  );
}

export function isDiagnostic(proposal: components["schemas"]["ProposalOut"]) {
  return "missing_required" in proposal.payload || "unrecognised_headers" in proposal.payload;
}

export function isApplicable(proposal: components["schemas"]["ProposalOut"]) {
  if (proposal.status !== "PROPOSED" || isDiagnostic(proposal)) return false;
  if (proposal.kind === "COLUMN") return columnPayload.safeParse(proposal.payload).success;
  if (proposal.kind === "ALIAS_MODEL") {
    const parsed = modelAliasPayload.safeParse(proposal.payload);
    return parsed.success && !isPlaceholder(parsed.data.raw_value);
  }
  if (proposal.kind === "ALIAS_COLOR") {
    const parsed = colorAliasPayload.safeParse(proposal.payload);
    return parsed.success && !isPlaceholder(parsed.data.raw_value);
  }
  if (proposal.kind === "ALIAS_CHECKZONE") {
    const parsed = checkzoneAliasPayload.safeParse(proposal.payload);
    return parsed.success && !isPlaceholder(parsed.data.raw_value);
  }
  // T86: a ZONE payload carrying `matches` is a guided panel-match set; one
  // carrying `mappings` is T29's owner-proved pack, which this list has
  // never claimed to validate.
  if (proposal.kind === "ZONE" && "matches" in proposal.payload)
    return panelMatchPayload.safeParse(proposal.payload).success;
  if (proposal.kind === "FILM_MODEL") return filmModelPayload.safeParse(proposal.payload).success;
  return false;
}

/** Plain-language name of a proposal kind, shared by every proposal list. */
export function proposalKindLabel(kind: components["schemas"]["ProposalOut"]["kind"]) {
  switch (kind) {
    case "COLUMN":
      return "Column mapping";
    case "ALIAS_MODEL":
      return "Model alias";
    case "ALIAS_COLOR":
      return "Colour alias";
    case "ALIAS_CHECKZONE":
      return "Panel alias";
    case "ZONE":
      return "Panel set";
    case "FILM_MODEL":
      return "Film model choice";
    default:
      return kind;
  }
}
