import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { readinessOptions } from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";

function property(value: unknown, key: string): unknown {
  return typeof value === "object" && value !== null && !Array.isArray(value) && key in value
    ? (value as Record<string, unknown>)[key]
    : undefined;
}

/** API health colour only — not a product grade. */
function healthTone(status: string): string {
  return status === "ready" || status === "ok" ? "var(--nominal)" : "var(--caution)";
}

const stripChrome = {
  background: "linear-gradient(180deg, var(--primary-soft) 0%, var(--color-panel) 40%)",
  boxShadow: "inset 0 2px 0 var(--color-primary), var(--shadow-panel)",
} as const;

export function HealthBanner() {
  const readiness = useQuery(readinessOptions);
  const status = property(readiness.data, "status");
  const checks = property(readiness.data, "checks");
  return (
    <section
      aria-label="Service readiness"
      className="panel overflow-hidden animate-rise"
      style={stripChrome}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Activity aria-hidden="true" className="size-3.5 text-primary" />
          Service readiness
        </h2>
        <Button
          size="sm"
          variant="ghost"
          disabled={readiness.isFetching}
          onClick={() => void readiness.refetch()}
        >
          Check readiness
        </Button>
      </div>
      {readiness.isPending ? (
        <LoadingState>Checking service readiness…</LoadingState>
      ) : readiness.isError ? (
        <ApiErrorState error={readiness.error} retry={() => void readiness.refetch()} />
      ) : (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-border px-4 py-2.5 text-sm">
          {typeof status === "string" ? (
            <p className="flex items-center gap-2">
              Status:{" "}
              <span
                className="rounded-[var(--radius-sm)] border px-2 py-0.5 text-xs font-medium"
                style={{
                  color: healthTone(status),
                  borderColor: healthTone(status),
                  backgroundColor: "var(--surface-2)",
                }}
              >
                {status}
              </span>
            </p>
          ) : (
            <p>Readiness details unavailable</p>
          )}
          {(
            [
              ["database", "Database"],
              ["object_store", "Object store"],
            ] as const
          ).map(([key, label]) => {
            const check = property(property(checks, key), "status");
            return typeof check === "string" ? (
              <p key={key} className="text-muted-foreground">
                {label}:{" "}
                <span className="text-foreground" style={{ color: healthTone(check) }}>
                  {check}
                </span>
              </p>
            ) : null;
          })}
        </div>
      )}
    </section>
  );
}
