import assert from "node:assert/strict";
import test from "node:test";
import {
  completeLayout,
  pendingPointWrites,
  persistPoints,
} from "../src/features/measurements/model-studio/save-all.ts";
import {
  storageKey,
  type PointProfile,
} from "../src/features/measurements/model-studio/point-storage.ts";
const location = {
  assetVersion: "body@1",
  mesh: "hood",
  position: [0, 1, 0] as [number, number, number],
  normal: [0, 1, 0] as [number, number, number],
};
const profile = {
  domain: "wavescan",
  points: [
    { point_key: "A", revision: 2 },
    { point_key: "B", revision: null },
  ],
} as PointProfile;
test("Save all requires the full current-domain layout, not a filtered list or empty catalogue", () => {
  assert.equal(completeLayout(profile, { [storageKey("wavescan", "A")]: location }), false);
  assert.equal(
    completeLayout(profile, {
      [storageKey("wavescan", "A")]: location,
      [storageKey("wavescan", "B")]: location,
    }),
    true,
  );
  assert.equal(completeLayout({ ...profile, points: [] }, {}), false);
});
test("batch captures only changed current-domain points and their individual revisions", () => {
  const requests = pendingPointWrites(profile, {
    [storageKey("wavescan", "A")]: location,
    [storageKey("film", "A")]: location,
  });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].pointKey, "A");
  assert.equal(requests[0].revision, 2);
});
test("partial failure stops the batch without resending successful writes or skipping failed drafts", async () => {
  const called: number[] = [];
  const result = await persistPoints(
    [1, 2, 3],
    async (n) => {
      called.push(n);
      if (n === 2) throw new Error("Conflict");
    },
    () => {},
  );
  assert.deepEqual(called, [1, 2]);
  assert.equal(result.completed, 1);
  assert.equal(result.failed, 2);
});
