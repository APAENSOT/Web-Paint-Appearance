import type { components } from "@/api/types";

export type DataDomain = "both" | "wavescan" | "film";
type Workbook = components["schemas"]["WorkbookOut"];

export const domainLabel = (domain: Exclude<DataDomain, "both">) =>
  domain === "wavescan" ? "WaveScan" : "Film Thickness";

export function workbookDomains(workbook: Workbook): Array<Exclude<DataDomain, "both">> {
  const domains = new Set<Exclude<DataDomain, "both">>();
  for (const sheet of workbook.sheets) {
    if (
      sheet.batch.sheet_class === "OUT_OF_SCOPE_SHEET" ||
      sheet.batch.sheet_class === "UNKNOWN_DATA_SHEET"
    )
      continue;
    const value = sheet.batch.domain ?? sheet.batch.sheet_class;
    if (value === "WAVESCAN") domains.add("wavescan");
    if (value === "FILMTHICKNESS") domains.add("film");
  }
  return (["wavescan", "film"] as const).filter((domain) => domains.has(domain));
}

export function filterWorkbooks(workbooks: Workbook[], domain: DataDomain): Workbook[] {
  return domain === "both"
    ? workbooks
    : workbooks.filter((workbook) => workbookDomains(workbook).includes(domain));
}
