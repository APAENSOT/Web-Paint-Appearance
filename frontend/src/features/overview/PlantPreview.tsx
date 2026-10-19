import { lazy, Suspense, useState } from "react";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, ArrowUpRight, Building2, ChevronRight, MapPin } from "lucide-react";
import { FEED_LEVEL_LABEL, PLANTS, type Plant } from "@/lib/ct/data";
import type { FactoryDomain } from "./FactoryStage";
import { PLANT_MEDIA } from "./plant-media";
import { sinceText, type PlantFeed } from "./plant-feed";
import { monthTitle, calendarYearMonth } from "@/features/measurements/overview-display";

const FactoryStage = lazy(() => import("./FactoryStage"));

export function PlantPreview({
  feeds,
  country,
  plant,
  domain,
  onDomain,
  onPlant,
  onBack,
  reduced,
  paused,
  highlighted,
  onHighlight,
}: {
  feeds: Record<string, PlantFeed>;
  country: string;
  plant: Plant | null;
  domain: FactoryDomain;
  onDomain: (domain: FactoryDomain) => void;
  onPlant: (plant: Plant) => void;
  onBack: () => void;
  reduced: boolean;
  paused: boolean;
  highlighted: string | null;
  onHighlight: (id: string | null) => void;
}) {
  const [pointerNavigation, setPointerNavigation] = useState(false);
  const plants = PLANTS.filter((item) => item.country === country);
  const feed = plant ? feeds[plant.code] : undefined;
  const status = feed?.status ?? null;
  const last = feed?.latest[0];
  return (
    <aside className="panel plant-preview" aria-label="Plant preview">
      <header className="plant-preview__header">
        <div>
          <span className="plant-preview__location">
            <MapPin size={14} />
            {country}
          </span>
          <h2>
            {plant ? (
              <>
                <span className="plant-preview__identity">{plant.code}</span> · Plant preview
              </>
            ) : (
              "Explore the plants"
            )}
          </h2>
        </div>
        <button
          type="button"
          className="plant-preview__back"
          onClick={onBack}
          aria-label="Back to all plants"
        >
          <ArrowLeft size={16} />
        </button>
      </header>
      <div className="plant-preview__plant-picker" aria-label={`Plants in ${country}`}>
        {plants.map((item) => (
          <button
            type="button"
            key={item.id}
            onClick={() => onPlant(item)}
            aria-pressed={plant?.id === item.id}
          >
            <Building2 size={15} />
            <strong>{item.code}</strong>
            <span>{item.name}</span>
            <ChevronRight size={14} />
          </button>
        ))}
      </div>
      {plant ? (
        <>
          <Suspense
            fallback={
              <div className="factory-stage factory-stage__fallback" role="status">
                <Building2 size={42} strokeWidth={1} />
                <span>Preparing factory preview…</span>
              </div>
            }
          >
            <FactoryStage
              code={plant.code}
              domain={domain}
              onDomain={onDomain}
              reduced={reduced}
              paused={paused}
            />
          </Suspense>
          <div className="plant-preview__content">
            <div className="plant-preview__domains" aria-label="Factory areas">
              <button
                type="button"
                aria-pressed={domain === "wave"}
                onClick={() => onDomain("wave")}
              >
                Wave Scan
              </button>
              <button
                type="button"
                aria-pressed={domain === "film"}
                onClick={() => onDomain("film")}
              >
                Film Thickness
              </button>
            </div>
            <p className="plant-preview__domain-copy">
              {domain === "wave"
                ? "Paint appearance · Wave Scan reporting"
                : "Coating thickness · Film Thickness reporting"}
            </p>
            <div className="plant-preview__summary" aria-live="polite">
              <h3>{plant.name}</h3>
              <dl>
                <div>
                  <dt>Data feed</dt>
                  <dd style={{ color: status ? `var(--${status.level})` : undefined }}>
                    {status && <i style={{ background: `var(--${status.level})` }} />}
                    {status
                      ? FEED_LEVEL_LABEL[status.level]
                      : feed?.pending
                        ? "Checking…"
                        : feed?.error
                          ? "Unavailable"
                          : "No control plan"}
                  </dd>
                </div>
                <div>
                  <dt>Last upload</dt>
                  <dd title={last?.source_file}>
                    {last
                      ? `${sinceText(last.started_at)} ago`
                      : feed?.pending
                        ? "Checking…"
                        : feed?.error
                          ? "Unavailable"
                          : "No uploads yet"}
                  </dd>
                </div>
                <div>
                  <dt>Reporting line</dt>
                  <dd>{plant.line}</dd>
                </div>
              </dl>
              <p>
                {feed?.pending
                  ? "Loading the weekly upload plan…"
                  : feed?.error
                    ? "Plant status could not load. Retry from the notice above."
                    : feedSentence(status)}
              </p>
              <small>
                Weekly upload plan · {monthTitle(calendarYearMonth())} · live measurements are in
                the dashboard.
              </small>
            </div>
            <Link
              to="/plant/$code"
              params={{ code: plant.code.toLowerCase() }}
              search={{ paint: domain === "film" ? "film" : undefined }}
              className="plant-preview__open"
              onPointerDown={() => setPointerNavigation(true)}
              onKeyDown={() => setPointerNavigation(false)}
              viewTransition={
                !reduced && pointerNavigation ? { types: ["plant-dashboard"] } : false
              }
            >
              Open {plant.code} dashboard
              <ArrowUpRight size={17} />
            </Link>
          </div>
        </>
      ) : (
        <div className="plant-photo-list">
          {plants.map((item) => (
            <button
              type="button"
              key={item.id}
              className="plant-photo"
              data-highlighted={highlighted === item.id}
              aria-label={`Explore ${item.code} factory photo`}
              onClick={() => onPlant(item)}
              onMouseEnter={() => onHighlight(item.id)}
              onMouseLeave={() => onHighlight(null)}
              onFocus={() => onHighlight(item.id)}
              onBlur={() => onHighlight(null)}
            >
              <img
                src={PLANT_MEDIA[item.code].src}
                alt={PLANT_MEDIA[item.code].alt}
                width="640"
                height="360"
                loading="lazy"
              />
              <span className="plant-photo__body">
                <strong>
                  {item.code} · {item.name}
                </strong>
                <span>{PLANT_MEDIA[item.code].caption}</span>
                <span className="plant-photo__action">
                  Explore plant <ArrowUpRight size={16} />
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}

function feedSentence(status: PlantFeed["status"]): string {
  if (!status) return "No standard models or colours set for this plant yet.";
  const missed = status.missing
    ? `${status.missing} past week${status.missing > 1 ? "s" : ""} missing`
    : status.late
      ? `${status.late} past week${status.late > 1 ? "s" : ""} late or incomplete`
      : "Every past week on time";
  return `${missed}. Week ${status.week}: ${status.coloursThisWeek} of ${status.colours} colours in so far.`;
}
