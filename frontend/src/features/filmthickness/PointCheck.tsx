/**
 * T109 (D-109-1): **Point Check**, Standard's own entry for the points each
 * plant walks.
 *
 * The Film **Points** panel moved here from the Film Thickness standards
 * screen: standards are what a reading is measured against, and this is what
 * a reading is measured *at*. T114 (D-114-1) adds the Wave Scan section below
 * it, in place of the sentence that said it was coming.
 *
 * It renders through `PlantStandard` (`standardView === "points"`), so
 * `PlantMeasurements.tsx` needed no change.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { meOptions } from "@/api/queries";
import { mayAdminPointLists, mayEditFilmPoints } from "@/api/roles";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { AccessDenied } from "@/features/shell/AccessDenied";
import { POINT_CHECK_COPY } from "./film-points";
import { FilmPointSettings } from "./FilmPointSettings";
import { WsPointSettings } from "./WsPointSettings";
import "./point-check.css";

export function PointCheck({ code }: { code: string }) {
  const plant = code.toUpperCase();
  const [domain, setDomain] = useState<"film" | "wavescan">("film");
  // RO12 (D-RO12-4): its reads and writes are Engineer routes, so a Viewer
  // reaching it by URL is told so, as FilmStandards does for Admin.
  const identity = useQuery(meOptions);
  if (identity.isPending) return <LoadingState>Loading API identity...</LoadingState>;
  if (identity.isError)
    return <ApiErrorState error={identity.error} retry={() => void identity.refetch()} />;
  if (!mayEditFilmPoints(identity.data.principal))
    return (
      <AccessDenied requiredRole="Engineer" message="Point Check needs Engineer or Admin access." />
    );
  // RO17: the Admin-only point-list writes are offered to Admins only.
  const admin = mayAdminPointLists(identity.data.principal);
  return (
    <div className="point-check min-w-0 space-y-4" data-testid="point-check">
      <section
        className="point-check-heading panel min-w-0 p-4 sm:p-5"
        aria-label={`${plant} Point Check`}
      >
        <h2 className="text-xl font-bold">{POINT_CHECK_COPY.heading}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage the inspection points for {plant}. Choose a measurement type, then a model.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Counted settings apply to every month. Measurement readings stay unchanged.
        </p>
        <div className="point-check-tabs" role="tablist" aria-label="Point Check measurement type">
          {(["film", "wavescan"] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              id={`point-check-tab-${value}`}
              aria-selected={domain === value}
              aria-controls={`point-check-panel-${value}`}
              tabIndex={domain === value ? 0 : -1}
              onClick={() => setDomain(value)}
              onKeyDown={(event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                event.preventDefault();
                const next =
                  event.key === "Home"
                    ? "film"
                    : event.key === "End"
                      ? "wavescan"
                      : value === "film"
                        ? "wavescan"
                        : "film";
                setDomain(next);
                document.getElementById(`point-check-tab-${next}`)?.focus();
              }}
            >
              {value === "film" ? "Film Thickness" : "Wave Scan"}
            </button>
          ))}
        </div>
      </section>
      <div
        role="tabpanel"
        id="point-check-panel-film"
        aria-labelledby="point-check-tab-film"
        hidden={domain !== "film"}
      >
        <FilmPointSettings code={plant} admin={admin} />
      </div>
      <div
        role="tabpanel"
        id="point-check-panel-wavescan"
        aria-labelledby="point-check-tab-wavescan"
        hidden={domain !== "wavescan"}
      >
        <WsPointSettings code={plant} admin={admin} />
      </div>
    </div>
  );
}
