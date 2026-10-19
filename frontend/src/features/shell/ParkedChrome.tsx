import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ThemeToggle } from "@/components/ct/ThemeToggle";

/** Vault header for routes that are not in the Lovable product yet. */
export function ParkedChrome({ children }: { children: ReactNode }) {
  return (
    <div className="relative z-10 min-h-screen">
      <header
        className="relative z-30 border-b border-border backdrop-blur-md"
        style={{ backgroundColor: "var(--header-bg)" }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 lg:px-6">
          <Link to="/" className="flex items-center gap-3">
            <div
              className="grid size-9 place-items-center rounded-[var(--radius-sm)] border"
              style={{ borderColor: "var(--primary)", backgroundColor: "var(--primary-soft)" }}
            >
              <svg
                viewBox="0 0 24 24"
                className="size-5"
                fill="none"
                stroke="var(--primary)"
                strokeWidth="1.6"
              >
                <path d="M12 2v20M2 12h20" strokeOpacity="0.45" />
                <circle cx="12" cy="12" r="4.5" />
                <circle cx="12" cy="12" r="9" strokeOpacity="0.5" strokeDasharray="2 4" />
              </svg>
            </div>
            <div>
              <h1 className="text-[15px] font-semibold leading-none tracking-tight">
                Paint Appearance
              </h1>
              <p className="eyebrow mt-1">WAVE SCAN &amp; FILM THICKNESS · IMG REGION · 4 PLANTS</p>
            </div>
          </Link>
          <ThemeToggle />
        </div>
      </header>
      <main className="space-y-2 p-2 lg:p-3">{children}</main>
    </div>
  );
}
