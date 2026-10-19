import { useCallback, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Search } from "lucide-react";
import {
  monthlyPointsOptions,
  monthlyPointStatusesOptions,
  pointProfileOptions,
} from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { MonthlyBody } from "./MonthlyBody";
import { PointCharts } from "./PointCharts";
import { pointStatusLabel, type Profile } from "./display";
const EMPTY_SUMMARIES: components["schemas"]["MonthlyPointStatus"][] = [];
const meanLabel = (value: string) =>
  Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });

export function ProfileInspection({
  plant,
  month,
  profile,
  hex,
  onBack,
}: {
  plant: string;
  month: string;
  profile: Profile;
  hex: string | null;
  onBack: () => void;
}) {
  const points = useQuery(pointProfileOptions(plant, profile.model_code, profile.domain));
  const [selected, setSelected] = useState<string | null>(null),
    [query, setQuery] = useState("");
  const detail = useRef<HTMLElement>(null);
  const select = useCallback((key: string) => {
    setSelected(key);
    if (matchMedia("(max-width: 1200px)").matches)
      requestAnimationFrame(() => detail.current?.scrollIntoView({ block: "start" }));
  }, []);
  const [metric, setMetric] = useState<components["schemas"]["MonthlyPointsOut"]["metric"]>(
    profile.domain === "wavescan" ? "cf" : "clear",
  );
  const measures = useQuery({
    ...monthlyPointsOptions(plant, {
      domain: profile.domain,
      month,
      model: profile.model_code,
      color: profile.color_name,
      metric,
      point_key: selected ?? "",
    }),
    enabled: Boolean(selected),
  });
  const statuses = useQuery(
    monthlyPointStatusesOptions(plant, {
      domain: profile.domain,
      month,
      model: profile.model_code,
      color: profile.color_name,
      metric,
    }),
  );
  const point = points.data?.points.find((p) => p.point_key === selected);
  const list = (points.data?.points ?? []).filter((p) =>
    `${p.point_no} ${p.label} ${p.point_key}`.toLowerCase().includes(query.toLowerCase()),
  );
  const placed = points.data?.points.filter((p) => p.anchor?.asset_compatible).length ?? 0;
  const statusByPoint = new Map(statuses.data?.items.map((item) => [item.point_key, item]) ?? []);
  const statusCounts = (statuses.data?.items ?? []).reduce<Record<string, number>>(
    (counts, item) => {
      const key = item.status ?? (item.mean ? "UNCLASSIFIED" : "NO_DATA");
      counts[key] = (counts[key] ?? 0) + 1;
      return counts;
    },
    {},
  );
  return (
    <section
      className="monthly-inspection"
      aria-label={`${profile.model_code} ${profile.color_name} monthly inspection`}
    >
      <header className="monthly-inspection-header">
        <button className="monthly-back" onClick={onBack}>
          <ArrowLeft size={17} /> All profiles
        </button>
        <div>
          <h2>{profile.model_code}</h2>
          <p>
            <span
              className="monthly-color-dot"
              style={{ background: hex ?? "var(--muted-foreground)" }}
            />
            {profile.color_name} · {month} ·{" "}
            {profile.domain === "wavescan" ? "Wave Scan" : "Film Thickness"}
          </p>
        </div>
        <span className="monthly-tag">{profile.family_name ?? "Family not assigned"}</span>
      </header>
      {points.isPending ? (
        <LoadingState>Loading saved inspection profile…</LoadingState>
      ) : points.isError ? (
        <ApiErrorState error={points.error} retry={() => void points.refetch()} />
      ) : (
        <div className="monthly-inspection-grid">
          <aside ref={detail} className="monthly-point-detail" aria-label="Selected point details">
            <header>
              <h3>
                {point ? `${point.point_no ?? "—"} · ${point.label}` : "Choose an inspection point"}
              </h3>
              <p>
                {point
                  ? `Standard key: ${point.point_key}`
                  : "Click a dot on the body or choose a point from the list."}
              </p>
            </header>
            <label className="monthly-metric">
              {profile.domain === "wavescan" ? "Measurement" : "Paint layer"}
              <select
                value={metric}
                onChange={(e) =>
                  setMetric(e.target.value as components["schemas"]["MonthlyPointsOut"]["metric"])
                }
              >
                {(profile.domain === "wavescan"
                  ? ["cf", "lw", "sw", "doi", "du", "wa", "wb", "wc", "wd", "we", "b"]
                  : ["ecoat", "primer", "base", "clear"]
                ).map((m) => (
                  <option key={m} value={m}>
                    {m.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            {!selected ? (
              <div className="monthly-point-intro">
                <strong>{profile.sample_count} monthly samples</strong>
                <p>
                  Inspect the distribution and progression of each Standard point. Points without a
                  saved location are still available in the list.
                </p>
              </div>
            ) : measures.isPending ? (
              <LoadingState>Loading all monthly samples at this point…</LoadingState>
            ) : measures.isError ? (
              <ApiErrorState error={measures.error} retry={() => void measures.refetch()} />
            ) : (
              <>
                <dl className="monthly-point-counts">
                  <div>
                    <dt>Samples checked</dt>
                    <dd>
                      {measures.data.checked_sample_count} / {measures.data.sample_count}
                    </dd>
                  </div>
                  <div>
                    <dt>Readings</dt>
                    <dd>{measures.data.reading_count}</dd>
                  </div>
                </dl>
                <PointCharts data={measures.data} />
                {measures.data.unaligned_reading_count > 0 && (
                  <p className="monthly-help">
                    {measures.data.unaligned_reading_count} historical readings are outside the
                    current point list and are excluded from this point chart.
                  </p>
                )}
              </>
            )}
          </aside>
          <div className="monthly-vehicle">
            <MonthlyBody
              model={profile.model_code}
              hex={hex}
              family={profile.family_name}
              profile={points.data}
              selected={selected}
              onSelect={select}
              summaries={statuses.data?.items ?? EMPTY_SUMMARIES}
            />
            <section className="monthly-point-list">
              <div className="monthly-section-title">
                <h3>Inspection points</h3>
                <span>
                  {placed} / {points.data.points.length} located in Studio
                </span>
              </div>
              <p className="monthly-help monthly-status-explanation">
                Dot colour shows each point’s monthly average against the current Standard. Select a
                dot or list item to see its graph.
              </p>
              {statuses.isPending && (
                <p className="monthly-help" role="status">
                  Loading point averages…
                </p>
              )}
              {statuses.isError && (
                <ApiErrorState error={statuses.error} retry={() => void statuses.refetch()} />
              )}
              <div className="monthly-status-legend" aria-label="Point average status legend">
                {(["PASS", "WARNING", "FAIL", "OVER", "NO_DATA"] as const).map((status) =>
                  statusCounts[status] ? (
                    <span key={status} data-status={status}>
                      <i aria-hidden="true" /> {pointStatusLabel(status, profile.domain, metric)} ·{" "}
                      {statusCounts[status]}
                    </span>
                  ) : null,
                )}
                {statusCounts.UNCLASSIFIED ? (
                  <span data-status="UNCLASSIFIED">
                    <i aria-hidden="true" /> No Standard · {statusCounts.UNCLASSIFIED}
                  </span>
                ) : null}
              </div>
              <label className="monthly-search">
                <Search size={16} aria-hidden="true" />
                <span className="sr-only">Find an inspection point</span>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Point name or number"
                />
              </label>
              {placed === 0 && (
                <p className="monthly-help">
                  No saved locations yet. Plot points in Model Detail; you can inspect their
                  measurements here now.
                </p>
              )}
              <div className="monthly-point-buttons">
                {list.map((p) => {
                  const summary = statusByPoint.get(p.point_key);
                  const status = summary?.status ?? (summary?.mean ? "UNCLASSIFIED" : "NO_DATA");
                  return (
                    <button
                      key={p.point_key}
                      onClick={() => select(p.point_key)}
                      aria-pressed={selected === p.point_key}
                      data-status={status}
                    >
                      <span className="monthly-point-number">{p.point_no ?? "—"}</span>
                      <span>
                        {p.label}
                        <small title={summary?.mean ?? undefined}>
                          {summary?.mean
                            ? `Avg ${meanLabel(summary.mean)} ${statuses.data?.unit}`
                            : summary
                              ? "No reading"
                              : statuses.isPending
                                ? "Loading average…"
                                : "Average unavailable"}
                          {summary?.status
                            ? ` · ${pointStatusLabel(summary.status, profile.domain, metric)}`
                            : summary?.mean
                              ? " · No Standard"
                              : ""}
                          {p.anchor?.asset_compatible ? " · Located" : " · Not placed"}
                          {p.counted === false ? " · Not counted" : ""}
                        </small>
                      </span>
                    </button>
                  );
                })}
              </div>
              {!list.length && <p className="monthly-empty">No points match this search.</p>}
              {points.data.unavailable.length > 0 && (
                <p className="monthly-help">
                  {points.data.unavailable.length} retired or unavailable locations remain in the
                  saved profile but are not mapped to current points.
                </p>
              )}
            </section>
            <p className="monthly-help monthly-layout-note">
              Current saved layout, shared across colours and months. Display appearance is an
              approximation.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
