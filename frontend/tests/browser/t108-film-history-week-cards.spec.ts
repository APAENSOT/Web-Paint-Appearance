/**
 * T108 in a real browser: Film History walks Week -> card -> cars -> points.
 *
 * Mocked with `page.route` -- the live card totals are a GET-only check in
 * this task's report, and nothing here uploads. What this pins:
 *
 * * D-108-2 -- the four levels and a Back at each one, which lands exactly
 *   where it came from;
 * * D-108-3 -- the Model / Colour filters reach the Film reads, and T105's
 *   rule holds for Film: opening a card writes `filmWeek` / `filmCardModel`
 *   / `filmCardColor` and **never** `model` / `color`, so the filters are
 *   as the person left them after Back;
 * * D-108-4 -- every number on the card is the server's: the cars, the
 *   readings, the Box / No box counts and the incomplete count. The screen
 *   shows what the payload says, including a zero.
 *
 * Screenshots: desktop and 390, written to test-results/screenshots. 390 is
 * asserted free of horizontal page scroll.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";

type Vehicle = components["schemas"]["FilmVehicleOut"];
type Card = components["schemas"]["FilmCardOut"];

const SHOTS = "test-results/screenshots";
const MONTH = "2026-08";

const RANGER = "P703 DBL RANGER";
const SGL = "P703 SGL";
const WHITE = "Arctic White";
const BLACK = "Absolute / Shadow Black";

const BOX_CAR = "a".repeat(64);
const SECOND_CAR = "b".repeat(64);
const SGL_CAR = "c".repeat(64);

function vehicle(overrides: Partial<Vehicle>): Vehicle {
  return {
    logical_vehicle_id: BOX_CAR,
    plant_code: "FTM",
    measured_date: "2026-08-05",
    date_is_month_only: false,
    model: RANGER,
    model_display_name: null,
    color: BLACK,
    serial_no: null,
    job_nos: ["AW_DBL_1958197"],
    identity_complete: true,
    load_ids: [41],
    source_files: ["AW_DBL_1958197.xlsx"],
    mapped_point_count: 98,
    expected_point_count: 98,
    incomplete: false,
    box: "box",
    identity_note: null,
    ...overrides,
  };
}

/** Three cars: two Ranger of week 1, one Single CAP of week 3. */
const CARS: Vehicle[] = [
  vehicle({}),
  vehicle({
    logical_vehicle_id: SECOND_CAR,
    measured_date: "2026-08-06",
    job_nos: ["AW_DBL_1958198"],
    mapped_point_count: 64,
    incomplete: true,
  }),
  vehicle({
    logical_vehicle_id: SGL_CAR,
    measured_date: "2026-08-18",
    model: SGL,
    model_display_name: "Single CAP",
    color: WHITE,
    job_nos: ["AM_SGL_1961607"],
    mapped_point_count: 58,
    expected_point_count: 58,
    box: "no_box",
    identity_note: 'The Job Number\'s colour code "AM" and the file name\'s "AW" are different.',
  }),
];

function card(overrides: Partial<Card>): Card {
  return {
    model: RANGER,
    model_display_name: null,
    color: BLACK,
    vehicle_count: 2,
    point_count: 648,
    box_count: 2,
    no_box_count: 0,
    incomplete_count: 1,
    measured_date_min: "2026-08-05",
    measured_date_max: "2026-08-06",
    ...overrides,
  };
}

const SGL_CARD = card({
  model: SGL,
  model_display_name: "Single CAP",
  color: WHITE,
  vehicle_count: 1,
  point_count: 232,
  box_count: 0,
  no_box_count: 1,
  incomplete_count: 0,
  measured_date_min: "2026-08-18",
  measured_date_max: "2026-08-18",
});

const POINTS: components["schemas"]["FilmPointOut"][] = [
  {
    point_no: 1,
    point_code: "001HOOD",
    orientation: "H",
    src_location_text: "001HOOD",
    load_id: 41,
    source_row: 15,
    layers: { ecoat: "21.4", primer: "30.3", base: "18.2", clear: "40.1" },
    counted: true,
    is_complete_stop: false,
    // T109: a live point of the plant's standard list.
    is_extra: false,
    retired: false,
  },
  {
    point_no: 22,
    point_code: "022LTFTDOOR",
    orientation: "V",
    src_location_text: null,
    load_id: null,
    source_row: null,
    layers: { ecoat: null, primer: null, base: null, clear: null },
    counted: true,
    is_complete_stop: false,
    // T109: a live point of the plant's standard list.
    is_extra: false,
    retired: false,
  },
];

/**
 * The server's own grouping, mocked: the cards are by (week, model, colour)
 * and narrowed by the `model` / `color` query, and the cars of a card are
 * the cars of that week, model and colour. Nothing the screen does picks a
 * week -- it asks for one.
 */
