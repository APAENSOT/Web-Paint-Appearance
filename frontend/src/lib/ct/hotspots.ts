import type { Risk } from "./data";

/**
 * Hotspot demo data for the colour dashboard 3D stage.
 *
 * Concept: each paint-colour record (e.g. Ranger / Ignite Orange) is measured
 * at fixed body points. The 3D model shows clickable hotspots; clicking one
 * (or picking it from the right-hand list) drives the left detail panel.
 *
 * Function note: positions are in model space (Kenney pickup, z = length axis,
 * y up). Swap HOTSPOTS for real per-point feed data when the backend lands.
 */

export interface Hotspot {
  id: string;
  label: string;
  /** [x, y, z] on the model */
  position: [number, number, number];
  waveScan: number;
  filmThickness: number;
  pct: number;
  delta: number;
  status: Risk;
}

export const HOTSPOTS: Hotspot[] = [
  {
    id: "hood",
    label: "Hood",
    position: [0, 1.0, -1.05],
    waveScan: 96.8,
    filmThickness: 97.2,
    pct: 97.0,
    delta: 1.4,
    status: "nominal",
  },
  {
    id: "roof",
    label: "Roof",
    position: [0, 1.25, -0.2],
    waveScan: 95.9,
    filmThickness: 96.1,
    pct: 96.0,
    delta: 0.6,
    status: "nominal",
  },
  {
    id: "front-door",
    label: "Front Door",
    position: [0.8, 0.72, -0.45],
    waveScan: 91.2,
    filmThickness: 89.4,
    pct: 90.3,
    delta: -2.1,
    status: "caution",
  },
  {
    id: "rear-door",
    label: "Rear Door",
    position: [0.8, 0.72, 0.15],
    waveScan: 93.5,
    filmThickness: 92.8,
    pct: 93.1,
    delta: 0.9,
    status: "nominal",
  },
  {
    id: "bed-side",
    label: "Bed Side",
    position: [0.8, 0.72, 0.9],
    waveScan: 84.6,
    filmThickness: 82.1,
    pct: 83.4,
    delta: -5.8,
    status: "critical",
  },
  {
    id: "tailgate",
    label: "Tailgate",
    position: [0, 0.68, 1.52],
    waveScan: 94.1,
    filmThickness: 95.0,
    pct: 94.5,
    delta: 2.3,
    status: "nominal",
  },
];

/** Per-colour summary shown on the right-hand dashboard cards (demo). */
export interface ColourSummary {
  modelId: string;
  metric: string;
  color: string;
  accent: string;
  pct: number;
  delta: number;
  uploads: number;
}

export const COLOUR_SUMMARIES: ColourSummary[] = [
  {
    modelId: "ranger-ignite-orange",
    metric: "Wave Scan",
    color: "Ignite Orange",
    accent: "#e4601c",
    pct: 96.4,
    delta: 10,
    uploads: 24,
  },
  {
    modelId: "ranger-arctic-white",
    metric: "Film Thickness",
    color: "Arctic White",
    accent: "#7d9dbd",
    pct: 88.1,
    delta: -4.2,
    uploads: 17,
  },
];

export const DEFAULT_SUMMARY: ColourSummary = COLOUR_SUMMARIES[0];

export const STATUS_LABEL: Record<Risk, string> = {
  nominal: "UPDATE",
  caution: "LATE",
  critical: "MISSING",
};

export const STATUS_COLOR: Record<Risk, string> = {
  nominal: "var(--nominal)",
  caution: "var(--caution)",
  critical: "var(--critical)",
};

/**
 * Boxplot demo data for the two right-hand dashboard frames.
 *
 * Concept: paint engineers split body panels into a HORIZONTAL zone
 * (hood, roof, bed floor — surfaces facing up, oven-cure behaves
 * differently) and a VERTICAL zone (doors, bed sides, tailgate). Each box
 * is this month's film-thickness distribution at that point.
 *
 * Function note: five-number summary (min / q1 / median / q3 / max) in %
 * of spec. `SPEC_BAND` is the acceptable window shaded behind the boxes.
 * Swap for live per-month distributions when the backend lands.
 */
export interface BoxSeries {
  id: string;
  label: string;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  status: Risk;
}

/** Acceptable film-thickness window, drawn as a shaded band (demo). */
export const SPEC_BAND = { low: 90, high: 98 };

export const BOXPLOT_HORIZONTAL: BoxSeries[] = [
  {
    id: "hood",
    label: "Hood",
    min: 93.2,
    q1: 95.4,
    median: 97.2,
    q3: 98.5,
    max: 99.6,
    status: "nominal",
  },
  {
    id: "roof",
    label: "Roof",
    min: 92.5,
    q1: 94.6,
    median: 96.1,
    q3: 97.4,
    max: 98.8,
    status: "nominal",
  },
  {
    id: "bed-floor",
    label: "Bed Floor",
    min: 89.8,
    q1: 92.2,
    median: 94.0,
    q3: 95.6,
    max: 97.1,
    status: "nominal",
  },
];

export const BOXPLOT_VERTICAL: BoxSeries[] = [
  {
    id: "front-door",
    label: "Front Door",
    min: 84.1,
    q1: 87.0,
    median: 89.4,
    q3: 91.2,
    max: 93.5,
    status: "caution",
  },
  {
    id: "rear-door",
    label: "Rear Door",
    min: 88.6,
    q1: 91.0,
    median: 92.8,
    q3: 94.2,
    max: 95.9,
    status: "nominal",
  },
  {
    id: "bed-side",
    label: "Bed Side",
    min: 76.4,
    q1: 79.3,
    median: 82.1,
    q3: 84.6,
    max: 87.0,
    status: "critical",
  },
  {
    id: "tailgate",
    label: "Tailgate",
    min: 91.2,
    q1: 93.4,
    median: 95.0,
    q3: 96.3,
    max: 97.8,
    status: "nominal",
  },
];
