import { useQuery } from "@tanstack/react-query";
import { assistantAnswerOptions } from "@/api/queries";
import { EvidenceChart } from "./charts";
import { EvidenceTable } from "./charts/Table";
import { monthWords } from "./report-slides";
import type { AssistantAnswer } from "./report-types";

/** A summary includes the existing comparison calculation without another question or click. */
export function SupportingComparison({ code, answer }: { code: string; answer: AssistantAnswer }) {
  const comparison = useQuery({
    ...assistantAnswerOptions(code, {
      topic: "changes",
      month: answer.month ?? undefined,
      domain: answer.domain,
      models: answer.models,
      colors: answer.colors,
    }),
    enabled: Boolean(answer.month && answer.previous_month),
  });
  if (!answer.previous_month)
    return (
      <p className="text-sm text-muted-foreground">
        There is no earlier month available for comparison with this selection.
      </p>
    );
  if (comparison.isPending)
    return (
      <p role="status" className="text-sm text-muted-foreground">
        I’m also checking what changed from {monthWords(answer.previous_month)}…
      </p>
    );
  if (comparison.isError)
    return (
      <div className="guide-caveats">
        <p>The current-month finding is ready. I couldn’t load its month comparison.</p>
        <button
          type="button"
          className="mt-2 min-h-11 underline underline-offset-4"
          onClick={() => void comparison.refetch()}
        >
          Retry month comparison
        </button>
      </div>
    );
  const other = comparison.data;
  const chart = EvidenceChart({
    evidence: other.evidence,
    periods: { before: monthWords(answer.previous_month), now: monthWords(answer.month!) },
  });
  return (
    <section
      className="guide-evidence min-w-0"
      aria-label="Automatic month comparison"
      data-testid="supporting-comparison"
    >
      <div className="mb-4 grid gap-2">
        <h4 className="font-semibold">Here’s what changed</h4>
        <p className="text-sm text-muted-foreground">
          {monthWords(answer.previous_month)} to {monthWords(answer.month!)}
        </p>
        <p className="max-w-[70ch] text-[15px] leading-relaxed">
          {other.explanation || other.decision.headline}
        </p>
      </div>
      {chart ??
        (other.evidence.rows.length ? (
          <div className="overflow-x-auto">
            <EvidenceTable evidence={other.evidence} caption="Month comparison measurements" />
          </div>
        ) : null)}
      {other.proof && chart && (
        <p className="guide-takeaway">
          <strong>What stands out: </strong>
          {other.proof}
        </p>
      )}
      {other.method.caveats.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-sm text-muted-foreground">
          {other.method.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
