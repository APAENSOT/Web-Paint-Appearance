/**
 * AR05 limit card: one definition-list row per layer and orientation (label, then its limits);
 * the table below carries the same limits per box.
 */

import type { AssistantAnswer } from "../report-types";
import { EvidenceTable } from "./Table";

type Evidence = AssistantAnswer["evidence"];

export function LimitCard({ evidence }: { evidence: Evidence }) {
  const card = evidence.card ?? [];
  if (!card.length) return <EvidenceTable evidence={evidence} caption="Limits per box" />;
  return (
    <div className="max-w-full overflow-x-auto">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {card.map((c) => (
          <div key={c.label} className="contents">
            <dt className="font-medium">{c.label}</dt>
            <dd className="text-muted-foreground">{c.value}</dd>
          </div>
        ))}
      </dl>
      <EvidenceTable evidence={evidence} caption="Limits per box" />
    </div>
  );
}
