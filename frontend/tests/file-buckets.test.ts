import assert from "node:assert/strict";
import { test } from "node:test";
import { workbookFixture } from "./workbook-fixtures";
import { groupFiles } from "../src/features/measurements/file-buckets";

test("current month weeks use measured dates, never upload date or filename", () => {
  for (const [day, week] of [
    [1, 1],
    [7, 1],
    [8, 2],
    [14, 2],
    [15, 3],
    [21, 3],
    [22, 4],
    [28, 4],
    [29, 5],
    [30, 5],
    [31, 5],
  ]) {
    const groups = groupFiles(
      [
        {
          ...workbookFixture,
          measured_date_min: `2026-07-${String(day).padStart(2, "0")}`,
          uploaded_at: "2026-09-16T00:00:00Z",
        },
      ],
      new Date(2026, 6, 15),
    );
    assert.equal(groups[0].month, "2026-07");
    assert.equal(groups[0].week, week);
  }
  assert.equal(
    groupFiles(
      [{ ...workbookFixture, uploaded_at: "2026-07-08T00:30:00+07:00" }],
      new Date(2026, 6, 15),
    )[0].week,
    0,
  );
});

test("undated files top current calendar month, older measured months have no weeks", () => {
  const file = (hash: string, uploaded_at: string) => ({
    ...workbookFixture,
    file_hash: hash,
    uploaded_at,
  });
  const groups = groupFiles(
    [
      file("older", "2026-09-15T00:00:00Z"),
      {
        ...file("retained", "2026-09-29T00:00:00Z"),
        superseded: true,
        operational_summary: "SUPERSEDED" as const,
      },
      { ...file("processing", "2026-09-01T00:00:00Z"), operational_summary: "PROCESSING" as const },
      { ...file("unresolved", "2026-09-02T00:00:00Z"), measured_date_min: null },
      file("newer", "2026-09-16T00:00:00Z"),
    ],
    new Date(2026, 8, 28),
  );
  assert.deepEqual(
    groups.map(({ month, week }) => [month, week]),
    [
      ["2026-09", 0],
      ["2026-06", 0],
    ],
  );
  assert.deepEqual(
    groups[0].files.map((f) => f.file_hash),
    ["unresolved"],
  );
  assert.equal(groups.flatMap((g) => g.files).length, 5);
});

test("remainder with a separate hash keeps its own inbox card", () => {
  const named = { ...workbookFixture, file_hash: "named", source_file: "May CF.xlsx" };
  const remainder = { ...workbookFixture, file_hash: "rem", source_file: "May CF-remainder.xlsx" };
  assert.deepEqual(
    groupFiles([named, remainder], new Date(2026, 8, 28)).flatMap((g) =>
      g.files.map((f) => f.file_hash),
    ),
    ["named", "rem"],
  );
});

test("Upload Data keeps stored workbooks with distinct hashes", () => {
  const groups = groupFiles([
    {
      ...workbookFixture,
      abandoned: true,
      operational_summary: "ABANDONED",
      measured_date_min: null,
      uploaded_at: "2026-09-16T00:00:00Z",
    },
    {
      ...workbookFixture,
      file_hash: "s".repeat(64),
      superseded: true,
      operational_summary: "SUPERSEDED",
    },
  ]);
  assert.equal(groups.flatMap((group) => group.files).length, 2);
});
