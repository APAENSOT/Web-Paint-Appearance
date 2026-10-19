import { validateDateRange } from "./date-range";
import type { PreviewQuery } from "./client";

// A whitelist keeps measurement pagination and grading concepts out of preview requests.
export function buildPreviewQuery(input: PreviewQuery): PreviewQuery {
  const query: PreviewQuery = {};
  if (input.dimension) query.dimension = input.dimension;
  for (const key of ["plant", "model", "color", "checkzone", "date_from", "date_to"] as const) {
    const value = input[key];
    if (value) query[key] = value;
  }
  validateDateRange(query);
  return query;
}
