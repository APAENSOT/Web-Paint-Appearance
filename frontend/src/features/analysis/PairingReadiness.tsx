/**
 * AR01: Wave Scan <-> Film pairing readiness for one plant.
 *
 * Counts only (D-AR01-6): paired cars in total, by pair group and by model x
 * colour, the pair list with its flags, and the data-quality list. No score,
 * percentage, rate, status or target (D-AR01-7). Every number is the API's.
 */

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { pairingReadinessOptions } from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";

export type PairingReadinessData = components["schemas"]["PairingReadinessOut"];

const PAIRING_COPY = {
  heading: "Wave Scan and Film pairing",
  explain:
    "Cars measured by both instruments, matched by car number. Counts only, from every active reading.",
  noRule: "No film car-number rule for this plant yet.",
  noPairs: "No car is in both Wave Scan and Film at this plant yet.",
};

const QUALITY_LABEL: Record<string, string> = {
  film_no_car_number: "Film jobs with no car number",
  wavescan_serial_not_7_digits: "Wave Scan serials that are not 7 digits",
  film_colour_code_shared: "Film colour codes used for more than one colour",
  pair_model_mismatch: "Pairs whose model differs",
  pair_colour_mismatch: "Pairs whose colour differs",
  wavescan_reading_unmapped: "Wave Scan readings on a zone with no pair group",
  film_reading_unmapped: "Film readings on a point with no pair group",
};

const FLAG_LABEL: Record<string, string> = {
  model_mismatch: "Model differs",
  colour_mismatch: "Colour differs",
};

const groupLabel = (code: string) => code.replaceAll("_", " ").toLowerCase();

function Table({
  caption,
  heads,
  children,
}: {
  caption: string;
  heads: string[];
  children: ReactNode;
}) {
  return (
    <div className="mt-2 overflow-x-auto rounded-md border border-border">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-[var(--surface-2)] text-muted-foreground">
          <tr>
            {heads.map((head) => (
              <th key={head} scope="col" className="px-3 py-2 font-medium">
                {head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function PairingReadiness({ code }: { code: string }) {
  const readiness = useQuery(pairingReadinessOptions(code));
  if (readiness.isPending) return <LoadingState>Loading pairing counts...</LoadingState>;
  if (readiness.isError)
    return <ApiErrorState error={readiness.error} retry={() => void readiness.refetch()} />;
  return <PairingReadinessView data={readiness.data} />;
}

export function PairingReadinessView({ data }: { data: PairingReadinessData }) {
  const counts: [string, number][] = [
    ["Wave Scan cars", data.wavescan_cars],
    ["Film cars", data.film_cars],
    ["Paired cars", data.paired_cars],
  ];
  return (
    <section
      className="panel min-w-0 p-4 sm:p-5"
      aria-label={`${data.plant_code} ${PAIRING_COPY.heading}`}
      data-testid="pairing-panel"
    >
      <p className="eyebrow">Analysis & Report</p>
      <h3 className="text-lg font-bold">{PAIRING_COPY.heading}</h3>
      <p className="mt-1 text-sm text-muted-foreground">{PAIRING_COPY.explain}</p>
      {data.car_rule === null && (
        <p className="mt-3 text-sm" data-testid="pairing-no-rule">
          {PAIRING_COPY.noRule}
        </p>
      )}

      <dl className="mt-4 grid grid-cols-3 gap-2" data-testid="pairing-counts">
        {counts.map(([label, value]) => (
          <div key={label} className="rounded-md border border-border p-2">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="num text-xl font-bold">{value}</dd>
          </div>
        ))}
      </dl>

      <h4 className="mt-5 text-sm font-semibold">By panel</h4>
      <Table
        caption="Paired cars per side and panel"
        heads={["Panel", "Wave Scan zones", "Film points", "Paired cars"]}
      >
        {data.by_pair_group.map((g) => (
          <tr key={g.pair_group} className="border-t border-border" data-pair-group={g.pair_group}>
            <th scope="row" className="px-3 py-2 font-medium capitalize">
              {groupLabel(g.pair_group)}
            </th>
            <td className="px-3 py-2 font-mono">{g.wavescan_zones.join(" ")}</td>
            <td className="num px-3 py-2">{g.film_points}</td>
            <td className="num px-3 py-2">{g.paired_cars}</td>
          </tr>
        ))}
      </Table>

      <h4 className="mt-5 text-sm font-semibold">Pairs</h4>
      {data.pairs.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground" data-testid="pairing-no-pairs">
          {PAIRING_COPY.noPairs}
        </p>
      ) : (
        <Table
          caption="Cars in both Wave Scan and Film"
          heads={["Car", "Model", "Colour", "Wave Scan dates", "Film dates", "Gap (days)", "Flags"]}
        >
          {data.pairs.map((p) => (
            <tr key={p.car_no} className="border-t border-border" data-pair={p.car_no}>
              <th scope="row" className="px-3 py-2 font-mono font-medium">
                {p.car_no}
              </th>
              <td className="px-3 py-2">
                {p.wavescan_model === p.film_model
                  ? p.wavescan_model
                  : `${p.wavescan_model} / ${p.film_model}`}
              </td>
              <td className="px-3 py-2">
                {p.wavescan_color === p.film_color
                  ? p.wavescan_color
                  : `${p.wavescan_color} / ${p.film_color}`}
              </td>
              <td className="px-3 py-2">{p.wavescan_dates.join(", ")}</td>
              <td className="px-3 py-2">{p.film_dates.join(", ")}</td>
              <td className="num px-3 py-2">{p.gap_days}</td>
              <td className="px-3 py-2" data-testid={`pairing-flags-${p.car_no}`}>
                {p.flags.length ? p.flags.map((f) => FLAG_LABEL[f] ?? f).join(", ") : "-"}
              </td>
            </tr>
          ))}
        </Table>
      )}

      <h4 className="mt-5 text-sm font-semibold">By model and colour</h4>
      <Table
        caption="Cars per model and colour in each domain"
        heads={["Model", "Colour", "Wave Scan cars", "Film cars", "Paired cars"]}
      >
        {data.by_model_colour.map((r) => (
          <tr key={`${r.model}|${r.color}`} className="border-t border-border">
            <td className="px-3 py-2">{r.model}</td>
            <td className="px-3 py-2">{r.color}</td>
            <td className="num px-3 py-2">{r.wavescan_cars}</td>
            <td className="num px-3 py-2">{r.film_cars}</td>
            <td className="num px-3 py-2">{r.paired_cars}</td>
          </tr>
        ))}
      </Table>

      <h4 className="mt-5 text-sm font-semibold">Data quality</h4>
      <ul className="mt-2 space-y-2" data-testid="pairing-quality">
        {data.quality.map((q) => (
          <li
            key={q.kind}
            className="rounded-md border border-border p-2 text-sm"
            data-quality={q.kind}
          >
            <span className="num font-bold">{q.count}</span> {QUALITY_LABEL[q.kind] ?? q.kind}
            {q.examples.length > 0 && (
              <span className="block break-words font-mono text-xs text-muted-foreground">
                {q.examples.join(" · ")}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