async function mockFilm(page: Page) {
  const reads: URL[] = [];
  await page.route("**/api/v1/plants/*/filmthickness/**", (route) => {
    const url = new URL(route.request().url());
    reads.push(url);
    const common = {
      plant_code: "FTM",
      plant_is_active: true,
      active_data_source: "filmthickness_active",
    };
    const model = url.searchParams.get("model");
    const color = url.searchParams.get("color");
    const matching = CARS.filter(
      (item) => (!model || item.model === model) && (!color || item.color === color),
    );
    if (url.pathname.endsWith("facets"))
      return route.fulfill({
        json: {
          ...common,
          default_month: MONTH,
          months: [MONTH],
          month: url.searchParams.get("month"),
          model,
          color,
          models: url.searchParams.has("month") ? [RANGER, SGL] : [],
          colors: url.searchParams.has("month") ? [BLACK, WHITE] : [],
        },
      });
    if (url.pathname.endsWith("summaries")) {
      const weeks = [
        { week: 3, cards: [SGL_CARD] },
        { week: 1, cards: [card({})] },
      ]
        .map((item) => ({
          ...item,
          cards: item.cards.filter(
            (one) => (!model || one.model === model) && (!color || one.color === color),
          ),
        }))
        .filter((item) => item.cards.length)
        .map((item) => ({
          week: item.week,
          measured_date_min: item.cards[0].measured_date_min,
          measured_date_max: item.cards[0].measured_date_max,
          cards: item.cards,
        }));
      return route.fulfill({
        json: { ...common, month: url.searchParams.get("month"), model, color, weeks },
      });
    }
    if (url.pathname.endsWith("vehicles")) {
      const week = Number(url.searchParams.get("week")) || null;
      const items = matching.filter((item) => week === null || weekOf(item) === week);
      return route.fulfill({
        json: {
          ...common,
          month: url.searchParams.get("month"),
          week,
          model,
          color,
          items,
          page: { offset: 0, limit: 200, returned: items.length, total: items.length },
        },
      });
    }
    const id = url.pathname.split("/").at(-2);
    return route.fulfill({
      json: {
        ...common,
        vehicle: CARS.find((item) => item.logical_vehicle_id === id) ?? CARS[0],
        items: POINTS,
      },
    });
  });
  return reads;
}

/** The server's own band, as `domain.history.measured_week` writes it. The
 * screen never computes this -- the mock stands in for the server that does. */
const weekOf = (item: Vehicle) =>
  Math.min(5, Math.floor((Number(item.measured_date.slice(8)) - 1) / 7) + 1);

const film = (page: Page) => page.getByRole("region", { name: "Film Thickness" });

