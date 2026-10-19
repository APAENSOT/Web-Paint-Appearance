import type { MeasurementQuery } from "./client";
import { validateDateRange } from "./date-range";

export type MeasurementListFilters = Pick<
  MeasurementQuery,
  "model" | "color" | "checkzone" | "date_from" | "date_to" | "load_id"
>;

export function buildMeasurementQuery(
  plant: string,
  offset: number,
  filters: MeasurementListFilters = {},
): MeasurementQuery {
  if (!plant.trim()) throw new Error("A plant route is required.");
  const query: MeasurementQuery = { plant, offset, limit: 50 };
  for (const key of ["model", "color", "checkzone", "date_from", "date_to"] as const) {
    const value = filters[key];
    if (value) query[key] = value;
  }
  if (filters.load_id !== undefined && filters.load_id !== null) query.load_id = filters.load_id;
  validateDateRange(query);
  return query;
}
