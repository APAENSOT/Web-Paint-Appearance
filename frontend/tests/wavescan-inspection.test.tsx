import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { WavescanBoxSummary } from "../src/features/measurements/WavescanBoxSummary";
import {
  wavescanPrimary,
  wavescanBoxKey,
  wavescanDescription,
} from "../src/features/measurements/wavescan-inspection";
import { wavescanClickFixture } from "./wavescan-click-fixtures";

test("WaveScan inspection maps observed bounds rather than quartiles/whiskers, preserving exact specs", () => {
  const box = wavescanClickFixture.boxes[0];
  assert.deepEqual(
    wavescanPrimary(box).map((f) => [f.label, f.raw, f.display]),
    [
      ["Average", box.mean, "62.0"],
      ["Observed minimum", box.box_min, "12.1"],
      ["Observed maximum", box.box_max, "91.0"],
      ["Standard", box.ford, box.ford],
      ["Minimum", "0", "0"],
    ],
  );
});
test("WaveScan inspection distinguishes absent specs and zero without classifications", () => {
  const box = wavescanClickFixture.boxes[1];
  assert.deepEqual(
    wavescanPrimary(box)
      .slice(3)
      .map((f) => f.display),
    ["Not set", "Not set"],
  );
  assert.deepEqual(
    wavescanPrimary(wavescanClickFixture.boxes[3]).map((f) => f.display),
    ["0.0", "0.0", "0.0", "0", "0"],
  );
});
test("WaveScan identity separates repeated colours by model and orientation", () => {
  assert.equal(new Set(wavescanClickFixture.boxes.map(wavescanBoxKey)).size, 4);
  assert.notEqual(
    wavescanBoxKey(wavescanClickFixture.boxes[0]),
    wavescanBoxKey(wavescanClickFixture.boxes[2]),
  );
});
test("WaveScan exact descriptions and summary retain backend status despite rounded mean", () => {
  const box = wavescanClickFixture.boxes[0];
  assert.match(wavescanDescription(box), /Fail/);
  // RO13 (F6): the aria text says what the box shows (62.0), not the raw mean.
  assert.match(wavescanDescription(box), /Average: 62\.0 CF/);
  const html = renderToStaticMarkup(<WavescanBoxSummary box={box} close={() => {}} />);
  assert.match(html, /Detailed measurements/);
  assert.match(html, /data-wavescan-status="FAIL"/);
  for (const raw of [box.mean, box.box_min, box.box_max, box.ford!]) assert.ok(html.includes(raw));
  assert.match(html, /Statistical outliers/);
  assert.doesNotMatch(
    html,
    /µm|Outside-limit readings|Measurement date|point_code|logical_vehicle/,
  );
});
test("WaveScan null status and empty statistical outliers remain explicit", () => {
  const html = renderToStaticMarkup(
    <WavescanBoxSummary box={wavescanClickFixture.boxes[1]} close={() => {}} />,
  );
  assert.match(html, /No standard/);
  assert.match(html, /Not set/);
  assert.match(html, /None/);
});