// =====================================================================
// 1. the four levels, and Back at each one
// =====================================================================
test("T108 Film History walks week cards, card, cars and points, with Back at each level", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  await mockFilm(page);
  await page.goto(`/plant/FTM?dataView=history&dataDomain=film&month=${MONTH}`);

  // Level 1: the weeks, newest first, with the server's counts on the cards.
  const panel = film(page);
  await expect(panel.getByRole("heading", { name: "Week 3" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Week 1" })).toBeVisible();
  const ranger = panel.getByRole("button", { name: new RegExp(`${RANGER} / `) });
  await expect(ranger).toContainText("2 cars");
  await expect(ranger).toContainText("648 readings");
  await expect(ranger).toContainText("Box 2");
  await expect(ranger).toContainText("No box 0");
  await expect(ranger).toContainText("Incomplete 1");
  await expect(ranger).toContainText("2026-08-05 to 2026-08-06");
  // The Single CAP card shows its display name, as its cars do.
  await expect(panel.getByRole("button", { name: /Single CAP \/ Arctic White/ })).toContainText(
    "No box 1",
  );
  await page.screenshot({ path: `${SHOTS}/T108-film-week-cards-desktop.png`, fullPage: true });

  // Level 2: the card's cars, and only its cars.
  await ranger.click();
  await expect(page).toHaveURL(/filmWeek=1/);
  await expect(page).toHaveURL(/filmCardModel=P703\+DBL\+RANGER/);
  await expect(panel.getByRole("heading", { name: `Week 1 / ${RANGER} / ${BLACK}` })).toBeVisible();
  await expect(panel.getByRole("button", { name: /AW_DBL_1958197/ })).toBeVisible();
  await expect(panel.getByRole("button", { name: /AW_DBL_1958198/ })).toBeVisible();
  await expect(panel.getByRole("button", { name: /AM_SGL_1961607/ })).toHaveCount(0);
  await expect(panel.getByText("Mapped points: 64 / 98 | Incomplete")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/T108-film-card-cars-desktop.png`, fullPage: true });

  // Level 3: one car's catalogue points.
  await panel.getByRole("button", { name: /AW_DBL_1958197/ }).click();
  await expect(page).toHaveURL(new RegExp(`filmVehicle=${BOX_CAR}`));
  await expect(panel.getByRole("heading", { name: /Catalogue points \(2\)/ })).toBeVisible();
  await expect(panel.getByRole("region", { name: "Horizontal points" })).toContainText("001HOOD");
  await expect(panel.getByRole("region", { name: "Vertical points" })).toContainText(
    "Not measured",
  );
  await page.screenshot({ path: `${SHOTS}/T108-film-points-desktop.png`, fullPage: true });

  // Back, three times, each one to where it came from.
  await panel.getByRole("button", { name: "Back to vehicles" }).click();
  await expect(page).not.toHaveURL(/filmVehicle/);
  await expect(panel.getByRole("button", { name: /AW_DBL_1958198/ })).toBeVisible();
  await panel.getByRole("button", { name: "Back to week cards" }).click();
  await expect(page).not.toHaveURL(/filmWeek|filmCardModel|filmCardColor/);
  await expect(panel.getByRole("heading", { name: "Week 3" })).toBeVisible();
  await expect(panel.getByRole("button", { name: /Single CAP \/ Arctic White/ })).toBeVisible();
  await expect(page).toHaveURL(/dataDomain=film/);
  await expect(page).toHaveURL(new RegExp(`month=${MONTH}`));
});

// =====================================================================
// 2. T105's rule, for Film (D-108-3)
// =====================================================================
test("T108 opening a Film card leaves the filters as they were", async ({ page }) => {
  await mockHistory(page, "viewer");
  const reads = await mockFilm(page);
  await page.goto(`/plant/FTM?dataView=history&dataDomain=film&month=${MONTH}`);
  const panel = film(page);
  const model = page.getByRole("combobox", { name: "Model" });
  const colour = page.getByRole("combobox", { name: "Colour" });
  await expect(model).toHaveValue("");
  await expect(colour).toHaveValue("");

  await panel.getByRole("button", { name: new RegExp(`${RANGER} / `) }).click();
  await expect(page).toHaveURL(/filmCardModel=/);
  // The card's identity is not a filter: neither dropdown moved, and the URL
  // carries no `model=` or `color=`.
  await expect(model).toHaveValue("");
  await expect(colour).toHaveValue("");
  await expect(page).not.toHaveURL(/[?&]model=/);
  await expect(page).not.toHaveURL(/[?&]color=/);

  await panel.getByRole("button", { name: "Back to week cards" }).click();
  await expect(model).toHaveValue("");
  await expect(colour).toHaveValue("");
  const cards = reads.filter((url) => url.pathname.endsWith("summaries"));
  expect(cards.at(-1)?.searchParams.get("model")).toBe(null);
  expect(cards.at(-1)?.searchParams.get("color")).toBe(null);
});

test("T108 a filter set by hand reaches the Film reads and survives the card", async ({ page }) => {
  await mockHistory(page, "viewer");
  const reads = await mockFilm(page);
  await page.goto(`/plant/FTM?dataView=history&dataDomain=film&month=${MONTH}`);
  const panel = film(page);
  // D-108-3: Film honours Model / Colour. Before T108 this list ignored them.
  await page.getByRole("combobox", { name: "Model" }).selectOption(SGL);
  await expect(page).toHaveURL(/[?&]model=P703\+SGL/);
  await expect(panel.getByRole("button", { name: /Single CAP \/ Arctic White/ })).toBeVisible();
  await expect(panel.getByRole("button", { name: new RegExp(`${RANGER} / `) })).toHaveCount(0);
  await expect
    .poll(() =>
      reads.some(
        (url) => url.pathname.endsWith("summaries") && url.searchParams.get("model") === SGL,
      ),
    )
    .toBe(true);

  // Opening the card keeps the filter, and Back keeps it too (T105's rule).
  await panel.getByRole("button", { name: /Single CAP \/ Arctic White/ }).click();
  await expect(panel.getByRole("button", { name: /AM_SGL_1961607/ })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Model" })).toHaveValue(SGL);
  await panel.getByRole("button", { name: "Back to week cards" }).click();
  await expect(page.getByRole("combobox", { name: "Model" })).toHaveValue(SGL);
  await expect(panel.getByRole("button", { name: new RegExp(`${RANGER} / `) })).toHaveCount(0);

  // And changing a filter closes an open card (D-105-3, for Film).
  await panel.getByRole("button", { name: /Single CAP \/ Arctic White/ }).click();
  await expect(page).toHaveURL(/filmWeek=3/);
  await page.getByRole("combobox", { name: "Model" }).selectOption("");
  await expect(page).not.toHaveURL(/filmWeek|filmCardModel|filmCardColor/);
  await expect(panel.getByRole("button", { name: new RegExp(`${RANGER} / `) })).toBeVisible();
});

// =====================================================================
// 3. 390 width
// =====================================================================
test("T108 Film week cards and the card's cars fit 390 with no horizontal scroll", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockHistory(page, "viewer");
  await mockFilm(page);
  await page.goto(`/plant/FTM?dataView=history&dataDomain=film&month=${MONTH}`);
  const panel = film(page);
  const noScroll = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    );
  await expect(panel.getByRole("button", { name: new RegExp(`${RANGER} / `) })).toBeVisible();
  expect(await noScroll()).toBe(true);
  await page.screenshot({ path: `${SHOTS}/T108-film-week-cards-390.png`, fullPage: true });

  await panel.getByRole("button", { name: new RegExp(`${RANGER} / `) }).click();
  await expect(panel.getByRole("button", { name: /AW_DBL_1958197/ })).toBeVisible();
  expect(await noScroll()).toBe(true);
  await page.screenshot({ path: `${SHOTS}/T108-film-card-cars-390.png`, fullPage: true });
});
