import type { components } from "../../api/types";
type Preview = components["schemas"]["DashboardPreview"];

export function TruncationNotice({
  truncated,
  point_limit,
}: Pick<Preview, "truncated" | "point_limit">) {
  if (!truncated) return null;
  return (
    <p role="status" className="rounded-md border border-primary/40 bg-primary/10 p-4 text-sm">
      Preview capped at {point_limit} points. More measurements match these filters. Narrow the
      filters or date range to inspect a smaller selection.
    </p>
  );
}

export function GradingUnavailable({ grading_note }: Partial<Pick<Preview, "grading_note">>) {
  return (
    <aside aria-label="Grading unavailable" className="panel p-5">
      <h2 className="text-lg font-semibold">Grading unavailable</h2>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
        Raw measurements are available. Graded analysis awaits approved grouping and colour-family
        mapping.
      </p>
      {grading_note && (
        <blockquote className="mt-2 max-w-3xl border-l border-border pl-3 text-sm text-muted-foreground">
          {grading_note}
        </blockquote>
      )}
    </aside>
  );
}
