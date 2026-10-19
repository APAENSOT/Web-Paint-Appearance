export type PlantLens =
  "data" | "overview" | "detail" | "comparison" | "analysis" | "standard" | "model";

export const DISPLAY_LENSES = [
  { id: "overview", name: "Monthly Overview" },
  { id: "detail", name: "Monthly Detail" },
  { id: "comparison", name: "Comparison" },
  { id: "analysis", name: "Analysis & Report" },
] as const satisfies ReadonlyArray<{ id: PlantLens; name: string }>;

export const SETTING_LENSES = [
  { id: "data", name: "Data" },
  { id: "standard", name: "Standard" },
  { id: "model", name: "Model Detail" },
] as const satisfies ReadonlyArray<{ id: PlantLens; name: string }>;

export const LENS_PLACEHOLDER: Record<PlantLens, { title: string; reason: string }> = {
  data: {
    title: "Data",
    reason: "Measurement browsing, filters and corrections are parked for this visual walkthrough.",
  },
  overview: {
    title: "Monthly Overview",
    reason: "Plant-month CF boxplots, one Horizontal chart then one Vertical chart per model.",
  },
  detail: {
    title: "Monthly Detail",
    reason:
      "Model and colour summaries are unavailable until their data and grading rules are approved.",
  },
  comparison: {
    title: "Comparison",
    reason:
      "Side-by-side model comparison is unavailable. Comparison data will be connected in a later phase.",
  },
  analysis: {
    title: "Analysis & Report",
    reason: "Plant trends and reports are parked for this visual walkthrough.",
  },
  standard: {
    title: "Standard",
    reason:
      "Plant-scoped Color Family and Model under Setting → Standard. Thresholds are Standard Horizontal, Minimum Horizontal, Standard Vertical, and Minimum Vertical.",
  },
  model: {
    title: "Model Detail",
    reason: "Model detail is unavailable. Model views remain reserved for a later phase.",
  },
};

export const UNAVAILABLE_BAY_REASON =
  "Unavailable until a graded or feed-completeness API exists. No rate is shown.";

export const panelChrome = {
  background: "linear-gradient(180deg, var(--primary-soft) 0%, var(--color-panel) 30%)",
  boxShadow: "inset 0 2px 0 var(--color-primary), var(--shadow-panel)",
} as const;

export const identityChrome = {
  background: "linear-gradient(135deg, var(--primary-soft) 0%, var(--panel-raised) 70%)",
  boxShadow: "inset 0 2px 0 var(--color-primary)",
} as const;
