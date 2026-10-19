/**
 * AR05: "What can I ask?" — every catalog question, grouped by job in registry
 * order. A left column from 1024 px; below that a sheet that opens above the thread.
 */

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { AssistantQuestion } from "./report-types";

const GROUPS: [AssistantQuestion["group"], string][] = [
  ["month", "This month"],
  ["compare", "Compare"],
  ["problem", "Find the problem"],
  ["trend", "Trend and risk"],
  ["appearance", "Appearance and layers"],
  ["data", "Data and standards"],
];
const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]";

export function QuestionMenu({
  questions,
  onPick,
}: {
  questions: AssistantQuestion[];
  onPick(q: AssistantQuestion): void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  return (
    <nav ref={root} className="grid min-w-0 content-start gap-2" aria-label="What can I ask?">
      <button
        ref={trigger}
        type="button"
        aria-label="Explore topics"
        className={`flex min-h-11 items-center justify-between gap-2 rounded-md border border-border px-3 text-sm font-semibold ${FOCUS}`}
        aria-expanded={open}
        aria-controls="question-menu"
        onClick={() => setOpen(!open)}
      >
        <span className="hidden sm:inline">Explore topics</span>
        <ChevronDown
          className={`size-4 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>
      <div id="question-menu" className={`${open ? "grid" : "hidden"} guide-topics gap-5`}>
        {GROUPS.map(([group, heading]) => (
          <section key={group} className="grid gap-1" aria-label={heading}>
            <h4 className="text-sm font-semibold text-muted-foreground">{heading}</h4>
            {questions
              .filter((q) => q.group === group)
              .map((q) => (
                <button
                  key={q.id}
                  type="button"
                  data-question={q.id}
                  className={`min-h-11 rounded-md px-3 py-2 text-left text-sm hover:bg-[var(--surface-2)] ${FOCUS}`}
                  onClick={() => {
                    setOpen(false);
                    onPick(q);
                  }}
                >
                  {q.label}
                </button>
              ))}
          </section>
        ))}
      </div>
    </nav>
  );
}
