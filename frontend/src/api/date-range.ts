import type { MeasurementQuery } from "./client";

export function validateDateRange(range: Pick<MeasurementQuery, "date_from" | "date_to">) {
  for (const value of [range.date_from, range.date_to]) {
    if (!value) continue;
    const date = new Date(`${value}T00:00:00Z`);
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
      !Number.isFinite(date.getTime()) ||
      date.toISOString().slice(0, 10) !== value ||
      value < "2000-01-01" ||
      value > "2100-12-31"
    )
      throw new Error("Choose a valid date between 2000-01-01 and 2100-12-31.");
  }
  if (range.date_from && range.date_to && range.date_from > range.date_to)
    throw new Error("From date must be on or before To date.");
}
