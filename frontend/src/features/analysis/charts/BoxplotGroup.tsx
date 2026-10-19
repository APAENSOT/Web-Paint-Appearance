/** AR05 boxplot group: one box per colour family on one scale. BoxplotPair's drawing, widened. */

import { BoxplotPair } from "./BoxplotPair";
import type { AssistantAnswer } from "../report-types";

export function BoxplotGroup({ evidence }: { evidence: AssistantAnswer["evidence"] }) {
  return <BoxplotPair evidence={evidence} width={Math.max(320, 90 * evidence.groups.length)} />;
}
