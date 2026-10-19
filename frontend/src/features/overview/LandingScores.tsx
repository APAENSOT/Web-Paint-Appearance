import type { CSSProperties } from "react";
import { ArrowUpRight } from "lucide-react";
import { PLANTS, FEED_LEVEL_LABEL, type Plant } from "@/lib/ct/data";
import { calendarYearMonth, monthTitle } from "@/features/measurements/overview-display";
import { scoreLevel, type PlantFeed } from "./plant-feed";
import { FactoryLandmark } from "./FactoryLandmark";

export function LandingScores({
  feeds,
  active,
  selected,
  onPlant,
  onHighlight,
}: {
  feeds: Record<string, PlantFeed>;
  active: string[];
  selected: string | null;
  onPlant: (plant: Plant) => void;
  onHighlight: (id: string | null) => void;
}) {
  return (
    <section className="landing-scores" aria-label="Plant scores">
      {PLANTS.map((plant) => (
        <ScoreCard
          key={plant.id}
          plant={plant}
          intake={feeds[plant.code]}
          feed={active.includes(plant.id)}
          selected={selected === plant.id}
          onPlant={onPlant}
          onHighlight={onHighlight}
        />
      ))}
    </section>
  );
}

function ScoreCard({
  plant,
  intake,
  feed,
  selected,
  onPlant,
  onHighlight,
}: {
  plant: Plant;
  intake: PlantFeed;
  feed: boolean;
  selected: boolean;
  onPlant: (plant: Plant) => void;
  onHighlight: (id: string | null) => void;
}) {
  const status = intake.status;
  const score = feed ? (status?.pct ?? null) : intake.quality;
  const level = feed ? (status?.level ?? null) : score === null ? null : scoreLevel(score);
  const pending = intake.pending;
  return (
    <button
      type="button"
      className="panel landing-score"
      aria-label={`Explore ${plant.code} score and plant`}
      aria-pressed={selected}
      style={
        {
          "--score-status": level ? `var(--${level})` : "var(--border)",
          "--score-fill": `${score ?? 0}%`,
        } as CSSProperties
      }
      onClick={() => onPlant(plant)}
      onMouseEnter={() => onHighlight(plant.id)}
      onMouseLeave={() => onHighlight(null)}
      onFocus={() => onHighlight(plant.id)}
      onBlur={() => onHighlight(null)}
    >
      <span className="landing-score__heading">
        <strong>{plant.code}</strong>
        <ArrowUpRight size={17} />
      </span>
      <span className="landing-score__country">{plant.country}</span>
      <span className="landing-score__value">
        {score === null ? (pending ? "…" : "—") : score.toFixed(1)}
        {score !== null && <small>%</small>}
      </span>
      <span className="landing-score__metric">
        {feed ? "On-time data entry" : "Month-to-date quality"}
      </span>
      <span className="landing-score__factory">
        <FactoryLandmark code={plant.code} paused />
      </span>
      <span className="landing-score__gauge">
        <span />
      </span>
      <span className="landing-score__footer">
        <span>
          {pending
            ? "Loading plant status…"
            : intake.error
              ? "Status unavailable · retry above"
              : feed
                ? status
                  ? `Week ${status.week} · late ${status.late} · missing ${status.missing}`
                  : "No control plan for this plant"
                : intake.quality === null
                  ? `No graded readings in ${monthTitle(calendarYearMonth())} yet`
                  : "Wave Scan · Film Thickness"}
        </span>
        <strong style={{ color: status ? `var(--${status.level})` : "var(--muted-foreground)" }}>
          Feed: {status ? FEED_LEVEL_LABEL[status.level] : intake.pending ? "…" : "—"}
        </strong>
      </span>
    </button>
  );
}
