/**
 * AR04/AR05: the question-catalog chatbot on the Analysis & Report page. No AI:
 * pick a question from the menu or type it (keywords + live names fill its
 * details); the bot asks for a missing detail with chips.
 *
 * The asks live in the workspace, so a filter change (which reloads the
 * report) keeps every card. Each card keeps the filters it was asked with and
 * is never refetched. The conversation stays readable, oldest first; a
 * chip answers its own turn; one "Showing:" divider marks where a turn's month or filters differ from the turn before.
 */

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useIsFetching, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, MessageSquare } from "lucide-react";
import { assistantAnswerOptions, assistantQuestionsOptions } from "@/api/queries";
import { errorDetail } from "@/api/error-copy";
import { Skeleton } from "@/components/ui/skeleton";
import { AnswerCard, BUTTON } from "./AnswerCard";
import {
  filterLabel,
  newAsk,
  sameFilters,
  slotAnswer,
  type Ask,
  type LiveNames,
} from "./assistant-intents";
import { QuestionMenu } from "./QuestionMenu";
import { resolveGuideQuestion, resolveSlotChoice } from "./guide-conversation";
import { ReportCompanion } from "./ReportCompanion";
import { SupportingComparison } from "./SupportingComparison";
import "./report-chat.css";
import { answerSlide, type SlideSpec } from "./report-slides";
import type { AnalysisReportQuery, AssistantAnswer, AssistantQuestion } from "./report-types";

type OnAsk = (
  topic: Ask["topic"],
  target: string | null,
  query: AnalysisReportQuery,
  slots: Record<string, string>,
  said: string,
) => void;
type Props = {
  code: string;
  query: AnalysisReportQuery;
  live: LiveNames;
  asks: Ask[];
  onAsks(next: Ask[]): void;
  onAddToSlides(s: SlideSpec): void;
};

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]";

