import assert from "node:assert/strict";
import { test } from "node:test";
import { scoreLevel, sinceText, toPlantFeed } from "../src/features/overview/plant-feed.ts";

test("landing plant maps API fields only; no client grading", () => {
  const feed = toPlantFeed(
    {
      plant_code: "FTM",
      quality: { pct: 65.8, groups: [] },
      feed: {
        level: "LATE",
        pct: 20.8,
        week: 2,
        late_weeks: 1,
        missing_weeks: 0,
        colours_this_week: 0,
        colours: 9,
        models: 4,
      },
      wavescan_cars: 47,
      film_cars: 169,
      latest_files: [],
    },
    false,
    false,
  );
  assert.equal(feed.status?.level, "caution");
  assert.equal(feed.status?.pct, 20.8);
  assert.equal(feed.quality, 65.8);
  assert.equal(feed.wavescanCars, 47);
  const missing = toPlantFeed(undefined, true, false);
  assert.equal(missing.status, null);
  assert.equal(missing.quality, null);
  assert.equal(missing.pending, true);
});

test("score bands: 0-50 red, 51-80 yellow, 81-100 green", () => {
  assert.deepEqual([50, 51, 80, 81].map(scoreLevel), ["critical", "caution", "caution", "nominal"]);
});

test("since text", () => {
  const t = Date.parse("2026-10-13T10:00:00Z");
  assert.equal(sinceText("2026-10-13T09:56:00Z", t), "4m");
  assert.equal(sinceText("2026-10-13T07:00:00Z", t), "3h");
  assert.equal(sinceText("2026-10-10T10:00:00Z", t), "3d");
});
