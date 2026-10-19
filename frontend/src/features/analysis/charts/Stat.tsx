/** AR05 stat: the first card row as one big number with its label; the rest as small lines. */

import type { AssistantAnswer } from "../report-types";
import { EvidenceTable } from "./Table";

type Evidence = AssistantAnswer["evidence"];

export function Stat({ evidence }: { evidence: Evidence }) {
  const [main, ...rest] = evidence.card ?? [];
  if (!main) return <EvidenceTable evidence={evidence} caption="Count" />;
  return (
    <div>
      <p className="text-4xl font-semibold tabular-nums" aria-label={`${main.label} ${main.value}`}>
        {main.value}
      </p>
      <p className="text-sm text-muted-foreground">{main.label}</p>
      {rest.map((c) => (
        <p key={c.label} className="mt-1 text-xs text-muted-foreground">
          {c.label}: {c.value}
        </p>
      ))}
      <EvidenceTable evidence={evidence} caption="Count" />
    </div>
  );
}
