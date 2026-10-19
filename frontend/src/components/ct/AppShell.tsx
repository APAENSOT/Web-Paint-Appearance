import { useQuery } from "@tanstack/react-query";
import { readinessOptions } from "@/api/queries";
import { ThemeToggle } from "@/components/ct/ThemeToggle";
import type { ControlState } from "@/lib/ct/engine";
import type { ReactNode } from "react";

export function AppShell({
  children,
  footerControls,
}: {
  children: ReactNode;
  state: ControlState;
  footerControls?: ReactNode;
}) {
  // shortcut: /health/ready answers 503 when only the object store is down, so that also reads as Disconnected; split it if it ever matters.
  const readiness = useQuery({ ...readinessOptions, refetchInterval: 30_000 });
  const dbStatus = (readiness.data as { checks?: { database?: { status?: unknown } } } | undefined)
    ?.checks?.database?.status;
  const posture = readiness.isPending
    ? { label: "Checking", color: "var(--muted-foreground)" }
    : dbStatus === "ok"
      ? { label: "Connected", color: "var(--nominal)" }
      : { label: "Disconnected", color: "var(--critical)" };

  return (
    <div className="relative z-10 min-h-screen">
      <a className="skip-workspace" href="#plant-network">
        Skip to plant dashboards
      </a>
      <header
        className="relative z-30 border-b border-border backdrop-blur-md"
        style={{ backgroundColor: "var(--header-bg)" }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 lg:px-6">
          <div className="flex min-w-0 items-center gap-3 sm:gap-4">
            <img
              src="/brand/ford-oval.svg"
              alt="Ford"
              width="1000"
              height="360"
              className="h-auto w-[76px] shrink-0 sm:w-[88px]"
            />
            <div className="min-w-0">
              <h1 className="text-[15px] font-semibold leading-none tracking-tight">
                Paint Appearance
              </h1>
              <p className="mt-1 text-xs text-muted-foreground">
                WaveScan &amp; Film Thickness · IMG region
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 sm:flex">
              <span className="text-xs text-muted-foreground">Database</span>
              <span
                className="rounded-[var(--radius-sm)] border px-2 py-1 text-xs font-medium"
                style={{
                  color: posture.color,
                  borderColor: posture.color,
                  backgroundColor: "var(--surface-2)",
                }}
              >
                {posture.label}
              </span>
            </div>
            <ThemeToggle variant="pill" />
          </div>
        </div>
      </header>

      <main id="plant-network" tabIndex={-1} className="space-y-3 p-3 lg:p-5 outline-none">
        {children}

        <footer className="flex flex-wrap items-center justify-between gap-2 px-2 pb-2 pt-1">
          {footerControls}
          <p className="rounded-sm bg-panel px-2 py-1 text-xs text-muted-foreground">
            Ford Internal Use Only
          </p>
        </footer>
      </main>
    </div>
  );
}
