import test from "node:test";
import assert from "node:assert/strict";
import {
  profileLocations,
  profilePoints,
  mergeLocations,
  toAnchor,
} from "../src/features/measurements/model-studio/point-storage";
import type { components } from "../src/api/types";
const anchor = {
  asset_version: "ranger-sgl@20261013-repair-3",
  mesh_name: "hood",
  position: [1, 2, 3],
  normal: [0, 1, 0],
  body_zone: null,
  asset_compatible: true,
};
const point = {
  point_key: "HOOD",
  zone_code: "HOOD",
  point_code: null,
  point_no: 1,
  label: "Hood 1",
  counted: true,
  is_extra: false,
  unavailable_reason: null,
  retired_at: null,
  revision: 2,
  saved_at: "2026-10-13T00:00:00Z",
  saved_by: "Engineer",
  anchor,
};
const profile = {
  plant_code: "FTM",
  model_code: "P703 SGL",
  domain: "wavescan",
  state: "configured",
  profile_revision: 2,
  last_saved_at: point.saved_at,
  asset: null,
  points: [point],
  unavailable: [],
} as components["schemas"]["PointProfileOut"];
test("profile keeps canonical identity behind the plant's renamed display label", () => {
  const [p] = profilePoints(profile);
  assert.equal(p.code, "Hood 1");
  assert.equal(p.pointKey, "HOOD");
  assert.equal(p.key, JSON.stringify(["wavescan", "HOOD"]));
});
test("saved locations only draw on their exact compatible geometry", () => {
  const key = JSON.stringify(["wavescan", "HOOD"]);
  const locations = profileLocations(profile, anchor.asset_version);
  assert.equal(locations[key].mesh, "hood");
  assert.deepEqual(profileLocations(profile, "other-model@version"), {});
  assert.deepEqual(
    profileLocations(
      { ...profile, points: [{ ...point, anchor: { ...anchor, asset_compatible: false } }] },
      anchor.asset_version,
    ),
    {},
  );
  assert.deepEqual(toAnchor(locations[key]), {
    asset_version: anchor.asset_version,
    mesh_name: "hood",
    position: [1, 2, 3],
    normal: [0, 1, 0],
    body_zone: null,
  });
});
test("one pending removal preserves other saved and other-domain locations", () => {
  const base = profileLocations(profile, anchor.asset_version);
  const key = Object.keys(base)[0];
  const other = JSON.stringify(["film", "HOOD"]);
  assert.deepEqual(mergeLocations({ ...base, [other]: base[key] }, { [key]: null }), {
    [other]: base[key],
  });
});
