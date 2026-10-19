import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Search, SlidersHorizontal } from "lucide-react";
import { colorAppearancesOptions } from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { filterProfiles } from "./display";
import { ProfilePhoto } from "./ProfilePhoto";
import { ProfileInspection } from "./ProfileInspection";
import "./monthly-detail.css";
import { calendarYearMonth } from "../overview-display";
import { useSurfaceMotion } from "@/hooks/use-surface-motion";

export function MonthlyDetail({
  code,
  data,
  isPending,
  error,
  retry,
  models,
  colors,
}: {
  code: string;
  data: components["schemas"]["MonthlyProfilesOut"] | undefined;
  isPending: boolean;
  error: Error | null;
  retry: () => void;
  models: string[];
  colors: string[];
}) {
  const appearances = useQuery(colorAppearancesOptions(code));
  const [query, setQuery] = useState(""),
    [family, setFamily] = useState(""),
    [measuredOnly, setMeasuredOnly] = useState(false);
  const [opened, setOpened] = useState<string | null>(null);
  const items = filterProfiles(data?.items ?? [], { query, models, colors, family, measuredOnly });
  const current = items.find((p) => p.profile_id === opened);
  const motion = useSurfaceMotion(current?.profile_id ?? "gallery", current ? 1 : -1);
  const shade = (color: string) =>
    appearances.data?.items.find((c) => c.color_name === color)?.appearance?.hex ??
    appearances.data?.unavailable.find((c) => c.color_name === color)?.appearance?.hex ??
    null;
  if (isPending || appearances.isPending)
    return (
      <section className="panel p-6">
        <LoadingState>Loading monthly vehicle profiles…</LoadingState>
      </section>
    );
  if (error || appearances.isError)
    return (
      <section className="panel p-6">
        <ApiErrorState
          error={error ?? appearances.error!}
          retry={() => {
            retry();
            void appearances.refetch();
          }}
        />
      </section>
    );
  if (current)
    return (
      <div {...motion}>
        <ProfileInspection
          key={`${current.profile_id}:${data?.month ?? "no-measured-month"}`}
          plant={code}
          month={data?.month ?? calendarYearMonth()}
          profile={current}
          hex={shade(current.color_name)}
          onBack={() => setOpened(null)}
        />
      </div>
    );
  const families = [
    ...new Set((data?.items ?? []).flatMap((p) => (p.family_name ? [p.family_name] : []))),
  ].sort();
  return (
    <div {...motion}>
      <section className="monthly-detail" aria-label={`${code} Monthly Detail`}>
        <header className="monthly-gallery-header">
          <div>
            <h2>Monthly Detail</h2>
            <p>
              {data?.month ?? "No measured month"} ·{" "}
              {data?.domain === "film" ? "Film Thickness" : "Wave Scan"} · {items.length} profiles
            </p>
          </div>
          <span className="monthly-tag">{code}</span>
        </header>
        <div className="monthly-gallery-tools">
          <label className="monthly-search">
            <Search size={17} aria-hidden="true" />
            <span className="sr-only">Find a model or colour profile</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a model, colour or family"
            />
          </label>
          <label className="monthly-family">
            <SlidersHorizontal size={16} aria-hidden="true" />
            <span className="sr-only">Colour family</span>
            <select value={family} onChange={(e) => setFamily(e.target.value)}>
              <option value="">All colour families</option>
              {families.map((f) => (
                <option key={f}>{f}</option>
              ))}
            </select>
          </label>
          <label className="monthly-measured">
            <input
              type="checkbox"
              checked={measuredOnly}
              onChange={(e) => setMeasuredOnly(e.target.checked)}
            />{" "}
            With monthly samples
          </label>
        </div>
        <div className="monthly-profile-grid">
          {items.map((p) => (
            <button
              className="monthly-profile-card"
              key={p.profile_id}
              onClick={() => setOpened(p.profile_id)}
              aria-label={`Open ${p.model_code} · ${p.color_name} · ${p.sample_count} samples`}
            >
              <ProfilePhoto
                model={p.model_code}
                hex={shade(p.color_name)}
                colorName={p.color_name}
              />
              <div className="monthly-card-info">
                <div className="monthly-card-tags">
                  <span>{p.domain === "wavescan" ? "Wave Scan" : "Film Thickness"}</span>
                  <span>{p.family_name ?? "Family not assigned"}</span>
                  {!p.is_offered && <span>Historical combination</span>}
                </div>
                <h3>{p.model_code}</h3>
                <p>
                  <span
                    className="monthly-color-dot"
                    style={{ background: shade(p.color_name) ?? "var(--muted-foreground)" }}
                  />
                  {p.color_name}
                </p>
                <div className="monthly-card-bottom">
                  <span>
                    {p.sample_count ? (
                      <>
                        <strong>{p.sample_count}</strong> samples
                      </>
                    ) : (
                      "No samples this month"
                    )}
                  </span>
                  <span>
                    Open inspection <ArrowUpRight size={16} aria-hidden="true" />
                  </span>
                </div>
                {!shade(p.color_name) && (
                  <small className="monthly-help">Colour appearance not configured in Studio</small>
                )}
              </div>
            </button>
          ))}
        </div>
        {!items.length && (
          <div className="monthly-gallery-empty">
            <h3>{data?.items.length ? "No matching profiles" : "No profiles available"}</h3>
            <p>
              {data?.items.length
                ? "Change the model, colour, family or search filters to find a profile."
                : "Attach model and colour identities in this plant’s Standard, or load monthly measurements."}
            </p>
            {(query || family || measuredOnly) && (
              <button
                onClick={() => {
                  setQuery("");
                  setFamily("");
                  setMeasuredOnly(false);
                }}
              >
                Clear profile filters
              </button>
            )}
          </div>
        )}
        <p className="monthly-help monthly-gallery-note">
          Profiles use this plant’s Standard model and colour identities. Empty combinations do not
          assert production. Body panels preview the saved colour; lamps, glass, wheels and trim
          retain the original photo. Illustrative appearance, not a calibrated paint match.
        </p>
      </section>
    </div>
  );
}
