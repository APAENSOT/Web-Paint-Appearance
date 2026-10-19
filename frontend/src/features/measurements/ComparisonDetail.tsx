import { useRef } from "react";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, XAxis, YAxis } from "recharts";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import type { components } from "@/api/types";
import type { Points } from "./comparison-state";
import { vehicleLabel } from "./comparison-state";
import { pointText, usePointLabels } from "./point-labels";
export function ReadingSource({
  reading: r,
  point,
}: {
  reading: components["schemas"]["ComparisonReading"];
  /** D-RO17-16: the point as "label (code)", when the caller knows it. */
  point?: string;
}) {
  return (
    <span className="cv-source">
      {Object.entries({
        Point: point,
        Measurement: r.measurement_id,
        // D-RO17-16: the plant's own raw label of this reading, not the code.
        "Original panel": r.src_zone_text,
        "Original location": r.src_location_text,
        File: r.source_file,
        Sheet: r.source_sheet,
        Row: r.source_row,
        Load: r.load_id,
      })
        .filter(([, v]) => v != null)
        .map(([key, value]) => (
          <span key={key}>
            {key}: {value}
          </span>
        ))}
    </span>
  );
}
const shapes = [
  "circle",
  "square",
  "triangle",
  "diamond",
  "cross",
  "star",
  "wye",
  "square",
] as const;
export function ComparisonDetail({
  data,
  code,
  onClose,
  columnStart,
}: {
  data: Points;
  code: string | null;
  onClose: () => void;
  columnStart: number;
}) {
  const returnFocus = useRef<HTMLElement | null>(null);
  const row = data.locations.find((location) => location.code === code);
  const labelOf = usePointLabels(data.plant_code);
  const point =
    row &&
    pointText(
      labelOf(data.domain === "FILMTHICKNESS" ? "film" : "wavescan", data.model, row.code),
      row.code,
    );
  return (
    <Dialog
      open={!!row}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        className="cv-detail"
        onOpenAutoFocus={() => {
          returnFocus.current = document.activeElement as HTMLElement;
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocus.current?.focus();
        }}
      >
        <DialogTitle>
          {point} · {data.metric}
        </DialogTitle>
        <DialogDescription>
          Raw readings for the visible vehicles. Orientation: {row?.orientation ?? "unproved"}.
        </DialogDescription>
        {row && (
          <>
            <div
              className="cv-plot"
              role="img"
              aria-label={`${point} ${data.metric} dot plot; exact values and sources listed below`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 15, right: 25, bottom: 25, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    dataKey="value"
                    name={data.metric}
                    domain={["auto", "auto"]}
                    label={{ value: data.metric, position: "bottom" }}
                  />
                  <YAxis
                    type="number"
                    dataKey="vehicle"
                    domain={[0.5, data.columns.length + 0.5]}
                    ticks={data.columns.map((_, i) => i + 1)}
                    tickFormatter={(n) => `Vehicle ${columnStart + n}`}
                    width={72}
                  />
                  {row.cells.map((cell, i) => (
                    <Scatter
                      key={cell.vehicle_id}
                      name={`Vehicle ${columnStart + i + 1}: ${vehicleLabel(data.columns[i])}`}
                      shape={shapes[i]}
                      fill="var(--color-primary)"
                      data={cell.readings.map((reading, j) => ({
                        value: Number(reading.value),
                        // Separate duplicate symbols inside the labelled vehicle lane.
                        vehicle:
                          i +
                          1 +
                          (cell.readings.length === 1
                            ? 0
                            : (j / (cell.readings.length - 1) - 0.5) * 0.24),
                      }))}
                    />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <div className="cv-detail-values">
              {row.cells.map((cell, i) => (
                <section key={cell.vehicle_id}>
                  <h3>
                    Vehicle {columnStart + i + 1} · {vehicleLabel(data.columns[i])}
                  </h3>
                  <p className="cv-muted">
                    {data.columns[i].measured_date} ·{" "}
                    {data.columns[i].color ?? "Colour not recorded"}
                  </p>
                  {cell.missing ? (
                    <p>Not measured</p>
                  ) : (
                    cell.readings.map((reading, j) => (
                      <div className="cv-reading" key={j}>
                        <strong className="num">{reading.value}</strong>
                        <ReadingSource reading={reading} point={point} />
                      </div>
                    ))
                  )}
                </section>
              ))}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
