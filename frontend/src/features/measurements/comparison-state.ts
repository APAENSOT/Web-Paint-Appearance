import type { components } from "@/api/types";
export type Candidate = components["schemas"]["ComparisonCandidate"];
export type Points = components["schemas"]["ComparisonPointsOut"];
export type Domain = Candidate["domain"];
export type Metric = Points["metric"];
export const metrics: Record<Domain, Metric[]> = {
  WAVESCAN: ["lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b"],
  FILMTHICKNESS: ["ecoat", "primer", "base", "clear"],
};
export interface ComparisonState {
  mode: "months" | "vehicles";
  domain: Domain;
  model: string | null;
  months: string[] | null;
  colors: string[];
  periods: string[];
  metric: Metric;
  search: string;
  offset: number;
  selected: Candidate[];
  columnPage: number;
  focused: string | null;
}
export const initialComparison = (): ComparisonState => ({
  mode: "months",
  domain: "WAVESCAN",
  model: null,
  months: null,
  colors: [],
  periods: [],
  metric: "cf",
  search: "",
  offset: 0,
  selected: [],
  columnPage: 0,
  focused: null,
});
export type ComparisonAction =
  | { type: "mode"; mode: ComparisonState["mode"] }
  | { type: "domain"; domain: Domain }
  | { type: "model"; model: string }
  | { type: "defaults"; months: string[] }
  | { type: "clear" }
  | { type: "filter"; key: "months" | "colors" | "periods"; value: string[] }
  | { type: "search"; value: string }
  | { type: "offset"; offset: number }
  | { type: "metric"; metric: Metric }
  | { type: "add"; vehicle: Candidate }
  | { type: "remove"; id: string }
  | { type: "move"; index: number; direction: -1 | 1 }
  | { type: "page"; page: number }
  | { type: "focus"; code: string | null };
export function comparisonReducer(s: ComparisonState, a: ComparisonAction): ComparisonState {
  switch (a.type) {
    case "mode":
      return { ...s, mode: a.mode };
    case "clear":
      return { ...initialComparison(), mode: s.mode };
    case "domain":
      return {
        ...initialComparison(),
        mode: s.mode,
        domain: a.domain,
        metric: a.domain === "WAVESCAN" ? "cf" : "ecoat",
      };
    case "model":
      return {
        ...s,
        model: a.model,
        colors: [],
        periods: [],
        search: "",
        offset: 0,
        selected: [],
        columnPage: 0,
        focused: null,
      };
    case "defaults":
      return s.months === null ? { ...s, months: a.months } : s;
    case "filter":
      return {
        ...s,
        [a.key]: a.value,
        offset: 0,
        ...(a.key === "months"
          ? { periods: s.periods.filter((p) => a.value.includes(p.slice(0, 7))) }
          : {}),
      };
    case "search":
      return { ...s, search: a.value, offset: 0 };
    case "offset":
      return { ...s, offset: a.offset };
    case "metric":
      return { ...s, metric: a.metric, focused: null };
    case "add":
      return s.selected.some((v) => v.vehicle_id === a.vehicle.vehicle_id)
        ? s
        : { ...s, selected: [...s.selected, a.vehicle] };
    case "remove": {
      const selected = s.selected.filter((v) => v.vehicle_id !== a.id);
      return {
        ...s,
        selected,
        columnPage: Math.min(s.columnPage, Math.max(0, Math.ceil(selected.length / 8) - 1)),
        focused: null,
      };
    }
    case "move": {
      const selected = [...s.selected];
      const to = a.index + a.direction;
      if (to < 0 || to >= selected.length) return s;
      [selected[a.index], selected[to]] = [selected[to], selected[a.index]];
      return { ...s, selected, focused: null };
    }
    case "page":
      return {
        ...s,
        columnPage: Math.max(
          0,
          Math.min(a.page, Math.max(0, Math.ceil(s.selected.length / 8) - 1)),
        ),
        focused: null,
      };
    case "focus":
      return { ...s, focused: a.code };
  }
}
export const visibleVehicles = (s: ComparisonState) =>
  s.selected.slice(s.columnPage * 8, s.columnPage * 8 + 8);
export const vehicleLabel = (v: Candidate) => v.serial_no?.trim() || "Serial not recorded";
