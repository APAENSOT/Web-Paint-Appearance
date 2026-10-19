import test from "node:test";
import assert from "node:assert/strict";
import {
  boardReducer,
  initialBoard,
  laneMonths,
  type Board,
} from "../src/features/measurements/comparison-board";
import { createApiClient } from "../src/api/client";
import { monthlyEntries } from "../src/features/measurements/studio-series";
import { studioPreview } from "./studio-fixtures";

test("T82 only supplied group 50, original boxes and exact zero; gaps retain month order and no group statistics", () => {
  const input = {
    domain: "WAVESCAN" as const,
    model: "P703",
    metric: "cf" as const,
    months: ["2026-08", "2026-06", "2026-07"],
  };
  const data = studioPreview(input);
  data.group_means[1] = {
    ...data.group_means[1],
    mean: null,
    monthly: input.months.map((month) => ({ month, mean: null, n: 0 })),
    contributing_months: [],
    missing_months: input.months,
    contributing_month_count: 0,
  };
  const item = { id: "group", kind: "group" as const, name: "Group", months: input.months };
  let entries = monthlyEntries(data, item, () => true);
  const mean = entries.find((e) => e.group?.color === "Arctic White" && e.orientation === "H")!;
  assert.equal(mean.group?.mean, "50");
  assert.equal(mean.box, undefined);
  assert.equal(mean.n, undefined);
  const gap = entries.find(
    (e) => e.caption === "2026-08" && e.color === "Arctic White" && e.orientation === "H",
  )!;
  assert.equal(gap.box, undefined);
  assert.equal(gap.n, 0);
  assert.deepEqual(
    entries
      .filter((e) => e.color === "Arctic White" && e.orientation === "H")
      .map((e) => e.caption),
    [...input.months, "Group"],
  );
  data.month_boxes[1].wavescan_boxes[0].mean = "0.00000000000000000";
  entries = monthlyEntries(data, { ...item, kind: "month" }, (c) => c === "Arctic White");
  assert.equal(
    entries.find((e) => e.caption === "2026-06" && e.orientation === "H")?.box?.mean,
    "0.00000000000000000",
  );
  assert.equal(entries.filter((e) => e.group).length, 0);
  assert.ok(entries.every((e) => e.color === "Arctic White"));
  assert.deepEqual(
    monthlyEntries(data, item, () => false),
    [],
  );
});
const lane = (model: string) => ({ id: model, model, domain: "WAVESCAN" as const, items: [] });
test("T82 arbitrary boards, overlapping and one-month groups retain operator order; cross-model move rejected", () => {
  let board = boardReducer(initialBoard(), { type: "lane", lane: lane("P703") });
  board = boardReducer(board, { type: "lane", lane: lane("U704") });
  for (let i = 0; i < 12; i++)
    board = boardReducer(board, {
      type: "add",
      lane: "P703",
      item: {
        id: String(i),
        kind: "month",
        name: String(i),
        months: [`2026-${String(i + 1).padStart(2, "0")}`],
      },
    });
  for (const [id, months] of [
    ["a", ["2026-06", "2026-07", "2026-08"]],
    ["b", ["2026-07"]],
  ] as const)
    board = boardReducer(board, {
      type: "add",
      lane: "P703",
      item: { id, kind: "group", name: id, months: [...months] },
    });
  board = boardReducer(board, {
    type: "add",
    lane: "U704",
    item: { id: "u", kind: "group", name: "u", months: [] },
  });
  const before = board.lanes;
  board = boardReducer(board, {
    type: "move",
    lane: "P703",
    id: "a",
    month: "2026-06",
    targetLane: "U704",
    target: "u",
  });
  assert.equal(board.lanes, before);
  assert.match(board.notice, /cannot move across model/);
  board = boardReducer(board, {
    type: "member-order",
    lane: "P703",
    id: "a",
    month: "2026-08",
    direction: -1,
  });
  assert.deepEqual(board.lanes[0].items.find((i) => i.id === "a")?.months, [
    "2026-06",
    "2026-08",
    "2026-07",
  ]);
  board = boardReducer(board, { type: "dissolve", lane: "P703", id: "a" });
  assert.equal(board.lanes[0].items.length, 16);
  assert.deepEqual(
    laneMonths(board.lanes[0]),
    Array.from({ length: 12 }, (_, i) => `2026-${String(i + 1).padStart(2, "0")}`),
  );
});
test("T82 move in/out, rename, reorder, remove and display-only colours", () => {
  let b: Board = boardReducer(initialBoard(), { type: "lane", lane: lane("P703") });
  b = boardReducer(b, {
    type: "add",
    lane: "P703",
    item: { id: "a", kind: "month", name: "June", months: ["2026-06"] },
  });
  b = boardReducer(b, {
    type: "add",
    lane: "P703",
    item: { id: "g", kind: "group", name: "Group", months: [] },
  });
  b = boardReducer(b, {
    type: "move",
    lane: "P703",
    id: "a",
    month: "2026-06",
    targetLane: "P703",
    target: "g",
  });
  assert.equal(b.lanes[0].items.length, 1);
  assert.deepEqual(b.lanes[0].items[0].months, ["2026-06"]);
  b = boardReducer(b, {
    type: "move",
    lane: "P703",
    id: "g",
    month: "2026-06",
    targetLane: "P703",
    target: "",
  });
  assert.equal(b.lanes[0].items.length, 2);
  b = boardReducer(b, { type: "rename", lane: "P703", id: "g", name: "New" });
  b = boardReducer(b, { type: "reorder", lane: "P703", id: "g", direction: 1 });
  assert.equal(b.lanes[0].items[1].name, "New");
  const before = b.lanes;
  b = boardReducer(b, { type: "hide", color: "Arctic White" });
  assert.equal(b.lanes, before);
  assert.deepEqual(b.hidden, ["Arctic White"]);
  b = boardReducer(b, { type: "restore" });
  assert.deepEqual(b.hidden, []);
  b = boardReducer(b, { type: "remove", lane: "P703", id: "g" });
  assert.equal(b.lanes[0].items.length, 1);
});
test("T82 read-only preview body and ordered vehicle visuals use existing transport/cancellation", async () => {
  const calls: { url: URL; init: RequestInit }[] = [];
  const client = createApiClient("http://localhost:8012", (async (url, init) => {
    calls.push({ url: new URL(String(url)), init: init! });
    return new Response("{}");
  }) as typeof fetch);
  const body = {
    domain: "WAVESCAN" as const,
    model: "P703",
    metric: "cf" as const,
    months: ["2026-07", "2026-06", "2026-08"],
  };
  const controller = new AbortController();
  await client.comparisonMonthlyPreview("AAT", body, controller.signal);
  await client.comparisonVehicleVisuals(
    "AAT",
    { model: "P703", vehicle_id: ["b".repeat(64), "a".repeat(64)] },
    controller.signal,
  );
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body as string), body);
  assert.deepEqual(calls[1].url.searchParams.getAll("vehicle_id"), [
    "b".repeat(64),
    "a".repeat(64),
  ]);
  assert.ok(
    calls.every((c) => c.init.credentials === "omit" && c.init.signal === controller.signal),
  );
});
