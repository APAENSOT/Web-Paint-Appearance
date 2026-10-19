import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { useCallback, useState } from "react";
import { ModelStage } from "@/components/ct/ModelStage";
import { HotspotDetail } from "@/components/ct/HotspotDetail";
import { BoxplotCard } from "@/components/ct/ColourDashPanels";
import {
  BOXPLOT_HORIZONTAL,
  BOXPLOT_VERTICAL,
  COLOUR_SUMMARIES,
  DEFAULT_SUMMARY,
  HOTSPOTS,
} from "@/lib/ct/hotspots";

export function ColourDashboard({ code, modelId }: { code: string; modelId: string }) {
  const name = modelId.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const summary = COLOUR_SUMMARIES.find((s) => s.modelId === modelId) ?? DEFAULT_SUMMARY;
  const monthLabel = "Sample data";
  const [selectedId, setSelectedId] = useState(HOTSPOTS[0].id);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const spot = HOTSPOTS.find((s) => s.id === selectedId) ?? HOTSPOTS[0];

  const selectIfOnModel = useCallback((id: string) => {
    if (HOTSPOTS.some((s) => s.id === id)) setSelectedId(id);
  }, []);

  const step = useCallback((dir: number) => {
    setSelectedId((cur) => {
      const i = HOTSPOTS.findIndex((s) => s.id === cur);
      const next = (i + dir + HOTSPOTS.length) % HOTSPOTS.length;
      return HOTSPOTS[next].id;
    });
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="p-3 lg:p-4">
        <div className="panel animate-rise flex items-center gap-4 px-5 py-4">
          <Link
            to="/plant/$code"
            params={{ code }}
            className="flex size-11 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border border-border text-muted-foreground transition-colors hover:text-foreground"
            aria-label="Back to plant dashboard"
          >
            <ArrowLeft className="size-4" />
          </Link>
          <div>
            <p className="eyebrow flex items-center gap-1.5 leading-tight">
              <Link to="/" className="transition-colors hover:text-foreground">
                Network
              </Link>
              <span aria-hidden>/</span>
              <Link
                to="/plant/$code"
                params={{ code }}
                className="transition-colors hover:text-foreground"
              >
                {code.toUpperCase()}
              </Link>
              <span aria-hidden>/</span>
              <span className="text-foreground">Colour Dashboard</span>
            </p>
            <h1 className="mt-0.5 text-2xl font-bold leading-tight tracking-tight">{name}</h1>
          </div>
          <span
            className="ml-auto hidden rounded-full px-3 py-1 text-xs font-bold tracking-[0.08em] sm:block"
            style={{
              color: summary.accent,
              background: `color-mix(in oklab, ${summary.accent} 12%, transparent)`,
            }}
          >
            {summary.color.toUpperCase()}
          </span>
        </div>
      </header>

      <main className="flex-1 px-3 pb-3 lg:px-4 lg:pb-4">
        <aside className="panel mb-3 p-4 text-sm" aria-label="Design preview notice">
          <p className="font-semibold">Design preview · Sample data</p>
          <p className="mt-1 text-muted-foreground">
            These measurements and statuses are illustrative. Use the plant dashboard for measured
            results.
          </p>
          <Link
            to="/plant/$code"
            params={{ code }}
            className="mt-2 inline-flex min-h-11 items-center text-primary underline underline-offset-4"
          >
            Open plant dashboard
          </Link>
        </aside>
        <div className="grid gap-3 lg:grid-cols-[280px_minmax(0,1fr)_420px]">
          <div className="self-start lg:sticky lg:top-4">
            <HotspotDetail spot={spot} />
          </div>

          <section
            className="panel animate-rise relative min-h-[420px] overflow-hidden lg:min-h-[560px]"
            style={{
              animationDelay: "80ms",
              background: "linear-gradient(180deg, var(--panel-raised) 0%, var(--surface-2) 130%)",
            }}
            aria-label="3D vehicle model — drag to rotate"
            tabIndex={0}
            onKeyDown={(event) => {
              if (
                event.target !== event.currentTarget ||
                event.altKey ||
                event.ctrlKey ||
                event.metaKey
              )
                return;
              if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                event.preventDefault();
                step(event.key === "ArrowRight" ? 1 : -1);
              }
            }}
          >
            <p className="eyebrow pointer-events-none absolute left-5 top-4 z-10">
              Drag to rotate · Scroll to zoom · ← / → to step points
            </p>
            <ModelStage
              accent={summary.accent}
              selectedId={selectedId}
              highlightId={hoverId}
              onSelect={setSelectedId}
              onHover={setHoverId}
            />
          </section>

          <div className="flex min-h-[420px] flex-col gap-3 lg:min-h-[560px]">
            <BoxplotCard
              title="Horizontal Zone"
              series={BOXPLOT_HORIZONTAL}
              month={monthLabel}
              delay="120ms"
              selectedId={selectedId}
              onSelect={selectIfOnModel}
              onHover={setHoverId}
            />
            <BoxplotCard
              title="Vertical Zone"
              series={BOXPLOT_VERTICAL}
              month={monthLabel}
              delay="180ms"
              selectedId={selectedId}
              onSelect={selectIfOnModel}
              onHover={setHoverId}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
