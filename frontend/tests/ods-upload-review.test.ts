import assert from "node:assert/strict";
import { test } from "node:test";
import type { components } from "../src/api/types";
import { workbookFixture } from "./workbook-fixtures";
import { filterWorkbooks, workbookDomains } from "../src/features/measurements/domain-tags";
import { noUsableQuickSummary, sheetClassNotice } from "../src/features/measurements/review-copy";

type Workbook = components["schemas"]["WorkbookOut"];
const oos = (
  name: string,
  status: Workbook["sheets"][number]["batch"]["status"] = "REJECTED_TEMPLATE",
): Workbook["sheets"][number] => ({
  ...workbookFixture.sheets[0],
  batch: {
    ...workbookFixture.sheets[0].batch,
    source_sheet: name,
    status,
    domain: null,
    sheet_class: "OUT_OF_SCOPE_SHEET",
  },
  committable: false,
  commit_blockers: ["OUT_OF_SCOPE_SHEET"],
});
const book = (name: string, sheets: Workbook["sheets"]): Workbook => ({
  ...workbookFixture,
  source_file: name,
  sheets,
  sheet_count: sheets.length,
});

test("T78 layer-only and link-only evidence get the same returned-classification message and Both placement", () => {
  for (const sheets of [
    [oos("Clearcoat"), oos("E-Coat")],
    [oos("Quick_Summary"), oos("Body")],
  ]) {
    const workbook = book("SAP-Film.ODS", sheets);
    assert.equal(noUsableQuickSummary(workbook), true);
    assert.deepEqual(workbookDomains(workbook), []);
    assert.deepEqual(filterWorkbooks([workbook], "both"), [workbook]);
    assert.deepEqual(filterWorkbooks([workbook], "film"), []);
    assert.match(sheetClassNotice(sheets[0], workbook) ?? "", /Film Thickness/);
    assert.doesNotMatch(sheetClassNotice(sheets[0], workbook) ?? "", /not WaveScan/);
  }
});

test("T78 mixed Film, unknown, xlsx, empty-current and superseded cases never claim missing Quick Summary", () => {
  const film = {
    ...workbookFixture.sheets[0],
    batch: {
      ...workbookFixture.sheets[0].batch,
      sheet_class: "FILMTHICKNESS",
      domain: "FILMTHICKNESS",
    },
  };
  const unknown: Workbook["sheets"][number] = {
    ...oos("Data"),
    batch: { ...oos("Data").batch, sheet_class: "UNKNOWN_DATA_SHEET" },
  };
  for (const workbook of [
    book("mixed.ods", [oos("Base"), film]),
    book("unknown.ods", [oos("Base"), unknown]),
    book("other.xlsx", [oos("Base")]),
    book("empty.ods", []),
    book("old.ods", [oos("Base", "SUPERSEDED")]),
  ])
    assert.equal(noUsableQuickSummary(workbook), false, workbook.source_file);
  assert.match(
    sheetClassNotice(oos("Base"), book("mixed.ods", [film, oos("Base")])) ?? "",
    /Film Thickness/,
  );
  assert.equal(
    sheetClassNotice(oos("Base"), book("other.xlsx", [oos("Base")])),
    "This tab is not WaveScan. It is kept as evidence and is not a broken template.",
  );
  assert.equal(
    sheetClassNotice(unknown, book("unknown.ods", [unknown])),
    "This tab looks like data but is not a WaveScan sheet. It is blocked for classification.",
  );
});
