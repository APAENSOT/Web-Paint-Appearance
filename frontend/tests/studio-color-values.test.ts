import assert from "node:assert/strict";
import test from "node:test";
import {
  parseHex,
  parseChannel,
  hexToRgb,
  rgbToHex,
  hsvToRgb,
  rgbToHsv,
  wheelPosition,
} from "../src/features/measurements/model-studio/color-values";

test("colour input accepts complete HEX and rejects incomplete or invalid values", () => {
  assert.equal(parseHex(" #a0B1c2 "), "#A0B1C2");
  assert.equal(parseHex("abc"), "#AABBCC");
  for (const value of ["", "#", "#12", "#1234", "#abcdef00", "rgb(1,2,3)", "#zzzzzz"])
    assert.equal(parseHex(value), null);
});

test("RGB input never coerces blank, fractional, negative or out of range values", () => {
  assert.equal(parseChannel("0"), 0);
  assert.equal(parseChannel("255"), 255);
  for (const value of ["", " ", "256", "-1", "1.5", "1e2", "0xff"])
    assert.equal(parseChannel(value), null);
});

test("wheel conversion preserves primary colours, greys and arbitrary RGB", () => {
  for (const hex of [
    "#FF0000",
    "#00FF00",
    "#0000FF",
    "#000000",
    "#FFFFFF",
    "#777777",
    "#2A739D",
    "#D6DCDF",
  ])
    assert.equal(rgbToHex(hsvToRgb(rgbToHsv(hexToRgb(hex)))), hex);
  assert.deepEqual(wheelPosition(0, 0), { h: 0, s: 0 });
  assert.deepEqual(wheelPosition(2, 0), { h: 0, s: 1 });
  assert.deepEqual(wheelPosition(0, 1), { h: 90, s: 1 });
});
