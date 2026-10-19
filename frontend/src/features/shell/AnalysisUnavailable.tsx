import { ChartNoAxesCombined } from "lucide-react";

export function AnalysisUnavailable() {
  return (
    <section>
      <h1 className="text-3xl font-semibold tracking-tight">Analysis</h1>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
        Raw CF trends and distributions will be available in a later release. Open a plant workspace
        to inspect recorded measurements.
      </p>
      <div className="panel mt-7 max-w-3xl p-6 sm:p-8">
        <ChartNoAxesCombined aria-hidden="true" className="mb-5 size-7 text-muted-foreground" />
        <h2 className="text-xl font-semibold">Grading unavailable</h2>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Grouping and colour-family mapping remain unresolved. Graded analysis will be available
          once those decisions are approved.
        </p>
      </div>
    </section>
  );
}
