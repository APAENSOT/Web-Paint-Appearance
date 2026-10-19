import { useQuery } from "@tanstack/react-query";
import { landingStatusOptions } from "@/api/queries";
import type { components } from "@/api/types";
import type { Risk } from "@/lib/ct/data";

type LandingPlant = components["schemas"]["LandingPlant"];
export type LandingFile = components["schemas"]["LandingFile"];

export type FeedStatus = {
  level: Risk;
  pct: number;
  week: number;
  late: number;
  missing: number;
  coloursThisWeek: number;
  colours: number;
};

/** Everything a plant's card, sidebar row, preview and map pin show. All API fields. */
export type PlantFeed = {
  status: FeedStatus | null;
  quality: number | null;
  pending: boolean;
  error: boolean;
  wavescanCars: number | null;
  filmCars: number | null;
  latest: LandingFile[];
};

const LEVEL: Record<NonNullable<LandingPlant["feed"]>["level"], Risk> = {
  UPDATE: "nominal",
  LATE: "caution",
  MISSING: "critical",
};

export function toPlantFeed(
  plant: LandingPlant | undefined,
  pending: boolean,
  error: boolean,
): PlantFeed {
  const f = plant?.feed;
  return {
    status: f
      ? {
          level: LEVEL[f.level],
          pct: f.pct,
          week: f.week,
          late: f.late_weeks,
          missing: f.missing_weeks,
          coloursThisWeek: f.colours_this_week,
          colours: f.colours,
        }
      : null,
    quality: plant?.quality.pct ?? null,
    pending,
    error,
    wavescanCars: plant?.wavescan_cars ?? null,
    filmCars: plant?.film_cars ?? null,
    latest: plant?.latest_files ?? [],
  };
}

/** Card bar colour for the month-to-date share: 0-50 red, 51-80 yellow, 81-100 green. */
export function scoreLevel(score: number): Risk {
  return score > 80 ? "nominal" : score > 50 ? "caution" : "critical";
}

/** "4m", "3h", "2d" since an ISO time. */
export function sinceText(iso: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / 1440)}d`;
}

const CODES = ["FTM", "AAT", "FVL", "SAP"] as const;

/** All four plants, keyed by plant code, from the one landing read. */
export function usePlantFeeds(): Record<string, PlantFeed> {
  const landing = useQuery(landingStatusOptions);
  return Object.fromEntries(
    CODES.map((code) => [
      code,
      toPlantFeed(
        landing.data?.plants.find((p) => p.plant_code === code),
        landing.isPending,
        landing.isError,
      ),
    ]),
  );
}

export function feedView(feed: PlantFeed) {
  return {
    pending: feed.pending,
    error: feed.error,
    level: feed.status?.level ?? null,
    wavescanCars: feed.wavescanCars,
    filmCars: feed.filmCars,
    files: feed.latest.map((b) => ({
      key: b.file_hash,
      domain: b.domain === "FILMTHICKNESS" ? "FT" : "WS",
      name: b.source_file,
      status: b.status,
      since: sinceText(b.started_at),
    })),
  };
}
