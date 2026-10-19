import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { meOptions } from "@/api/queries";
import { mayCorrect } from "@/api/roles";
import { MeasurementCorrection } from "./MeasurementCorrection";
import { pointText, usePointLabels } from "./point-labels";
import { dayText } from "./day-text";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { components } from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
} from "@/components/ui/table";

type Measurement = components["schemas"]["MeasurementOut"];

function MeasurementRow({
  row,
  canCorrect,
  onNotice,
}: {
  row: Measurement;
  canCorrect: boolean;
  onNotice: (notice: string | Error) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const labelOf = usePointLabels(row.plant);
  return (
    <Fragment>
      <TableRow data-measurement-id={row.measurement_id}>
        <TableCell>
          <Button
            size="icon"
            variant="ghost"
            aria-expanded={expanded}
            aria-controls={`details-${row.measurement_id}`}
            aria-label={`Details for measurement ${row.measurement_id}`}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
          </Button>
          {canCorrect && (
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Correct measurement ${row.measurement_id}`}
              onClick={() => {
                setExpanded(true);
                setCorrecting(true);
              }}
            >
              Correct
            </Button>
          )}
        </TableCell>
        <TableCell className="num font-semibold">{row.cf}</TableCell>
        <TableCell className="whitespace-nowrap">
          {dayText(row.measured_date, row.date_is_month_only)}
        </TableCell>
        <TableCell className="min-w-36">{row.model}</TableCell>
        <TableCell className="min-w-32">{row.color}</TableCell>
        <TableCell>
          {pointText(labelOf("wavescan", row.model, row.checkzone), row.checkzone)}
          <span className="mt-1 block text-xs text-muted-foreground">{row.tolerance_group}</span>
        </TableCell>
        <TableCell className="num">{row.lw ?? <span aria-label="Not recorded">—</span>}</TableCell>
        <TableCell className="num">{row.sw ?? <span aria-label="Not recorded">—</span>}</TableCell>
        <TableCell className="num">{row.doi ?? <span aria-label="Not recorded">—</span>}</TableCell>
      </TableRow>
      {expanded && (
        <TableRow id={`details-${row.measurement_id}`}>
          <TableCell colSpan={9} className="bg-[var(--surface-2)] p-5">
            <div className="sticky left-5 w-[calc(100cqw-2.5rem)]">
              <div className="grid gap-6 sm:grid-cols-2">
                <div>
                  <h3 className="mb-3 font-semibold">Additional measurements</h3>
                  <dl className="grid grid-cols-2 gap-4">
                    {(["du", "wa", "wb", "wc", "wd", "we", "b"] as const).map((key) => (
                      <div key={key}>
                        <dt className="text-xs text-muted-foreground">{key.toUpperCase()}</dt>
                        <dd className="num mt-1 break-all">{row[key] ?? "Not recorded"}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
                <div>
                  <h3 className="mb-3 font-semibold">Measurement source</h3>
                  <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-2 text-xs">
                    <dt className="text-muted-foreground">Measurement ID</dt>
                    <dd>{row.measurement_id}</dd>
                    {row.corrects_measurement_id != null && (
                      <>
                        <dt className="text-muted-foreground">Corrects measurement</dt>
                        <dd>{row.corrects_measurement_id}</dd>
                        <dt className="text-muted-foreground">Correction reason</dt>
                        <dd className="break-words">{row.correction_reason}</dd>
                      </>
                    )}
                    <dt className="text-muted-foreground">Plant</dt>
                    <dd>{row.plant}</dd>
                    <dt className="text-muted-foreground">Serial</dt>
                    <dd className="break-all">{row.serial_no ?? "Not recorded"}</dd>
                    <dt className="text-muted-foreground">Paint line</dt>
                    <dd>{row.paintline ?? "Not recorded"}</dd>
                    <dt className="text-muted-foreground">Batch</dt>
                    <dd>{row.load_id}</dd>
                    <dt className="text-muted-foreground">Sheet / row</dt>
                    <dd>
                      {row.source_sheet} / {row.source_row}
                    </dd>
                    <dt className="text-muted-foreground">Loaded at</dt>
                    <dd className="break-all">{row.loaded_at}</dd>
                  </dl>
                </div>
              </div>
              {correcting && canCorrect && (
                <MeasurementCorrection
                  id={row.measurement_id}
                  onClose={() => setCorrecting(false)}
                  onNotice={onNotice}
                />
              )}
            </div>
          </TableCell>
        </TableRow>
      )}
    </Fragment>
  );
}

export function MeasurementTable({
  rows,
  onNotice = () => {},
}: {
  rows: Measurement[];
  onNotice?: (notice: string | Error) => void;
}) {
  const identity = useQuery(meOptions);
  const canCorrect = !identity.isError && mayCorrect(identity.data?.principal);
  return (
    <div className="[container-type:inline-size]">
      <Table className="text-xs [&_td]:py-2 [&_th]:text-[11px]">
        <TableCaption className="sr-only">
          Raw WaveScan measurements. Expand a row for additional parameters and source details.
        </TableCaption>
        <TableHeader>
          <TableRow className="bg-[var(--surface-2)]">
            <TableHead>
              <span className="sr-only">Details</span>
            </TableHead>
            <TableHead>CF</TableHead>
            <TableHead>Measured date</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>Colour</TableHead>
            <TableHead>Checkzone</TableHead>
            <TableHead>LW</TableHead>
            <TableHead>SW</TableHead>
            <TableHead>DOI</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <MeasurementRow
              key={row.measurement_id}
              row={row}
              canCorrect={canCorrect}
              onNotice={onNotice}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
