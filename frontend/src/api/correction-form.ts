import { z } from "zod";
import type { components } from "./types";

type Correction = components["schemas"]["CorrectionCreate"];
type Measurement = components["schemas"]["MeasurementOut"];
export const measureFields = [
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
] as const satisfies readonly (keyof Correction)[];
export const correctionFields = [
  "measured_date",
  "serial_no",
  ...measureFields,
] as const satisfies readonly (keyof Correction)[];
export type CorrectionValues = Record<(typeof correctionFields)[number], string>;

// Compare exact decimals without converting to binary floating point, including at bounds.
function canonicalDecimal(value: string) {
  const [integer, fraction = ""] = value.replace(/^[+-]/, "").split(".");
  const whole = integer.replace(/^0+/, "") || "0";
  const decimals = fraction.replace(/0+$/, "");
  const sign = value.startsWith("-") && (whole !== "0" || decimals) ? "-" : "";
  return sign + whole + (decimals ? `.${decimals}` : "");
}
const decimal = (negative: boolean, capped: boolean) =>
  z
    .string()
    .trim()
    .regex(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/, "Enter a decimal value (no exponent).")
    .refine(
      (value) => {
        const normalized = canonicalDecimal(value);
        if (!negative && normalized.startsWith("-")) return false;
        if (!capped) return true;
        const [whole, fraction] = normalized.replace(/^-/, "").split(".");
        return (
          whole.length < 3 ||
          (whole.length === 3 && (whole < "100" || (whole === "100" && !fraction)))
        );
      },
      negative
        ? "Must be between -100 and 100."
        : capped
          ? "Must be between 0 and 100."
          : "Must be non-negative.",
    );

const reasonSchema = z.string().trim().min(1, "A reason is required.").max(2000);
const valuesSchema = z
  .object({
    measured_date: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/, "Enter a date.")
      .refine((value) => {
        const date = new Date(`${value}T00:00:00Z`);
        return (
          value >= "2000-01-01" &&
          value <= "2100-12-31" &&
          !Number.isNaN(date.getTime()) &&
          date.toISOString().slice(0, 10) === value
        );
      }, "Date must be valid and between 2000-01-01 and 2100-12-31.")
      .optional(),
    serial_no: z.string().trim().min(1, "Serial is required.").max(64).optional(),
    lw: decimal(false, false).optional(),
    sw: decimal(false, false).optional(),
    cf: decimal(false, true).optional(),
    doi: decimal(false, true).optional(),
    du: decimal(false, false).optional(),
    wa: decimal(false, false).optional(),
    wb: decimal(false, false).optional(),
    wc: decimal(false, false).optional(),
    wd: decimal(false, false).optional(),
    we: decimal(false, false).optional(),
    b: z.union([z.literal(""), decimal(true, true)]).optional(),
  })
  .strict();

export const supersedeSchema = z.object({ reason: reasonSchema }).strict() satisfies z.ZodType<
  components["schemas"]["SupersedeCreate"]
>;

export function correctionValues(row: Measurement): CorrectionValues {
  return Object.fromEntries(
    correctionFields.map((key) => [key, row[key] ?? ""]),
  ) as CorrectionValues;
}

export function buildCorrection(row: Measurement, input: unknown, reason: string): Correction {
  const raw = z.record(z.string()).parse(input);
  const changed = Object.fromEntries(
    Object.entries(raw).filter(([key, value]) => {
      const field = correctionFields.find((field) => field === key);
      // Unchanged API display values are not part of the request. Leave unknown keys
      // in the candidate so strict validation refuses them instead of silently stripping.
      return !field || value !== (row[field] ?? "");
    }),
  );
  const values = valuesSchema.parse(changed);
  const body: Correction = { reason: reasonSchema.parse(reason) };
  for (const key of correctionFields) {
    const value = values[key];
    if (value === undefined) continue;
    if (key === "measured_date" || key === "serial_no") {
      if (value !== row[key]) body[key] = value;
    } else if (key === "b" && value === "") {
      if (row.b !== null) body.b = null;
    } else if (row[key] === null || canonicalDecimal(value) !== canonicalDecimal(row[key]!)) {
      body[key] = value;
    }
  }
  if (Object.keys(body).length === 1)
    throw new Error("Change at least one value before creating a correction.");
  return body;
}
