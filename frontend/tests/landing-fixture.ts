import type { Page } from "@playwright/test";

/** Controlled GET /landing/status for browser specs. Invented values, never shipped. */
export function landingFixture(now = Date.now()) {
  const ago = (hours: number) => new Date(now - hours * 3_600_000).toISOString();
  const groups = (graded: number, passed: number) =>
    (["WAVESCAN_H", "WAVESCAN_V", "FILM_H", "FILM_V"] as const).map((group) => ({
      group,
      graded,
      passed,
    }));
  const file = (load_id: number, source_file: string, hours: number, domain = "FILMTHICKNESS") => ({
    load_id,
    source_file,
    file_hash: `hash-${load_id}`,
    status: "COMMITTED",
    domain,
    started_at: ago(hours),
  });
  const feed = (
    level: "UPDATE" | "LATE" | "MISSING",
    pct: number,
    late: number,
    missing: number,
  ) => ({
    level,
    pct,
    week: 2,
    late_weeks: late,
    missing_weeks: missing,
    colours_this_week: 3,
    colours: 9,
    models: 4,
  });
  return {
    as_of: new Date(now).toISOString(),
    month: new Date(now).toISOString().slice(0, 7),
    rules: "fixture",
    plants: [
      {
        plant_code: "FTM",
        quality: { pct: 92.5, groups: groups(4, 4) },
        feed: feed("UPDATE", 62.5, 0, 0),
        wavescan_cars: 47,
        film_cars: 169,
        latest_files: [
          file(4, "FTM film 4.xlsx", 2),
          file(3, "FTM film 3.xlsx", 5),
          file(2, "FTM ws.xlsx", 30, "WAVESCAN"),
          file(1, "FTM film 1.xlsx", 80),
        ],
      },
      {
        plant_code: "FVL",
        quality: { pct: null, groups: groups(0, 0) },
        feed: feed("MISSING", 0, 0, 1),
        wavescan_cars: 0,
        film_cars: 0,
        latest_files: [],
      },
      {
        plant_code: "SAP",
        quality: { pct: 45, groups: groups(4, 2) },
        feed: feed("MISSING", 4, 0, 1),
        wavescan_cars: 12,
        film_cars: 3,
        latest_files: [file(9, "SAP ws.xlsx", 200, "WAVESCAN")],
      },
      {
        plant_code: "AAT",
        quality: { pct: 70, groups: groups(10, 7) },
        feed: feed("LATE", 20.8, 1, 0),
        wavescan_cars: 135,
        film_cars: 34,
        latest_files: [file(7, "2507955 U704 JDC.xlsx", 25)],
      },
    ],
  };
}

export async function mockLanding(page: Page, fixture = landingFixture()) {
  await page.route("**/api/v1/landing/status**", (route) => route.fulfill({ json: fixture }));
}
