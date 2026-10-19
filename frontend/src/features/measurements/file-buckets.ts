import type { components } from "../../api/types";
type Workbook = components["schemas"]["WorkbookOut"];

export function measuredWeek(date: string) {
  return Math.ceil(Number(date.slice(8, 10)) / 7);
}

export function inboxWorkbooks(files: Workbook[]) {
  return files.filter((file) => !file.abandoned && !file.superseded);
}

function isRemainder(file: Workbook) {
  return /-remainder(?:\b|[-_.])/i.test(file.source_file);
}

function overlaps(a: Workbook, b: Workbook) {
  return !!(
    a.measured_date_min &&
    a.measured_date_max &&
    b.measured_date_min &&
    b.measured_date_max &&
    a.measured_date_min <= b.measured_date_max &&
    b.measured_date_min <= a.measured_date_max
  );
}

export function withoutPairedRemainders(files: Workbook[]) {
  return files.filter(
    (file) =>
      !isRemainder(file) ||
      !files.some(
        (parent) =>
          parent.file_hash !== file.file_hash && !isRemainder(parent) && overlaps(file, parent),
      ),
  );
}

export function groupFiles(files: Workbook[], now = new Date()) {
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const groups = new Map<string, { month: string; week: number; files: Workbook[] }>();
  const seen = new Set<string>();
  for (const file of files) {
    if (seen.has(file.file_hash)) continue;
    seen.add(file.file_hash);
    const month = file.measured_date_min?.slice(0, 7) ?? currentMonth;
    const week =
      month === currentMonth && file.measured_date_min ? measuredWeek(file.measured_date_min) : 0;
    const key = `${month}-${week}`;
    const group = groups.get(key) ?? { month, week, files: [] };
    group.files.push(file);
    groups.set(key, group);
  }
  return [...groups.values()]
    .sort(
      (a, b) =>
        (a.month === currentMonth
          ? -1
          : b.month === currentMonth
            ? 1
            : b.month.localeCompare(a.month)) || a.week - b.week,
    )
    .map((group) => ({
      ...group,
      files: group.files.sort(
        (a, b) =>
          Number(a.measured_date_min !== null) - Number(b.measured_date_min !== null) ||
          Date.parse(b.uploaded_at) - Date.parse(a.uploaded_at),
      ),
    }));
}
