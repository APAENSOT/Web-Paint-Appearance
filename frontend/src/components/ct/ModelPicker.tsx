import { useState } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { ChevronDown } from "lucide-react";
import { ModelCard, RANGER_IGNITE_IMG, type ModelCardData } from "./ModelCard";

/**
 * Model picker — vehicle-select section for the plant dashboard
 * (Sixt "Choose your vehicle" reference).
 *
 * Concept: the operator picks which vehicle model + paint colour to inspect.
 * Each card = one colour record: this month's score, the delta vs last month,
 * and how many data uploads that colour received this month. Sort cycles
 * BEST VALUE / LOW VALUE (highest paint score first vs lowest first).
 *
 * Function note: demo cards live in CARDS — swap for real feed data and lift
 * `sort` to the route when wiring; cards route into a per-colour dashboard.
 */

const SORTS = ["BEST VALUE", "LOW VALUE"] as const;
type Sort = (typeof SORTS)[number];

const CARDS: ModelCardData[] = [
  {
    id: "ranger-ignite-orange",
    title: "Ford P703 Ranger",
    metric: "Wave Scan",
    color: "Ignite Orange",
    accent: "#e4601c",
    pct: 96.4,
    delta: 10,
    uploads: 24,
    image: RANGER_IGNITE_IMG,
  },
  {
    id: "ranger-arctic-white",
    title: "Ford P703 Ranger",
    metric: "Film Thickness",
    color: "Arctic White",
    accent: "#7d9dbd",
    pct: 88.1,
    delta: -4.2,
    uploads: 17,
    image: RANGER_IGNITE_IMG,
  },
];

export function ModelPicker() {
  const [sort, setSort] = useState<Sort>("BEST VALUE");
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { code } = useParams({ from: "/plant/$code" });

  const now = new Date();
  const month = now.toLocaleString("en-US", { month: "long" });
  const prevMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1).toLocaleString("en-US", {
    month: "long",
  });

  const cards = [...CARDS].sort((a, b) => (sort === "BEST VALUE" ? b.pct - a.pct : a.pct - b.pct));
  const MODEL_COUNT = cards.length;

  return (
    <section
      className="panel animate-rise flex min-h-[420px] flex-col px-5 py-4"
      style={{ animationDelay: "80ms" }}
    >
      {/* header row — title + count ···················· sort */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-baseline gap-2.5">
          <h2 className="text-xl font-bold tracking-tight">Choose your Model</h2>
          <span className="eyebrow">{MODEL_COUNT} AVAILABLE</span>
        </div>

        {/* sort dropdown — minimal, uppercase, chevron like the filter panel */}
        <div className="relative">
          <div className="flex items-center gap-3">
            <span className="eyebrow">Sort by</span>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              aria-haspopup="listbox"
              className="flex items-center gap-2 border-b border-border pb-1 transition-colors hover:border-foreground"
            >
              <span className="text-xs font-bold tracking-[0.08em]">{sort} FIRST</span>
              <ChevronDown
                className="size-3.5 text-muted-foreground transition-transform duration-200"
                style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
              />
            </button>
          </div>

          {open && (
            <ul
              role="listbox"
              aria-label="Sort models"
              className="absolute right-0 z-20 mt-2 w-44 overflow-hidden rounded-[var(--radius-sm)] border border-border"
              style={{ backgroundColor: "var(--panel-raised)" }}
            >
              {SORTS.map((s) => {
                const on = s === sort;
                return (
                  <li key={s}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={on}
                      onClick={() => {
                        setSort(s);
                        setOpen(false);
                      }}
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-bold tracking-[0.08em] transition-colors hover:bg-[var(--surface-2)]"
                      style={{ color: on ? "var(--primary)" : "var(--muted-foreground)" }}
                    >
                      {s} FIRST
                      {on && (
                        <span
                          className="size-1.5 rounded-full"
                          style={{ backgroundColor: "var(--primary)" }}
                        />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {/* model / colour cards — staggered rise-in; gradient rule under header */}
      <div
        aria-hidden
        className="mt-4 h-px"
        style={{
          background:
            "linear-gradient(90deg, var(--color-primary), var(--color-border) 45%, transparent)",
        }}
      />
      <div className="grid gap-3 pt-4 sm:grid-cols-2 xl:grid-cols-3">
        {cards.map((c, i) => (
          <div
            key={`${sort}-${c.id}`}
            className="animate-rise"
            style={{ animationDelay: `${i * 90}ms` }}
          >
            <ModelCard
              data={c}
              month={month}
              prevMonth={prevMonth}
              onSelect={(id) =>
                navigate({ to: "/plant/$code/model/$modelId", params: { code, modelId: id } })
              }
            />
          </div>
        ))}
      </div>
    </section>
  );
}
