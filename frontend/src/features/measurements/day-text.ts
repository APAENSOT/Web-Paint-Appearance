/**
 * RO18 (B4): a sheet with no date anywhere is stored on the 1st of the month a
 * person named, with `date_is_month_only: true`. Every place that shows a day
 * shows "<Month YYYY> — day not recorded" for it, never "1 July". Week 0 is the
 * group of those cars: "Day not recorded", never "Week 0".
 */
export const DAY_NOT_RECORDED = "Day not recorded";

/** The day as the API sent it, or the month and "day not recorded". */
export function dayText(date: string, monthOnly?: boolean | null): string {
  if (!monthOnly) return date;
  const [year, month] = date.split("-").map(Number);
  const name = new Date(Date.UTC(year, month - 1, 1)).toLocaleString("en-GB", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  return `${name} — day not recorded`;
}

/** A week card's date span; a month-only span is said once. */
export function dayRange(min: string, max: string, monthOnly?: boolean): string {
  const from = dayText(min, monthOnly);
  const to = dayText(max, monthOnly);
  return monthOnly && from === to ? from : `${from} to ${to}`;
}

export const weekText = (week: number) => (week === 0 ? DAY_NOT_RECORDED : `Week ${week}`);
