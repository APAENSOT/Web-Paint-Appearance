import assert from "node:assert/strict";
import { test } from "node:test";
import { workbookFixture } from "./workbook-fixtures.ts";
import { filterWorkbooks, workbookDomains } from "../src/features/measurements/domain-tags.ts";

const wave = {
  ...workbookFixture,
  sheets: [
    {
      ...workbookFixture.sheets[0],
      batch: { ...workbookFixture.sheets[0].batch, domain: "WAVESCAN" },
    },
  ],
};
const film = {
  ...workbookFixture,
  file_hash: "b".repeat(64),
  sheets: [
    {
      ...workbookFixture.sheets[0],
      batch: { ...workbookFixture.sheets[0].batch, domain: "FILMTHICKNESS" },
    },
  ],
};
const unknown = {
  ...workbookFixture,
  file_hash: "c".repeat(64),
  sheets: [
    {
      ...workbookFixture.sheets[0],
      batch: {
        ...workbookFixture.sheets[0].batch,
        domain: null,
        sheet_class: "UNKNOWN_DATA_SHEET",
      },
    },
  ],
};

test("workbook tags use domain, fallback to sheet class, and ignore unknown classes", () => {
  assert.deepEqual(workbookDomains(wave), ["wavescan"]);
  assert.deepEqual(workbookDomains(film), ["film"]);
  assert.deepEqual(workbookDomains({ ...wave, sheets: [...wave.sheets, ...film.sheets] }), [
    "wavescan",
    "film",
  ]);
  assert.deepEqual(workbookDomains(unknown), []);
  assert.deepEqual(
    workbookDomains({
      ...wave,
      sheets: [
        {
          ...wave.sheets[0],
          batch: { ...wave.sheets[0].batch, sheet_class: "OUT_OF_SCOPE_SHEET" },
        },
      ],
    }),
    [],
  );
  assert.deepEqual(
    workbookDomains({
      ...film,
      sheets: [
        {
          ...film.sheets[0],
          batch: { ...film.sheets[0].batch, domain: null, sheet_class: "FILMTHICKNESS" },
        },
      ],
    }),
    ["film"],
  );
});

test("Both keeps unclassified uploads while domain filters require a matching sheet", () => {
  const all = [wave, film, unknown];
  assert.deepEqual(
    filterWorkbooks(all, "both").map((item) => item.file_hash),
    all.map((item) => item.file_hash),
  );
  assert.deepEqual(
    filterWorkbooks(all, "wavescan").map((item) => item.file_hash),
    [wave.file_hash],
  );
  assert.deepEqual(
    filterWorkbooks(all, "film").map((item) => item.file_hash),
    [film.file_hash],
  );
});
