import type { components } from "@/api/types";

export type OverviewBox = components["schemas"]["OverviewBox"];
export type OverviewColorOption = components["schemas"]["OverviewColorOption"];

/** Shown when a chart is wider than its panel (Film overview; Wave Scan when it overflows). */
export const SCROLL_HINT = "Scroll horizontally to see all colours.";

export function calendarYearMonth(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function displayMean(mean: string): string {
  const value = Number(mean);
  if (!Number.isFinite(value)) return mean;
  return value.toFixed(1);
}

export function monthTitle(yyyyMm: string): string {
  const [year, month] = yyyyMm.split("-").map(Number);
  if (!year || !month) return yyyyMm;
  return new Date(year, month - 1, 1).toLocaleString("en-US", { month: "long", year: "numeric" });
}

export function statusLabel(status: OverviewBox["status"]): string {
  if (status === "PASS") return "Pass";
  // T112 (D-112-1): the API code stays WARNING; the owner's word is "Acceptable".
  if (status === "WARNING") return "Acceptable";
  if (status === "FAIL") return "Fail";
  return "No standard";
}

export function groupBoxesByModel(boxes: OverviewBox[]): Array<{
  model: string;
  horizontal: OverviewBox[];
  vertical: OverviewBox[];
}> {
  const order: string[] = [];
  const groups = new Map<string, { horizontal: OverviewBox[]; vertical: OverviewBox[] }>();
  for (const box of boxes) {
    if (!groups.has(box.model_code)) {
      order.push(box.model_code);
      groups.set(box.model_code, { horizontal: [], vertical: [] });
    }
    const group = groups.get(box.model_code)!;
    if (box.orient === "Horizontal") group.horizontal.push(box);
    else group.vertical.push(box);
  }
  return order.map((model) => ({ model, ...groups.get(model)! }));
}

export function modelsToRender(
  selected: string[],
  boxes: OverviewBox[],
  options: string[],
): string[] {
  if (selected.length === 0) return groupBoxesByModel(boxes).map((group) => group.model);
  return options.filter((code) => selected.includes(code));
}

export function allChosen(selected: string[], options: string[]): boolean {
  if (options.length === 0) return true;
  return selected.length === 0 || selected.length === options.length;
}

export function isFilterOn(selected: string[], options: string[], value: string): boolean {
  return allChosen(selected, options) || selected.includes(value);
}

export function toggleFilterValue(selected: string[], options: string[], value: string): string[] {
  if (options.length === 0) return selected;
  const current = allChosen(selected, options) ? options : selected;
  const next = current.includes(value)
    ? current.filter((item) => item !== value)
    : [...current, value];
  if (next.length === 0 || next.length === options.length) return [];
  return next;
}

export function defaultDataMonth(calendarMonth: string, available: string[]): string {
  if (available.includes(calendarMonth)) return calendarMonth;
  return available[0] ?? calendarMonth;
}

export function integerDomain(lo: number, hi: number): [number, number] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 100];
  const floor = Math.floor(Math.min(lo, hi));
  const ceil = Math.ceil(Math.max(lo, hi));
  if (floor === ceil) return [floor - 1, ceil + 1];
  return [floor, ceil];
}

export function integerTicks(domain: [number, number]): number[] {
  const [lo, hi] = domain;
  const span = Math.max(hi - lo, 1);
  const step = span <= 20 ? 5 : 10;
  const start = Math.ceil(lo / step) * step;
  const ticks: number[] = [];
  for (let value = start; value <= hi; value += step) ticks.push(value);
  return ticks.length ? ticks : [lo, hi];
}

export function targetRuns(
  boxes: OverviewBox[],
  field: "ford" | "minimum",
): Array<{ value: number; start: string; end: string }> {
  const runs: Array<{ value: number; start: string; end: string }> = [];
  for (const box of boxes) {
    const raw = box[field];
    if (raw == null) continue;
    const value = Number(raw);
    if (!Number.isFinite(value)) continue;
    const last = runs[runs.length - 1];
    if (last && last.value === value) {
      last.end = box.color_name;
    } else {
      runs.push({ value, start: box.color_name, end: box.color_name });
    }
  }
  return runs;
}
