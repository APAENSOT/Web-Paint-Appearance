/**
 * AR04: one assistant answer, decision first (spec section 4).
 *
 * AR06: headline, plain explanation, the graph open (or its table when it draws nothing), next
 * step, risk and confidence; proof, evidence table and method fold under "Numbers and method".
 * Decision, proof, next step, risk and confidence are API fields shown as sent.
 * Counts only, never a share.
 */

import { useState, type ReactNode } from "react";
import { ArrowRight, ChevronRight, Plus } from "lucide-react";
import { StatusChip, type Code } from "./AnalysisReportView";
import { EvidenceChart, OWN_TABLE, TOP } from "./charts";
import { evidenceCell, riskLine, monthWords } from "./report-slides";
import type { AssistantAnswer, AssistantFollowup, AssistantSlot } from "./report-types";
import { evidenceReading } from "./guide-evidence";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]";
export const BUTTON =
  "inline-flex min-h-11 items-center gap-2 rounded-md border border-border px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50";
const SUMMARY = `inline-flex min-h-11 cursor-pointer items-center gap-1.5 font-semibold ${FOCUS}`;

type Props = {
  answer: AssistantAnswer;
  stale: string | null;
  collapsed: boolean;
  added: boolean;
  onExpand(): void;
  onFollowup(f: AssistantFollowup): void;
  /** A tapped choice for a missing detail: ask again with that slot set. */
  onSlot(name: string, value: string, label: string): void;
  onAddToSlides(): void;
  comparison?: ReactNode;
  referenceMonth?: string;
};

