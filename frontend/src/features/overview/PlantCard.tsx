import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight } from "lucide-react";
import { plantCountOptions } from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";

/** Vault KpiStrip tile chrome: amber top hairline, soft wash. Not a grade bar. */
const tileChrome = {
  background: "linear-gradient(180deg, var(--primary-soft) 0%, var(--color-panel) 32%)",
  boxShadow: "inset 0 2px 0 var(--color-primary), var(--shadow-panel)",
} as const;

export function PlantCard({ plant }: { plant: components["schemas"]["PlantOut"] }) {
  const count = useQuery(plantCountOptions(plant.plant_code));
  return (
    <article
      aria-label={`${plant.plant_code} plant`}
      className="panel flex min-h-[118px] flex-col overflow-hidden animate-rise"
      style={tileChrome}
    >
      <div className="flex flex-1 flex-col justify-between px-4 py-3">
        <div>
          <p className="eyebrow">{plant.plant_code}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{plant.plant_name}</p>
        </div>
        {count.isPending ? (
          <LoadingState>Loading active count…</LoadingState>
        ) : count.isError ? (
          <ApiErrorState error={count.error} retry={() => void count.refetch()} />
        ) : (
          <div className="mt-3">
            <p
              className="num text-3xl font-semibold leading-none tracking-tight"
              aria-label={`${count.data.page.total} active measurements`}
            >
              {count.data.page.total}
            </p>
            <p className="num mt-2 truncate text-[10px] text-muted-foreground">
              {count.data.page.total === 0 ? "No active measurements" : "Active measurements"}
            </p>
          </div>
        )}
      </div>
      <Link
        to="/plant/$code"
        params={{ code: plant.plant_code }}
        className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-xs font-medium hover:bg-secondary"
      >
        Open {plant.plant_code} measurements{" "}
        <ArrowUpRight aria-hidden="true" className="size-3.5 text-primary" />
      </Link>
    </article>
  );
}
