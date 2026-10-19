import type { components } from "../../api/types";

export function PointDetails({
  seriesKey,
  point,
}: {
  seriesKey: string;
  point: components["schemas"]["PreviewPoint"];
}) {
  return (
    <div
      role="tooltip"
      className="rounded-md border border-border bg-popover p-3 text-sm text-popover-foreground shadow-md"
    >
      <p className="font-semibold">{seriesKey}</p>
      <p>{point.measured_date}</p>
      <p>
        {point.plant} / {point.model} / {point.color} / {point.checkzone}
      </p>
      <p className="mt-2 font-mono">CF {point.cf}</p>
    </div>
  );
}
