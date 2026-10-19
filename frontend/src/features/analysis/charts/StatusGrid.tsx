/** AR05 status grid: boxes down, months across. Same cell as the heat map, so one renderer. */

import type { AssistantAnswer } from "../report-types";
import { Heatmap } from "./Heatmap";

export function StatusGrid({ evidence }: { evidence: AssistantAnswer["evidence"] }) {
  return <Heatmap evidence={evidence} />;
}