export function AssistantPanel({ code, query, live, asks, onAsks, onAddToSlides }: Props) {
  const [text, setText] = useState("");
  const [focus, setFocus] = useState<{ id: number; announce: boolean } | null>(null);
  const [announce, setAnnounce] = useState("");
  const [clarification, setClarification] = useState<string | null>(null);
  const catalog = useQuery(assistantQuestionsOptions(code));
  const questions = catalog.data?.questions ?? [];
  const client = useQueryClient();
  const fetching = useIsFetching({ queryKey: ["analysis", "ask", code.toUpperCase()] });
  const activity = fetching ? "checking" : text.trim() ? "composing" : "ready";
  const labelOf = (id: string) => questions.find((x) => x.id === id)?.label ?? id;
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const newestMonth = live.months[0] ?? null;

  // A new turn scrolls into view (instantly under reduced motion); opening an old one does not.
  useEffect(() => {
    if (focus?.announce) scrollTurn(listRef.current, focus.id);
  }, [focus]);

  const previousAsk = asks.at(-1);
  const previous = previousAsk?.topic
    ? {
        ask: previousAsk,
        answer: client.getQueryData<AssistantAnswer>(
          assistantAnswerOptions(code, {
            ...previousAsk.query,
            topic: previousAsk.topic,
            target: previousAsk.target,
            ...previousAsk.slots,
          }).queryKey,
        ),
      }
    : undefined;
  const guess =
    text.trim() && catalog.data
      ? resolveGuideQuestion(text, catalog.data, live, query, previous)
      : null;

  const ask: OnAsk = (topic, target, q, slots, said) => {
    setClarification(null);
    const next = newAsk(asks, topic, target, q, slots, said);
    next[next.length - 1].controlQuery = query;
    onAsks(next);
    setFocus({ id: next.at(-1)!.id, announce: true });
  };
  const pick = (q: AssistantQuestion) => ask(q.id, null, query, {}, q.label);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    const pending = previous?.answer?.status === "needs_slot" ? previous.answer.slot : null;
    const choice = pending ? resolveSlotChoice(text, pending) : null;
    if (
      pending &&
      choice &&
      previous &&
      sameFilters(previous.ask.controlQuery ?? previous.ask.query, query, newestMonth)
    ) {
      onAsks(slotAnswer(asks, previous.ask.id, pending.name, choice.value, choice.label));
      setFocus({ id: previous.ask.id, announce: true });
    } else {
      const m = catalog.data
        ? resolveGuideQuestion(text, catalog.data, live, query, previous)
        : null;
      if (
        pending &&
        previous &&
        sameFilters(previous.ask.controlQuery ?? previous.ask.query, query, newestMonth) &&
        !m
      ) {
        setClarification(
          "I couldn’t identify a single choice. Type its full name from the choices above, or select one.",
        );
        inputRef.current?.focus();
        return;
      }
      ask(m?.id ?? null, m?.target ?? null, m?.query ?? query, m?.slots ?? {}, text.trim());
    }
    setText("");
  };

  return (
    <section
      className="panel guide-chat min-w-0"
      aria-label="Ask about this month"
      data-testid="assistant"
    >
      <div className="guide-toolbar">
        <div className="guide-toolbar-identity">
          <ReportCompanion activity={activity} />
          <div>
            <h3 className="text-lg font-bold">Talk through your report</h3>
            <p className="mt-1 text-sm text-muted-foreground">{filterLabel(query, newestMonth)}</p>
          </div>
        </div>
        <div className="min-w-0">
          {catalog.isPending ? (
            <div className="grid gap-2" role="status">
              <span className="sr-only">Loading the questions</span>
              <Skeleton className="h-11 w-full" />
            </div>
          ) : catalog.isError ? (
            <div className="grid gap-2 text-sm">
              <p>Could not load the questions: {errorDetail(catalog.error)}</p>
              <button
                type="button"
                className={`${BUTTON} justify-self-start`}
                onClick={() => void catalog.refetch()}
              >
                Retry
              </button>
            </div>
          ) : (
            <QuestionMenu questions={questions} onPick={pick} />
          )}
        </div>
      </div>
      <div className="guide-thread grid min-w-0 content-start gap-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="guide-thread-label">
            <MessageSquare size={16} aria-hidden />{" "}
            {fetching ? "Checking your measurements…" : "Your conversation"}
          </p>
          {asks.length > 0 && (
            <button
              type="button"
              className={BUTTON}
              onClick={() => {
                // Nothing is saved, so no confirm; added slides stay in the deck.
                onAsks([]);
                setText("");
                setClarification(null);
                setFocus(null);
                setAnnounce(""); // so the next identical headline is announced again
                inputRef.current?.focus();
              }}
            >
              Clear chat
            </button>
          )}
        </div>
        {/* Only a newly asked card is announced; opening an older one is not. */}
        <p className="sr-only" aria-live="polite">
          {announce}
        </p>
        {asks.length === 0 && (
          <div className="guide-welcome">
            <h4 className="text-xl font-semibold">Let’s find what needs your attention.</h4>
            <p className="mt-2 max-w-[60ch] text-[15px] leading-relaxed text-muted-foreground">
              Ask about your measurements. I’ll explain the finding, walk you through the evidence
              and show the next check to make.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              {(
                [
                  ["summary", "What should I check first?"],
                  ["changes", "What changed since last month?"],
                  ["went_well", "What went well?"],
                ] as const
              ).map(([id, label]) => {
                const q = questions.find((q) => q.id === id);
                return (
                  q && (
                    <button
                      type="button"
                      key={id}
                      className={BUTTON}
                      onClick={() => ask(q.id, null, query, {}, label)}
                    >
                      {label}
                    </button>
                  )
                );
              })}
            </div>
          </div>
        )}
        <div ref={listRef} className="grid min-w-0 gap-3">
          {asks.map((a, i) => {
            const moved = i > 0 && !sameFilters(asks[i - 1].query, a.query, newestMonth);
            const props = {
              ask: a,
              collapsed: false,
              focus: focus?.id === a.id,
              onFocused: (headline: string) => {
                if (focus?.announce) {
                  setAnnounce(headline);
                  scrollTurn(listRef.current, a.id); // again: the answer is taller than its skeleton
                }
                setFocus(null);
              },
              onExpand: () => {
                setFocus({ id: a.id, announce: false });
              },
            };
            return (
              <div
                key={a.id}
                data-turn={a.id}
                className="guide-turn grid min-w-0 scroll-mt-20 scroll-mb-36 gap-5"
              >
                {moved && (
                  <p className="flex items-center gap-3 text-xs text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">
                    {/* Neutral: a typed month or an old card's follow-up moves it too, not only the filter bar. */}
                    {`Showing: ${filterLabel(a.query, newestMonth)}`}
                  </p>
                )}
                {a.said && (
                  <p className="guide-user grid max-w-[85%] justify-self-end rounded-lg bg-[var(--surface-2)] px-4 py-3 text-sm break-words">
                    <span className="text-xs text-muted-foreground">You asked</span>
                    {a.said}
                  </p>
                )}
                {a.topic ? (
                  <AskCard
                    {...props}
                    code={code}
                    topic={a.topic}
                    name={labelOf(a.topic)}
                    onAsk={ask}
                    onSlot={(slot, value, label) => {
                      onAsks(slotAnswer(asks, a.id, slot, value, label));
                      setFocus({ id: a.id, announce: true });
                    }}
                    onAddToSlides={(s) => {
                      onAsks(asks.map((x) => (x.id === a.id ? { ...x, added: true } : x)));
                      onAddToSlides(s);
                    }}
                  />
                ) : (
                  <HelpCard {...props} />
                )}
              </div>
            );
          })}
        </div>
        {/* Pinned under the chat so the next question is always one tap away. */}
        <form
          className="guide-composer sticky bottom-0 z-10 flex flex-wrap items-end gap-2"
          onSubmit={submit}
        >
          <label className="grid min-w-0 flex-1 basis-60 gap-1 text-xs text-muted-foreground">
            Ask your report guide
            <input
              ref={inputRef}
              className={`min-h-11 rounded-md border border-border bg-transparent px-3 text-sm text-foreground ${FOCUS}`}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setClarification(null);
              }}
              placeholder="What needs attention this month?"
              aria-describedby="assistant-guess"
            />
          </label>
          <button
            type="submit"
            className={`${BUTTON} guide-send`}
            disabled={!text.trim() || catalog.isPending}
          >
            <ArrowUp size={18} aria-hidden /> Ask
          </button>
          {clarification && (
            <p role="status" className="basis-full text-sm text-muted-foreground">
              {clarification}
            </p>
          )}
          <p id="assistant-guess" className="basis-full text-xs text-muted-foreground">
            {guess
              ? `Will answer: ${[labelOf(guess.id), ...Object.values(guess.slots)].join(" · ")}`
              : text.trim()
                ? "Try naming the model, colour or month, or explore the available topics."
                : "Answers use your plant’s recorded measurements and standards."}
          </p>
        </form>
      </div>
    </section>
  );
}

