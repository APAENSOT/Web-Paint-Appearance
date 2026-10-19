import test from "node:test";
import assert from "node:assert/strict";
import {
  FINISH_VALUES,
  finishForFamily,
} from "../src/features/measurements/model-studio/paint-finish";

test("the plant Standard family controls the visual finish, never the colour name", () => {
  assert.equal(finishForFamily("Light Metallics"), "metallic");
  assert.equal(finishForFamily("Dark Metallics"), "metallic");
  assert.equal(finishForFamily("Medium Solids"), "solid");
  assert.equal(finishForFamily(null), "solid");
  assert.equal(FINISH_VALUES.solid[2], 0);
  assert.ok(FINISH_VALUES.metallic[2] > 0);
  assert.ok(FINISH_VALUES.metallic[0] > FINISH_VALUES.solid[0]);
});
