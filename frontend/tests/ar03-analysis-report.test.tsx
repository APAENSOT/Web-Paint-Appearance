import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { AnalysisReportView } from "../src/features/analysis/AnalysisReportView";
import { buildDeck } from "../src/features/analysis/exportReport";
import {
  SECTIONS,
  bandNoteText,
  buildSlidePlan,
  observationRows,
  type SectionId,
} from "../src/features/analysis/report-slides";
import { RANGER, film, filmData, report, ws, wsData } from "./ar03-fixtures";
import { statusLabel } from "../src/features/measurements/overview-display";
import { statusPresentation } from "../src/features/filmthickness/film-overview-display";

const ALL = Object.fromEntries(SECTIONS.map((s) => [s.id, true])) as Record<SectionId, boolean>;
const noop = () => {};
const html = (sections = ALL) =>
  renderToStaticMarkup(
    <AnalysisReportView
      report={report}
      wavescanData={wsData}
      filmData={filmData}
      sections={sections}
      onToggle={noop}
      query={{}}
      onQuery={noop}
      remarks={{}}
      onRemark={noop}
      nextSteps=""
      onNextSteps={noop}
      onExport={noop}
      exporting={false}
      chartFor={(row) => <div data-chart={row.key} />}
      pairing={<div data-pairing="" />}
    />,
  );

test("the page leads with the verdict and the ranked problems, then the detail", () => {
  const out = html();
  const order = [
    "glance",
    "issues",
    "summary",
    "comparison",
    "bands",
    "relationships",
    "pairing",
    "slides",
  ];
  const at = order.map((id) => out.indexOf(`data-section="${id}"`));
  assert.ok(
    at.every((i) => i >= 0),
    JSON.stringify(at),
  );
  assert.deepEqual(
    [...at].sort((a, b) => a - b),
    at,
  );
  // Fail > Over > Acceptable > no status: the Film Primer group (Over) leads and opens first.
  const problems = [...out.matchAll(/data-problem="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(problems, [
    `film|${RANGER}|PRIMER`,
    `wavescan|${RANGER}|`,
    `film|${RANGER}|CLEAR`,
  ]);
  assert.match(out, /data-problem="film|P703 DBL RANGER|PRIMER"><details open="">/);
  assert.match(out, /data-chart="film|P703 DBL RANGER|PRIMER"/);
  for (const area of ["Wave Scan", "Primer", "Clear"])
    assert.match(out, new RegExp(`data-verdict="${area}"`));
  assert.ok(out.includes("1 Acceptable, 1 No standard of 2 boxes"));
});

test("slide choices change the deck, not the page", () => {
  const off = html({ ...ALL, bands: false, relationships: false });
  assert.match(off, /data-section="bands"/);
  assert.match(off, /data-section="relationships"/);
  assert.doesNotMatch(off, /data-toggle="bands" checked=""/);
});

