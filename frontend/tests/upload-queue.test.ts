import assert from "node:assert/strict";
import { test } from "node:test";
import {
  QUEUE_STATE_COPY,
  QUEUE_STATE_LABEL,
  newQueue,
  nextAttentionItem,
  queueRunning,
  queueSettled,
  resolvedQueueState,
  storedLoadId,
  type UploadQueueItem,
} from "../src/features/measurements/upload-queue";

const item = (over: Partial<UploadQueueItem> = {}): UploadQueueItem => ({
  id: 0,
  filename: "one.xlsx",
  state: "waiting",
  sheets: [],
  opened: false,
  ...over,
});

test("a chosen list becomes one waiting row per file, in order", () => {
  const queue = newQueue([
    { name: "one.xlsx" } as File,
    { name: "two.xlsx" } as File,
    { name: "three.xlsx" } as File,
  ]);
  assert.deepEqual(
    queue.map((row) => [row.id, row.filename, row.state, row.opened]),
    [
      [0, "one.xlsx", "waiting", false],
      [1, "two.xlsx", "waiting", false],
      [2, "three.xlsx", "waiting", false],
    ],
  );
  assert.equal(queueRunning(queue), true);
  assert.equal(queueSettled(queue), false);
});

test("the queue is settled only when no file is waiting, uploading or processing", () => {
  assert.equal(queueSettled([]), false);
  assert.equal(queueSettled([item({ state: "processing" })]), false);
  assert.equal(
    queueSettled([item({ state: "attention" }), item({ id: 1, state: "duplicate" })]),
    true,
  );
  assert.equal(queueRunning([item({ state: "refused" }), item({ id: 1, state: "waiting" })]), true);
});

test("the next file needing attention skips opened rows and rows without a hash", () => {
  const opened = item({ id: 0, state: "attention", hash: "a".repeat(64), opened: true });
  const unknown = item({ id: 1, state: "attention" });
  const waiting = item({ id: 2, state: "attention", hash: "c".repeat(64) });
  assert.equal(nextAttentionItem([opened, unknown, waiting]), waiting);
  assert.equal(nextAttentionItem([opened, unknown]), undefined);
  assert.equal(nextAttentionItem([opened, item({ id: 3, state: "ready" })]), undefined);
});

test("a settled file needs attention unless every accepted sheet is already committed", () => {
  assert.equal(
    resolvedQueueState({
      sheets: [{ status: "PENDING_REVIEW" }],
      batchStatuses: ["PENDING_REVIEW"],
      errored: false,
    }),
    "attention",
  );
  assert.equal(
    resolvedQueueState({
      sheets: [{ status: "COMMITTED" }],
      batchStatuses: ["COMMITTED"],
      errored: false,
    }),
    "ready",
  );
  assert.equal(resolvedQueueState({ sheets: [], batchStatuses: [], errored: false }), "ready");
});

test("a failed sheet, a failed batch or a dead poll is not dressed up as reviewable", () => {
  assert.equal(
    resolvedQueueState({ sheets: [{ status: "FAILED" }], batchStatuses: [""], errored: false }),
    "failed",
  );
  assert.equal(
    resolvedQueueState({
      sheets: [{ status: "PENDING_REVIEW" }],
      batchStatuses: ["FAILED"],
      errored: false,
    }),
    "failed",
  );
  assert.equal(
    resolvedQueueState({
      sheets: [{ status: "PENDING_REVIEW" }],
      batchStatuses: [""],
      errored: true,
    }),
    "failed",
  );
});

test("the stored load id comes from the 409 envelope, never guessed", () => {
  assert.equal(
    storedLoadId(
      `"07. Jul'26 CF data AAT.xlsx" has already been ingested: its SHA-256 matches load_id 1088 (07. Jul'26 CF data AAT.xlsx [Sheet1], SUPERSEDED). Nothing was stored.`,
    ),
    1088,
  );
  assert.equal(storedLoadId("This file is not a workbook."), undefined);
  assert.equal(storedLoadId(""), undefined);
});

test("every queue state has an honest label and sentence", () => {
  const states = Object.keys(QUEUE_STATE_LABEL);
  assert.deepEqual(states, Object.keys(QUEUE_STATE_COPY));
  for (const state of states) {
    assert.ok(QUEUE_STATE_LABEL[state as keyof typeof QUEUE_STATE_LABEL].length > 0);
    assert.ok(QUEUE_STATE_COPY[state as keyof typeof QUEUE_STATE_COPY].endsWith("."));
  }
  assert.equal(QUEUE_STATE_LABEL.duplicate, "Already uploaded");
  assert.equal(QUEUE_STATE_LABEL.attention, "Needs attention");
});
