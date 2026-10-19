/** Display wording only: the API's WARNING status and its grading stay unchanged. */
export const filmWarningLabel = (layer?: string | null) =>
  layer?.toUpperCase() === "CLEAR" ? "For Improvement" : "Acceptable";