function scrollTurn(list: HTMLElement | null, id: number) {
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  list
    ?.querySelector(`[data-turn="${id}"] [data-headline]`)
    ?.scrollIntoView?.({ block: "start", behavior: reduce ? "auto" : "smooth" });
}

type CardProps = {
  ask: Ask;
  collapsed: boolean;
  focus: boolean;
  onFocused(headline: string): void;
  onExpand(): void;
};

/** Moves focus to the card's headline once it has one (after loading). */
function useFocusHeadline(focus: boolean, onFocused: (headline: string) => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = focus ? ref.current?.querySelector<HTMLElement>("[data-headline]") : null;
    if (h) {
      // Someone already typing the next question keeps the input; the live region still announces.
      const typing =
        document.activeElement instanceof HTMLInputElement && !!document.activeElement.value;
      if (!typing) h.focus({ preventScroll: true }); // the panel scrolls the turn in
      onFocused(h.textContent ?? "");
    }
  });
  return ref;
}

function AskCard({
  code,
  topic,
  name,
  ask,
  collapsed,
  focus,
  onFocused,
  onExpand,
  onAsk,
  onSlot,
  onAddToSlides,
}: CardProps & {
  code: string;
  topic: NonNullable<Ask["topic"]>;
  name: string;
  onAsk: OnAsk;
  onSlot: (slot: string, value: string, label: string) => void;
  onAddToSlides: (s: SlideSpec) => void;
}) {
  // The query it was asked with, never the current one: a filter change does not refetch.
  const q = useQuery(
    assistantAnswerOptions(code, {
      ...ask.query,
      topic,
      target: ask.target,
      ...ask.slots,
    }),
  );
  const ref = useFocusHeadline(focus, onFocused);
  return (
    <div ref={ref} className="min-w-0">
      {q.isPending ? (
        <div className="panel grid gap-2 p-4 sm:p-5" role="status">
          <span className="sr-only">Working out: {name}</span>
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-3/5" />
        </div>
      ) : q.isError ? (
        <div className="panel grid gap-2 p-4 sm:p-5">
          <p tabIndex={-1} data-headline="" className={`font-semibold ${FOCUS}`}>
            Could not answer "{name}"
          </p>
          <p className="text-sm text-muted-foreground">{errorDetail(q.error)}</p>
          <button
            type="button"
            className={`${BUTTON} justify-self-start`}
            onClick={() => void q.refetch()}
          >
            Retry
          </button>
        </div>
      ) : (
        <AnswerCard
          answer={q.data}
          referenceMonth={ask.topic === "compare_months" ? ask.slots?.month2 : undefined}
          stale={null}
          collapsed={collapsed}
          added={Boolean(ask.added)}
          onExpand={onExpand}
          onFollowup={(f) => onAsk(f.topic, f.target, ask.query, {}, f.label)}
          onSlot={onSlot}
          onAddToSlides={() => onAddToSlides(answerSlide(q.data))}
          comparison={
            q.data.topic === "summary" &&
            q.data.status !== "needs_slot" &&
            q.data.status !== "not_enough_data" ? (
              <SupportingComparison code={code} answer={q.data} />
            ) : undefined
          }
        />
      )}
    </div>
  );
}

function HelpCard({ collapsed, focus, onFocused, onExpand }: CardProps) {
  const ref = useFocusHeadline(focus, onFocused);
  const title = "Let’s make that question more specific.";
  return (
    <div ref={ref} className="min-w-0">
      {collapsed ? (
        <button
          type="button"
          className={`panel flex min-h-11 w-full items-center px-4 py-2 text-left text-sm font-semibold sm:px-5 ${FOCUS}`}
          onClick={onExpand}
        >
          {title}
        </button>
      ) : (
        <article className="panel grid gap-3 p-4 sm:p-5">
          <h3 tabIndex={-1} data-headline="" className={`text-lg font-bold ${FOCUS}`}>
            {title}
          </h3>
          <p className="text-sm text-muted-foreground">
            I couldn’t match that to a report question. Try “What needs attention?”, name a model or
            colour, or ask “What changed since last month?”. Explore topics shows everything I can
            check.
          </p>
        </article>
      )}
    </div>
  );
}