test("status words are exactly the site helpers', never Warning", () => {
  const out = html();
  assert.equal(statusLabel("WARNING"), "Acceptable");
  assert.equal(statusPresentation(film[0]).text, "Over");
  assert.equal(statusPresentation(film[1]).text, "Not graded");
  for (const word of ["Acceptable", "Over", "Not graded", "No standard", "Pass"])
    assert.ok(out.includes(word), word);
  assert.doesNotMatch(out.replace(/data-[a-z-]+="[^"]*"/g, ""), /Warning|WARNING/);
});

test("no percent sign anywhere in the output", () => {
  assert.ok(!html().includes("%"));
});

test("n < 5 draws dots, and the band notes are verbatim", () => {
  const out = html();
  assert.match(out, /data-dot=""/);
  assert.ok(out.includes("Rule of thumb (VOME PAM 2016, slide 19)"));
  assert.equal(
    bandNoteText("wb"),
    "Wb (0.3–1 mm): base coat too heavy, or rough layers underneath (e-coat, substrate). Points to: Clear, Base.",
  );
  for (const b of ["du", "wa", "wb", "wc", "wd", "we"])
    assert.match(out, new RegExp(`data-band-note="${b}"`));
  assert.doesNotMatch(out, /data-band-note="cf"/);
  assert.ok(out.includes("Exploratory, 6 paired cars"));
  assert.ok(
    out.includes("A predictive model needs about 100 cars measured on both instruments; today 6."),
  );
});

test("390 px: tables scroll inside their box and no element has a fixed pixel width", () => {
  const out = html();
  const tables = out.match(/<table/g)!.length;
  assert.equal(out.match(/overflow-x-auto[^>]*><table/g)!.length, tables);
  // Charts scale with their box; only the 16 px lucide icons carry a pixel size.
  assert.doesNotMatch(out, /<svg(?![^>]*lucide)[^>]* width="\d+"/);
  assert.doesNotMatch(out, /w-\[(\d{4}|[4-9]\d\d)px\]/);
});

test("the slide plan: count, order, titles and the section rules", () => {
  const plan = buildSlidePlan(
    { report, wavescan: ws, film },
    {
      sections: ALL,
      remarks: { [`film|${RANGER}|PRIMER`]: "check gun 3" },
      nextSteps: ["Recheck booth 2", ""],
      date: new Date(2026, 9, 14),
    },
  );
  assert.deepEqual(
    plan.map((s) => (s.kind === "title" ? s.title : s.title)),
    [
      "FTM Paint Quality Sep 2026",
      `FTM ${RANGER} Wave Scan CF – Sep'26`,
      "FTM Wave Scan bands – Sep'26",
      `FTM ${RANGER} Primer FB – Sep'26`,
      `FTM ${RANGER} Clear FB – Sep'26`,
      "FTM Relationships – Sep'26",
      "Observation & Summary",
      "Observation & Summary",
    ],
  );
  const title = plan[0];
  assert.ok(
    title.kind === "title" && title.date === "Oct.14.2026" && title.subtitle === "IMG VME Paint",
  );
  const wsSlide = plan[1];
  assert.ok(wsSlide.kind === "chart");
  // Model charts are the Monthly Overview charts, captured by id; band charts carry boxes.
  assert.deepEqual(wsSlide.charts, [{ id: `ws|${RANGER}`, title: `${RANGER} CF` }]);
  const bandsSlide = plan[2];
  assert.ok(bandsSlide.kind === "chart" && bandsSlide.charts.every((c) => c.boxes?.length));
  assert.equal(
    wsSlide.finding,
    "Wave Scan: 0 of 2 boxes Pass, 1 Acceptable, 0 Fail; 0 readings below the minimum.",
  );
  assert.deepEqual(wsSlide.spec, ["Arctic White H: Standard 62.0, Minimum 55.0"]);
  const primer = plan[3];
  assert.ok(
    primer.kind === "chart" &&
      primer.finding === "Primer: 1 of 1 boxes not Pass (0 Acceptable, 0 Fail, 1 Over).",
  );
  const obs = plan[6];
  assert.ok(obs.kind === "observations");
  // FAIL > OVER > WARNING, then count: the Film Primer group (OVER) comes first.
  assert.deepEqual(obs.rows[1], [
    "1",
    RANGER,
    "Film Primer",
    "Primer: 1 of 1 boxes not Pass (0 Acceptable, 0 Fail, 1 Over).",
    "check gun 3",
  ]);
  const notes = plan[7];
  assert.ok(notes.kind === "notes" && notes.nextSteps.length === 1 && notes.summary.length === 1);
  const only = buildSlidePlan(
    { report, wavescan: ws, film },
    {
      sections: { ...ALL, glance: false, bands: false, relationships: false, summary: false },
      remarks: {},
      nextSteps: [],
      date: new Date(),
    },
  );
  assert.equal(only.length, 1);
  assert.ok(!JSON.stringify(plan).includes("%"));
  assert.equal(observationRows(report, ws, film).length, 3);
});

test("pptxgenjs writes a non-empty file for a 3-slide plan", async () => {
  const plan = buildSlidePlan(
    { report, wavescan: ws, film },
    {
      sections: { ...ALL, glance: false, relationships: false, summary: false },
      remarks: {},
      nextSteps: [],
      date: new Date(2026, 9, 14),
    },
  ).concat({
    kind: "notes",
    title: "Observation & Summary",
    nextSteps: ["a"],
    summary: report.summary,
  });
  assert.equal(plan.length, 3);
  const png1x1 =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";
  const png = { data: png1x1, width: 1, height: 1 };
  const deck = await buildDeck(plan, async () => png, { oval: png1x1, script: png1x1 });
  const buffer = (await deck.write({ outputType: "nodebuffer" })) as Buffer;
  assert.ok(buffer.length > 10_000);
  assert.equal(buffer.subarray(0, 2).toString(), "PK");
});
