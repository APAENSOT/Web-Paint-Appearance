import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { Button } from "../../components/ui/button";
import type { components } from "../../api/types";

export function PreviewTable({ series }: { series: components["schemas"]["PreviewSeries"][] }) {
  const [page, setPage] = useState(0);
  const rows = useMemo(
    () => series.flatMap((s) => s.points.map((point) => ({ key: s.key, point }))),
    [series],
  );
  const pageSize = 50;
  return (
    <section className="panel overflow-hidden" aria-labelledby="measurements-title">
      <div className="p-5">
        <h2 id="measurements-title" className="text-xl font-semibold">
          Recorded measurements
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Exact CF values from this preview. Use Open plant to inspect the plant workspace.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full whitespace-nowrap text-left text-sm">
          <caption className="sr-only">Raw CF measurements in the preview</caption>
          <thead className="border-y border-border bg-muted/30 text-muted-foreground">
            <tr>
              {[
                "Series",
                "Measured date",
                "Plant",
                "Model",
                "Colour",
                "Zone",
                "CF",
                "Workspace",
              ].map((label) => (
                <th scope="col" key={label} className="px-4 py-3 font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(page * pageSize, (page + 1) * pageSize).map(({ key, point }) => (
              <tr key={`${key}:${point.measurement_id}`} className="border-b border-border/60">
                <td className="px-4 py-3">{key}</td>
                <td className="px-4 py-3 font-mono">{point.measured_date}</td>
                <td className="px-4 py-3">{point.plant}</td>
                <td className="px-4 py-3">{point.model}</td>
                <td className="px-4 py-3">{point.color}</td>
                <td className="px-4 py-3">{point.checkzone}</td>
                <td className="px-4 py-3 font-mono">{point.cf}</td>
                <td className="px-4 py-3">
                  <Link
                    to="/plant/$code"
                    params={{ code: point.plant }}
                    className="text-primary underline underline-offset-4"
                  >
                    Open plant
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-3 p-4">
        <Button variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>
          Previous rows
        </Button>
        <span className="text-xs text-muted-foreground">Table pages cover this preview only.</span>
        <Button
          variant="outline"
          disabled={(page + 1) * pageSize >= rows.length}
          onClick={() => setPage(page + 1)}
        >
          Next rows
        </Button>
      </div>
    </section>
  );
}
