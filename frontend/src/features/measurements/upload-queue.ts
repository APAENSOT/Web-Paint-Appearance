import type { components } from "@/api/types";
import { isFailedUploadStatus, shouldAutoOpenReview } from "./review-copy";

export type UploadQueueState =
  | "waiting"
  | "uploading"
  | "processing"
  | "attention"
  | "ready"
  | "duplicate"
  | "refused"
  | "failed";

export type UploadQueueItem = {
  id: number;
  filename: string;
  state: UploadQueueState;
  sheets: components["schemas"]["UploadedSheet"][];
  opened: boolean;
  hash?: string;
  message?: string;
  correlationId?: string;
  storedLoadId?: number;
  error?: Error;
};

export const QUEUE_STATE_LABEL: Record<UploadQueueState, string> = {
  waiting: "Waiting",
  uploading: "Uploading",
  processing: "Processing",
  attention: "Needs attention",
  ready: "Already current",
  duplicate: "Already uploaded",
  refused: "Refused",
  failed: "Processing did not finish",
};

export const QUEUE_STATE_COPY: Record<UploadQueueState, string> = {
  waiting: "Waiting for the files before it.",
  uploading: "Sending this file on its own request.",
  processing: "Reading this file's sheets.",
  attention: "Open its review to answer this file's questions. Nothing loads until you do.",
  ready: "Nothing to answer. Open Measurement History to inspect these measurements.",
  duplicate: "These exact bytes are already stored. Nothing was stored for this file.",
  refused: "The server refused this file. Nothing was stored for it.",
  failed: "Processing did not finish for this file.",
};

const RUNNING_STATES: UploadQueueState[] = ["waiting", "uploading", "processing"];

export function newQueue(files: File[]): UploadQueueItem[] {
  return files.map((file, index) => ({
    id: index,
    filename: file.name,
    state: "waiting",
    sheets: [],
    opened: false,
  }));
}

export function queueRunning(items: UploadQueueItem[]) {
  return items.some((item) => RUNNING_STATES.includes(item.state));
}

export function queueSettled(items: UploadQueueItem[]) {
  return items.length > 0 && !queueRunning(items);
}

export function nextAttentionItem(items: UploadQueueItem[]) {
  return items.find((item) => item.state === "attention" && item.hash && !item.opened);
}

export function storedLoadId(message: string) {
  const match = message.match(/matches load_id (\d+) \((.+?) \[/);
  return match ? Number(match[1]) : undefined;
}

export function resolvedQueueState(input: {
  sheets: { status: string }[];
  batchStatuses: string[];
  errored: boolean;
}): Extract<UploadQueueState, "attention" | "ready" | "failed"> {
  if (input.errored) return "failed";
  if (input.sheets.some((sheet) => isFailedUploadStatus(sheet.status))) return "failed";
  if (input.batchStatuses.some((status) => isFailedUploadStatus(status))) return "failed";
  if (!input.sheets.length) return "ready";
  return shouldAutoOpenReview(input.sheets) ? "attention" : "ready";
}
