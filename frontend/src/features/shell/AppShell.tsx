import { Link, Outlet } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Factory,
  LayoutDashboard,
  ChartNoAxesCombined,
  Upload,
  Settings,
} from "lucide-react";
import { meOptions, metaOptions } from "@/api/queries";
import { maySeeIntakeNav, maySeeAdminNav, roleLabel } from "@/api/roles";
import { ThemeToggle } from "@/components/ct/ThemeToggle";
import { ApiErrorState, LoadingState } from "@/components/ApiState";

const navClass =
  "flex items-center gap-3 rounded-md border border-transparent px-3 py-2 text-xs font-medium hover:bg-secondary";
const activeNav = {
  className: "border-border bg-panel text-primary",
  "aria-current": "page" as const,
};

export function AppShell() {
  const identity = useQuery(meOptions);
  const metadata = useQuery({ ...metaOptions, enabled: identity.isSuccess && !identity.isError });
  const queryClient = useQueryClient();
  const principal = identity.isError ? undefined : identity.data?.principal;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-panel focus:p-3"
      >
        Skip to workspace
      </a>
      <header
        className="border-b border-border px-4 py-3 lg:px-6"
        style={{ backgroundColor: "var(--header-bg)" }}
      >
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-3 text-[15px] font-semibold leading-none">
            <span className="grid size-9 place-items-center rounded-sm border border-primary bg-primary/10">
              <Activity aria-hidden="true" className="size-5 text-primary" />
            </span>
            <span>
              Paint Appearance
              <span className="mt-1 block text-[10px] font-normal text-muted-foreground">
                WaveScan workspace
              </span>
            </span>
          </Link>
          <div className="flex items-center gap-4">
            {principal && (
              <div className="text-right text-xs" aria-label="Current API identity">
                <span className="font-medium">{principal.display_name}</span>
                <div className="mt-1 flex flex-wrap justify-end gap-2 text-xs text-muted-foreground">
                  <span>{roleLabel(principal)}</span>
                  <span className="rounded-sm border border-border px-1.5">
                    {principal.auth_source === "dev-bypass"
                      ? "Dev bypass"
                      : principal.auth_source === "open-access"
                        ? "Shared access"
                        : principal.auth_source}
                  </span>
                </div>
              </div>
            )}
            <ThemeToggle />
          </div>
        </div>
      </header>
      <div className="mx-auto grid max-w-[1600px] gap-3 p-3 lg:grid-cols-[180px_minmax(0,1fr)] lg:p-4">
        <aside className="min-w-0 rounded-md border border-border bg-panel/40 p-2 lg:self-start">
          <nav aria-label="Workspace" className="mb-4 grid grid-cols-2 gap-1 lg:grid-cols-1">
            <Link
              to="/"
              activeOptions={{ exact: true }}
              className={navClass}
              activeProps={activeNav}
            >
              <LayoutDashboard aria-hidden="true" className="size-4" />
              Overview
            </Link>
            <Link to="/analysis" className={navClass} activeProps={activeNav}>
              <ChartNoAxesCombined aria-hidden="true" className="size-4" />
              Analysis
            </Link>
          </nav>
          <div className="mb-2 flex items-center gap-2 px-3 text-xs font-medium">
            <Factory aria-hidden="true" className="size-4" /> Plants
          </div>
          {metadata.isSuccess && !identity.isError && (
            <nav aria-label="Plants" className="flex flex-wrap gap-2 lg:flex-col">
              {metadata.data.plants.map((plant) => (
                <Link
                  key={plant.plant_code}
                  to="/plant/$code"
                  params={{ code: plant.plant_code }}
                  className="rounded-md border border-transparent px-3 py-2 text-xs hover:bg-secondary"
                  activeProps={{
                    className: "border-border bg-panel text-primary",
                    "aria-current": "page",
                  }}
                >
                  <span className="block font-semibold">{plant.plant_code}</span>
                  <span className="hidden text-xs text-muted-foreground lg:block">
                    {plant.plant_name}
                  </span>
                </Link>
              ))}
            </nav>
          )}
          {metadata.isError && !identity.isError && (
            <div className="panel">
              <ApiErrorState error={metadata.error} retry={() => void metadata.refetch()} />
            </div>
          )}
          {metadata.isPending && principal && (
            <p className="text-xs text-muted-foreground">Loading plants...</p>
          )}
          {(maySeeIntakeNav(principal) || maySeeAdminNav(principal)) && (
            <div className="mt-6 space-y-1 border-t border-border pt-4">
              {maySeeIntakeNav(principal) && (
                <nav aria-label="Ingest">
                  <Link to="/batches" className={navClass} activeProps={activeNav}>
                    <Upload aria-hidden="true" className="size-4" />
                    Data intake
                  </Link>
                </nav>
              )}
              {maySeeAdminNav(principal) && (
                <nav aria-label="Administration">
                  <Link to="/admin" className={navClass} activeProps={activeNav}>
                    <Settings aria-hidden="true" className="size-4" />
                    Administration
                  </Link>
                </nav>
              )}
            </div>
          )}
          {identity.data && !identity.isError && (
            <p className="mt-4 px-3 pb-2 text-[10px] leading-relaxed text-muted-foreground">
              {identity.data.plant_scope === null
                ? "All plants are currently visible to authenticated users. Plant access policy is provisional."
                : identity.data.plant_scope_note}
            </p>
          )}
        </aside>
        <main id="main" tabIndex={-1} className="min-w-0">
          {identity.isPending ? (
            <div className="panel">
              <LoadingState>Connecting to your API session...</LoadingState>
            </div>
          ) : identity.isError ? (
            <div className="panel">
              <ApiErrorState
                error={identity.error}
                retry={() => void queryClient.invalidateQueries()}
              />
            </div>
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </div>
  );
}
