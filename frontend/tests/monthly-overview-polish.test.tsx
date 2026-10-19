import test from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { WavescanBoxSummary } from "../src/features/measurements/WavescanBoxSummary";
import { groupFilmBoxes, FILM_LAYERS } from "../src/features/filmthickness/film-overview-display";
import { overviewBox } from "./overview-fixtures";
import { filmBox, filmOverviewFixture } from "./film-overview-fixtures";
import { FilmBoxSummary } from "../src/features/filmthickness/FilmBoxSummary";

test("T74 returned reading order and distinct identities survive exact/null presentation", () => {
  const box = {
    ...overviewBox,
    status: "PASS" as const,
    below_minimum: [
      {
        measurement_id: 999001,
        measured_date: "2026-09-30",
        checkzone: "3HOOD",
        cf: "1.123456789012345678901",
      },
      {
        measurement_id: 999002,
        measured_date: "2026-09-30",
        checkzone: "3HOOD",
        cf: "1.123456789012345678901",
      },
      {
        measurement_id: 999003,
        measured_date: null,
        checkzone: null,
        cf: "2.000000000000000000001",
      },
    ],
  };
  const html = renderToStaticMarkup(<WavescanBoxSummary box={box} close={() => {}} />);
  assert.match(html, /Below Minimum/);
  assert.match(html, /30 Sep 2026/);
  assert.match(html, /Date unavailable/);
  assert.match(html, /Zone unavailable/);
  assert.equal(html.split("1.123456789012345678901").length - 1, 2);
  assert.ok(html.indexOf("1.123456789012345678901") < html.indexOf("2.000000000000000000001"));
  assert.doesNotMatch(html, /999001|999002|999003/);
  assert.match(html, /data-wavescan-status="PASS"/);
  assert.match(html, /Published standard/);
});

test("T74 null standards and explicit empty membership do not substitute statistical outliers", () => {
  const html = renderToStaticMarkup(
    <WavescanBoxSummary
      box={{
        ...overviewBox,
        ford: null,
        minimum: null,
        status: null,
        below_minimum: [],
        outliers: ["999.123"],
      }}
      close={() => {}}
    />,
  );
  assert.match(html, /No readings below Minimum/);
  assert.match(html, /Not set/);
  assert.match(html, /Statistical outliers/);
  assert.match(html, /999.123/);
});

test("T74 every plant/layer/model retains full authoritative slots, gaps and sequence metadata", () => {
  const sequence = [
    {
      rank: 1,
      color_name: "Zulu",
      family_code: "MM",
      family_name: "Metallic",
      family_order: 2,
      base_lo_h: "9",
      base_hi_h: "10",
      base_lo_v: "15",
      base_hi_v: "20",
      ladder: "BASE" as const,
    },
    {
      rank: 2,
      color_name: "Alpha",
      family_code: "LS",
      family_name: "Solid",
      family_order: 1,
      base_lo_h: "9",
      base_hi_h: "10",
      base_lo_v: "16",
      base_hi_v: null,
      ladder: "BASE" as const,
    },
    {
      rank: 3,
      color_name: "Published without Base measurements",
      family_code: "MM",
      family_name: "Metallic",
      family_order: 2,
      base_lo_h: "9",
      base_hi_h: "10",
      base_lo_v: "16",
      base_hi_v: null,
      ladder: "BASE" as const,
    },
    {
      rank: 4,
      color_name: "No Base",
      family_code: null,
      family_name: null,
      family_order: null,
      base_lo_h: null,
      base_hi_h: null,
      base_lo_v: null,
      base_hi_v: null,
      ladder: "NO_BASE_STANDARD" as const,
    },
  ];
  for (const plant_code of ["AAT", "FTM", "FVL", "SAP"])
    for (const { code } of FILM_LAYERS) {
      const data = {
        ...filmOverviewFixture,
        plant_code,
        color_sequence: sequence,
        boxes: [
          filmBox({
            layer_code: code,
            model_code: "One",
            color_name: "Zulu",
            color_rank: 1,
            orient: "H",
            mean: "100",
          }),
          filmBox({
            layer_code: code,
            model_code: "One",
            color_name: "No Base",
            color_rank: 4,
            orient: "V",
            mean: "0",
          }),
          filmBox({
            layer_code: code,
            model_code: "Two",
            color_name: "Alpha",
            color_rank: 2,
            orient: "H",
          }),
        ],
      };
      for (const group of groupFilmBoxes(data, code)) {
        assert.deepEqual(
          group.colours.map((c) => c.name),
          sequence.map((c) => c.color_name),
        );
        assert.deepEqual(
          group.colours.map((c) => c.family_name),
          sequence.map((c) => c.family_name),
        );
        assert.equal(group.colours[2].boxes.length, 0);
        assert.deepEqual(
          group.boxes,
          data.boxes.filter((b) => b.model_code === group.model),
        );
      }
    }
});

test("T74 Film published labels preserve zero/null, precision and ordering separate from grade", () => {
  const html = renderToStaticMarkup(
    <FilmBoxSummary
      box={filmBox({
        lo: "0",
        hi: null,
        hi_label: "Exact upper label",
        target: "46.0000000000000000001",
        target_label: "Requirement",
      })}
      ladder="NO_BASE_STANDARD"
      close={() => {}}
    />,
  );
  assert.match(html, /Published standard/);
  assert.match(html, /Exact upper label/);
  assert.match(html, /Not set/);
  assert.match(html, /46.0000000000000000001/);
  assert.match(html, /No Base standard for ordering/);
  assert.match(html, /data-status="nominal"/);
  assert.match(html, /0 µm/);
});

test("T74 NONE standard remains honest without hiding statistics or inventing limits", () => {
  const html = renderToStaticMarkup(
    <FilmBoxSummary
      box={filmBox({ standard_scope: "NONE", status: null, lo: null, lo_label: null })}
      close={() => {}}
    />,
  );
  assert.match(html, /No standard/);
  assert.doesNotMatch(html, /Minimum requirement|No Base standard for ordering/);
  assert.match(html, /Observed minimum/);
  assert.match(html, /Statistical outliers/);
});
