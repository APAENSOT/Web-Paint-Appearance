import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { identityChrome, UNAVAILABLE_BAY_REASON } from "./plant-lens";

function Bay({
  num,
  label,
  last = false,
  children,
}: {
  num: number;
  label: string;
  last?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={`group relative min-w-0 flex-1 px-4 py-3 sm:px-5 sm:py-4 ${last ? "" : "border-r border-border"}`}
    >
      {num < 3 && (
        <span
          aria-hidden
          className="num pointer-events-none absolute right-3 top-1 select-none text-5xl font-bold"
          style={{ color: "var(--surface-2)" }}
        >
          {num}
        </span>
      )}
      <div className="relative z-10">
        <p className="eyebrow mb-1">{label}</p>
        {children}
      </div>
    </div>
  );
}

export function PlantBays({ code, plantName }: { code: string; plantName?: string }) {
  const month = new Date().toLocaleString("en-US", { month: "long" });
  const year = new Date().getFullYear();
  return (
    <header
      aria-label="Plant dashboard"
      className="panel flex min-w-0 flex-col overflow-hidden xl:flex-row"
    >
      <div
        className="flex shrink-0 items-center gap-3 border-b border-border xl:border-b-0 xl:border-r px-4 py-3 sm:gap-4 sm:px-5 sm:py-4"
        style={identityChrome}
      >
        <Link
          to="/"
          className="flex size-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border border-border text-muted-foreground transition-colors hover:text-foreground"
          aria-label="Back to overview"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <div>
          <p className="eyebrow leading-tight">Plant Dashboard</p>
          <h1 className="mt-0.5 text-2xl font-bold leading-tight tracking-tight">{code}</h1>
        </div>
      </div>
      <div className="grid min-w-0 flex-1 grid-cols-2 sm:grid-cols-3 xl:grid-cols-5">
        <Bay num={1} label="Domain / Process">
          <p className="truncate text-sm font-bold">WAVESCAN</p>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {plantName ?? "Plant workspace"}
          </p>
        </Bay>
        <Bay num={2} label="Current Month">
          <p className="text-sm font-bold">{month}</p>
          <p className="num mt-0.5 text-[11px] text-muted-foreground">{year}</p>
        </Bay>
        <Bay num={3} label="First Run OK">
          <p className="max-w-[11rem] text-[11px] leading-snug text-muted-foreground">
            {UNAVAILABLE_BAY_REASON}
          </p>
        </Bay>
        <Bay num={4} label="Line Status">
          <p className="max-w-[11rem] text-[11px] leading-snug text-muted-foreground">
            {UNAVAILABLE_BAY_REASON}
          </p>
        </Bay>
        <Bay num={5} label="Data Backup" last>
          <p className="max-w-[11rem] text-[11px] leading-snug text-muted-foreground">
            {UNAVAILABLE_BAY_REASON}
          </p>
        </Bay>
      </div>
    </header>
  );
}
