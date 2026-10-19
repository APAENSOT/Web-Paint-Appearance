import type { components } from "./types";

export function batchPollInterval(
  batch: components["schemas"]["BatchOut"] | undefined,
  updates: number,
  failed: boolean,
) {
  if (
    failed ||
    !batch ||
    batch.status !== "RUNNING" ||
    batch.job?.status === "DONE" ||
    batch.job?.status === "FAILED"
  )
    return false;
  return Math.min(1000 * 2 ** Math.min(Math.max(updates - 1, 0), 4), 10000);
}