/** One chip per valid choice for the missing detail (needs_slot). */
export function SlotChips({ slot, onSlot }: { slot: AssistantSlot; onSlot: Props["onSlot"] }) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label={slot.prompt}>
      {slot.choices.map((c) => (
        <button
          key={c.value}
          type="button"
          className={BUTTON}
          data-choice={c.value}
          onClick={() => onSlot(slot.name, c.value, c.label)}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}

function Chip({ answer }: { answer: AssistantAnswer }) {
  // Only summary and colours grade the month; elsewhere all clear means "nothing found", not Pass.
  if (answer.status === "all_clear")
    return answer.topic === "summary" || answer.topic === "colours" ? (
      <StatusChip code="PASS" word="All clear" />
    ) : (
      <StatusChip
        code={null}
        word={answer.topic === "changes" ? "No change" : "Nothing stands out"}
      />
    );
  if (answer.status === "not_enough_data") return <StatusChip code={null} word="Not enough data" />;
  return answer.decision.status_code ? (
    <StatusChip code={answer.decision.status_code as Code} />
  ) : null;
}

export function AnswerCard({
  answer,
  stale,
  collapsed,
  added,
  onExpand,
  onFollowup,
  onSlot,
  onAddToSlides,
  comparison,
  referenceMonth,
}: Props) {
  const staleLine = stale && (
    <p className="text-xs text-muted-foreground" data-stale="">
      For {stale}
    </p>
  );
  if (collapsed)
    return (
      <article className="panel min-w-0" data-answer={answer.topic}>
        <button
          type="button"
          className="flex min-h-11 w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] sm:px-5"
          onClick={onExpand}
          aria-label={`Show answer: ${answer.decision.headline}`}
        >
          <Chip answer={answer} />
          <span className="min-w-0 font-semibold">{answer.decision.headline}</span>
          {staleLine}
        </button>
      </article>
    );

  // The bot asks for a missing detail: its prompt and the live choices, nothing else.
  if (answer.status === "needs_slot" && answer.slot)
    return (
      <article className="panel grid min-w-0 gap-3 p-4 sm:p-5" data-answer={answer.topic}>
        {staleLine}
        <h3 tabIndex={-1} data-headline="" className={`min-w-0 text-lg font-bold ${FOCUS}`}>
          {answer.slot.prompt}
        </h3>
        <SlotChips slot={answer.slot} onSlot={onSlot} />
      </article>
    );

  const { method, risk, evidence } = answer;
  const months =
    answer.topic === "compare_months" && answer.month && referenceMonth
      ? [answer.month, referenceMonth].sort()
      : null;
  const reference = months?.[0] ?? answer.previous_month;
  const current = months?.[1] ?? answer.month;
  const chart = EvidenceChart({
    evidence,
    periods:
      reference && current
        ? { before: monthWords(reference), now: monthWords(current) }
        : undefined,
  });
  const rows = evidence.rows.length > 0;
  // A chart that drew nothing leaves the numbers open in its place, never only in the fold.
  const tableOpen = !chart && rows;
  const tableFolded = !!chart && rows && !OWN_TABLE.has(evidence.kind ?? "");
  const [chartTitle, chartHelp] = evidenceReading(evidence);
  return (
    <article className="guide-answer grid min-w-0 gap-4" data-answer={answer.topic}>
      {staleLine}
      <p className="guide-speaker">Report guide</p>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Chip answer={answer} />
        <h3 tabIndex={-1} data-headline="" className={`min-w-0 text-lg font-bold ${FOCUS}`}>
          {answer.decision.headline}
        </h3>
      </div>
      {answer.explanation && (
        <p data-explanation="" className="max-w-[70ch] text-[15px] leading-relaxed">
          {answer.explanation}
        </p>
      )}
      {chart && (
        <figure className="guide-evidence min-w-0">
          <figcaption className="mb-4 grid gap-1">
            <h4 className="font-semibold">{chartTitle}</h4>
            <p className="max-w-[70ch] text-sm text-muted-foreground">{chartHelp}</p>
          </figcaption>
          {chart}
          {answer.proof && (
            <p className="guide-takeaway">
              <strong>What stands out: </strong>
              {answer.proof}
            </p>
          )}
        </figure>
      )}
      {tableOpen && <EvidenceRows evidence={evidence} />}
      {!chart && answer.proof && <p className="text-sm leading-relaxed">{answer.proof}</p>}
      {comparison}
      {answer.next_step && (
        <p className="guide-next flex items-start gap-3 text-sm">
          <ArrowRight className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            <span className="font-semibold">Next step:</span> {answer.next_step}
          </span>
        </p>
      )}
      {method.caveats.length > 0 && (
        <aside className="guide-caveats" aria-label="What to keep in mind">
          <p className="font-semibold">What to keep in mind</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {method.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </aside>
      )}
      {(risk || answer.confidence) && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          {risk && <span>{riskLine(risk)}</span>}
          {answer.confidence && (
            <span className="rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground">
              {answer.confidence === "solid" ? "Solid" : `Exploratory, n ${method.n}`}
            </span>
          )}
        </p>
      )}
      <details className="group min-w-0 text-sm">
        <summary className={SUMMARY}>
          <ChevronRight
            aria-hidden
            className="h-4 w-4 transition-transform group-open:rotate-90 motion-reduce:transition-none"
          />
          Numbers and method
        </summary>
        <div className="grid min-w-0 gap-2">
          {answer.proof && <p>{answer.proof}</p>}
          {tableFolded && <EvidenceRows evidence={evidence} />}
          <div className="grid gap-1 text-muted-foreground">
            <p>{method.rule}</p>
            <p>Looked at {method.n}.</p>
            {risk && <p>Risk uses {risk.basis}.</p>}
          </div>
        </div>
      </details>
      <div className="flex flex-wrap gap-2">
        {answer.followups.map((f) => (
          <button
            key={`${f.topic}|${f.target ?? ""}`}
            type="button"
            className={BUTTON}
            onClick={() => onFollowup(f)}
          >
            {f.label}
          </button>
        ))}
        {answer.status === "answer" && (
          <button
            type="button"
            className={`${BUTTON} sm:ml-auto`}
            disabled={added}
            onClick={onAddToSlides}
          >
            <Plus className="size-4" aria-hidden />
            {added ? "Added to slides" : "Slides"}
          </button>
        )}
      </div>
    </article>
  );
}

// ------------------------------------------------------------------ evidence
type Evidence = AssistantAnswer["evidence"];
const cell = evidenceCell;

function EvidenceRows({ evidence }: { evidence: Evidence }) {
  const [all, setAll] = useState(false);
  const { rows, columns } = evidence;
  const shown = all ? rows : rows.slice(0, TOP);
  return (
    <div className="grid min-w-0 gap-2 text-sm">
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">
            Evidence behind the answer{rows.length > TOP && !all ? ` (top ${TOP})` : ""}
          </caption>
          <thead className="bg-[var(--surface-2)] text-muted-foreground">
            <tr>
              {columns.map((h) => (
                <th key={h} scope="col" className="px-3 py-2 font-medium whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i} data-evidence-row="" className="border-t border-border">
                {r.map((c, j) => (
                  <td key={j} className={`px-3 py-2 ${typeof c === "number" ? "num" : ""}`}>
                    {cell(c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > TOP && (
        <button
          type="button"
          className={`${BUTTON} justify-self-start`}
          onClick={() => setAll(!all)}
        >
          {all ? `Show top ${TOP}` : `Show all ${rows.length}`}
        </button>
      )}
    </div>
  );
}
