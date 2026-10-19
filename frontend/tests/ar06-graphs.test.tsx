import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { EvidenceChart, OWN_TABLE } from "../src/features/analysis/charts";
import type { AssistantAnswer } from "../src/features/analysis/report-types";

type Evidence = AssistantAnswer["evidence"];
const ev = (kind: string, columns: string[], rows: unknown[][], points: unknown[] = []) =>
  ({
    kind,
    columns,
    rows,
    series: [],
    limits: null,
    cells: [],
    groups: [],
    points,
    card: [],
  }) as unknown as Evidence;
const html = (e: Evidence) => renderToStaticMarkup(<EvidenceChart evidence={e} />);

const SHIFT_COLS = ["Box", "Before", "Now", "Change", "Verdict"];
const shiftRows = [
  ["M1 Red · Primer · H", "Pass", "Fail", "+10.0 µm", "Real shift"],
  ["M2 Blue · Clear · V", "Pass", "Pass", "-0.2 µm", "Noise"],
  ["M3 Red · Primer · H", "—", "Pass", "—", "New"],
];
const shiftPoints = [
  { x: 20.5, y: 30.5, label: "M1 Red · Primer · H" },
  { x: 41.0, y: 40.8, label: "M2 Blue · Clear · V" },
];

test("shift: a dumbbell per box measured in both months, real shift named in words", () => {
  const out = html(ev("shift", SHIFT_COLS, shiftRows, shiftPoints));
  assert.match(out, /role="img"[^>]*aria-label="[^"]+"/);
  assert.equal([...out.matchAll(/data-shift=/g)].length, 2); // the New box has no before: no dumbbell
  assert.match(out, /data-shift="M1 Red · Primer · H"[^>]*data-real="true"/);
  assert.match(out, /data-shift="M2 Blue · Clear · V"[^>]*data-real="false"/);
  assert.ok(out.includes("Real shift") && out.includes("Noise"));
  assert.ok(out.includes("20.5 → 30.5 µm")); // unit read from the row's Change cell
  assert.ok(out.includes("41 → 40.8 µm"));
  assert.ok(
    out.includes("Shared scale:") && out.includes("Reference month") && out.includes("Later month"),
  );
  assert.ok(!out.includes("bg-muted-foreground/50"));
});

test("month shifts in different units have separately labelled scales", () => {
  const out = html(
    ev(
      "shift",
      SHIFT_COLS,
      [
        ["Primer", "Pass", "Fail", "-4.0 µm", "Real shift"],
        ["CF", "Pass", "Pass", "+2.0", "Noise"],
      ],
      [
        { x: 30, y: 26, label: "Primer" },
        { x: 50, y: 52, label: "CF" },
      ],
    ),
  );
  assert.ok(out.includes("26 to 30") && out.includes("50 to 52"));
  assert.equal((out.match(/guide-shift-group/g) ?? []).length, 2);
  assert.ok(out.includes("(unitless)") && out.includes("µm"));
});

test("a shift's accessible name includes both actual periods and their quality statuses", () => {
  const evidence = ev(
    "shift",
    SHIFT_COLS,
    [["Primer", "Pass", "Fail", "-4 µm", "Real shift"]],
    [{ x: 30, y: 26, label: "Primer" }],
  );
  const out = renderToStaticMarkup(
    <EvidenceChart
      evidence={evidence}
      periods={{ before: "September 2026", now: "October 2026" }}
    />,
  );
  const name = out.match(/aria-label="([^"]+)"/)?.[1] ?? "";
  for (const fact of ["September 2026", "October 2026", "Pass", "Fail", "30", "26"])
    assert.ok(name.includes(fact), fact);
});

test("shift without plottable numbers draws no frame; the card keeps its table", () => {
  assert.equal(html(ev("shift", SHIFT_COLS, shiftRows, [])), "");
  assert.equal(html(ev("shift", SHIFT_COLS, shiftRows, [{ x: Number.NaN, y: 1, label: "x" }])), "");
  assert.ok(!OWN_TABLE.has("shift"));
});

test("went_well: signed Change plots as a bar; capable rows without a change are skipped", () => {
  const cols = ["Box", "Change", "Verdict", "Now"];
  const out = html(
    ev("bar", cols, [
      ["Blue · Clear · V", "+2.0", "Real shift", "Pass"],
      ["Gold · Primer · V", null, "Capable (Cpk 2.10)", "Pass"],
    ]),
  );
  assert.match(out, /role="img"[^>]*aria-label="Change for the top 1, as in the table:/);
  assert.equal(html(ev("bar", cols, [["Gold", null, "Capable (Cpk 2.10)", "Pass"]])), "");
});

test("points (kind table): Out plots as a bar; no numbers falls back to the table", () => {
  const cols = ["Point", "Out", "Measured", "Plant normal"];
  assert.match(
    html(ev("table", cols, [["R-12", 6, 20, "about 1 in 9"]])),
    /aria-label="Out for the top 1, as in the table:/,
  );
  assert.equal(html(ev("table", cols, [])), "");
});

test("a correlation coefficient is never labelled as a count out of its sample size", () => {
  const out = html(ev("bar", ["Band", "ρ", "n"], [["LW", -0.8, 20]]));
  assert.ok(out.includes("-0.8"));
  assert.ok(!out.includes("of 20 readings"));
});
