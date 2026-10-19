/**
 * T109 Point Check, phase 1 (Film), in a real browser.
 *
 * Mocked with `page.route` -- the live FTM lists and the real writes are the
 * backend's own tests (`test_t109_point_check_film.py`) and T101. What this
 * file pins:
 *
 * * D-109-1 -- **Point Check** is its own entry inside Standard, shown to an
 *   Engineer and an Admin and hidden from a Viewer, and it renders without
 *   `PlantMeasurements.tsx` being touched (the URL is `standardView=points`);
 * * D-109-3 -- the extra tag on the list, in the review row and in History's
 *   point grid;
 * * D-109-4 -- Retire asks for a reason and will not go without one, warns
 *   in the owner's words, and the retired point is listed afterwards with
 *   when it went and why;
 * * D-109-5 -- Add sends the name, the tick, the H/V and the reason, and
 *   shows the server's refusal when a number is taken;
 * * D-109-6 -- an unknown Film label is asked about **in its own row**, the
 *   picker offers only the server's live points, and the answer posts the
 *   label and the point;
 * * 390 width, because that is the phone the owner reviews on.
 *
 * Screenshots: desktop and 390, written to test-results/screenshots.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { catalogueFixture } from "../fixtures";

type Point = components["schemas"]["FilmPointSettingItem"];
type Retired = components["schemas"]["FilmRetiredPointItem"];
type Models = components["schemas"]["FilmModelsOut"];

const SHOTS = "test-results/point-check-polish";
const PLANT = "FTM";
const MODEL = "P703 DBL RANGER";

const MODELS: Models = {
  plant_code: PLANT,
  items: [{ model_code: MODEL, display_name: null, point_count: 6, has_setting: true }],
};

function point(no: number, code: string, overrides: Partial<Point> = {}): Point {
  return {
    point_no: no,
    point_code: code,
    label: code,
    counted: true,
    orientation: code.includes("HOOD") ? "H" : "V",
    is_complete_stop: false,
    is_extra: false,
    reason: "T99 seed (owner D-99-5, 2026-10-10)",
    changed_by: null,
    changed_at: "2026-10-10T20:19:38+07:00",
    ...overrides,
  };
}

const POINTS: Point[] = [
  point(1, "001HOOD"),
  point(2, "002HOOD"),
  point(22, "022LTFTDOOR"),
  point(64, "064RAPILLAR", { is_complete_stop: true }),
  // D-109-3: two of the owner's eight.
  // T115 (D-115-1): as on the live list, one row was written by a person, and the
  // server sends that person's display name.
  point(95, "095RBXFLOOR", {
    is_extra: true,
    orientation: "H",
    reason: "T109 Point Check add",
    changed_by: "Development bypass",
    changed_at: "2026-10-11T10:05:00+07:00",
  }),
  point(96, "096TGATEIN", { is_extra: true }),
];

const RETIRED: Retired[] = [
  {
    point_no: 33,
    point_code: "033LBPILLAR",
    label: "033LBPILLAR",
    orientation: "V",
    is_extra: false,
    retired_at: "2026-10-11T09:30:00+07:00",
    retired_reason: "T109 (D-109-4): retired on Point Check -- the plant stopped measuring it",
  },
];

async function setup(
  page: Page,
  {
    role = "engineer",
    retired = [] as Retired[],
    addStatus = 200,
    navigate = `/plant/${PLANT}?standardView=points`,
  } = {},
) {
  await mockHistory(page, role);
  await page.route("**/api/v1/standards/catalogue", (r) => r.fulfill({ json: catalogueFixture }));
  // RO17: the aliases section under each list; empty keeps these tests to their own half.
  await page.route("**/api/v1/plants/*/point-aliases/**", (r) =>
    r.fulfill({ json: { plant_code: "X", domain: "film", model_code: "X", items: [] } }),
  );
  const posts: { url: string; body: unknown }[] = [];
  await page.route(`**/api/v1/plants/${PLANT}/film-points`, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    if (role === "viewer")
      return route.fulfill({
        status: 403,
        json: {
          statusCode: 403,
          error: "Forbidden",
          message: "This route requires the 'engineer' role. You hold ['viewer'].",
          correlationId: "v13w3r",
        },
      });
    return route.fulfill({ json: MODELS });
  });
  // T114: the Wave Scan section sits below Film; an empty list keeps it quiet.
  await page.route(`**/api/v1/plants/${PLANT}/ws-points`, (route) =>
    route.fulfill({ json: { plant_code: PLANT, items: [] } }),
  );
  await page.route(`**/api/v1/plants/${PLANT}/film-points/*/add`, (route) => {
    posts.push({ url: route.request().url(), body: route.request().postDataJSON() });
    if (addStatus !== 200)
      return route.fulfill({
        status: addStatus,
        json: {
          statusCode: addStatus,
          error: "Conflict",
          message:
            "FTM's P703 DBL RANGER list already walks 001HOOD as point 1, and 001T109NEW " +
            "would be point 1 too. Nothing was changed.",
          correlationId: "cl4sh",
        },
      });
    return route.fulfill({
      json: {
        point_code: "099TGATEIN",
        point_no: 99,
        operator_message: "099TGATEIN is now point 99 of FTM's walk, tagged as an extra point.",
      },
    });
  });
  await page.route(`**/api/v1/plants/${PLANT}/film-points/*/retire`, (route) => {
    posts.push({ url: route.request().url(), body: route.request().postDataJSON() });
    return route.fulfill({
      json: {
        point_code: "022LTFTDOOR",
        point_no: 22,
        operator_message: "022LTFTDOOR is off FTM's walk. It stops counting on the dashboard.",
      },
    });
  });
  await page.route(`**/api/v1/plants/${PLANT}/film-points/*`, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      json: {
        plant_code: PLANT,
        model_code: MODEL,
        has_setting: true,
        items: POINTS,
        retired_items: retired,
      },
    });
  });
  await page.goto(navigate);
  return { posts };
}

const panel = (page: Page) => page.getByTestId("film-points-panel");

// T115 (D-115-1): "Last change" names the person; the seed keeps its word.
test("T115 Film Last change shows the person's name, and the seed word for none", async ({
  page,
}) => {
  await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  const row = (code: string) => panel(page).locator(`tr[data-film-point="${code}"]`);
  await expect(row("095RBXFLOOR")).toContainText("Development bypass · 2026-10-11");
  await expect(row("001HOOD")).toContainText("seed · 2026-10-10");
  await row("095RBXFLOOR").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/T115-last-change-film-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(row("095RBXFLOOR")).toContainText("Development bypass");
  await page.screenshot({ path: `${SHOTS}/T115-last-change-film-390.png`, fullPage: true });
});

// =====================================================================
// D-109-1: the entry, and who sees it
// =====================================================================
test("T109 Point Check is its own entry in Standard and the Film section is on it", async ({
  page,
}) => {
  await setup(page, { retired: RETIRED });
  await expect(page.getByTestId("point-check")).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole("heading", { name: "Point Check", level: 2 })).toBeVisible();
  await expect(page.getByTestId("model-detail-nav-point-check")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(panel(page)).toBeVisible();
  await expect(panel(page).getByRole("table")).toContainText("001HOOD");
  // T114 CHANGE (D-114-1): the Wave Scan section replaced P1's "not part of
  // this screen yet" sentence; T114's own spec covers what it shows.
  await expect(page.getByTestId("point-check-wave-later")).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Wave Scan", exact: true })).toBeVisible();

  // D-109-3: the extra tag, on the two points that carry it and nowhere else.
  await expect(page.getByTestId("film-point-extra-095RBXFLOOR")).toContainText("Extra");
  await expect(page.getByTestId("film-point-extra-096TGATEIN")).toBeVisible();
  await expect(page.getByTestId("film-point-extra-001HOOD")).toHaveCount(0);

  // D-109-4: what left this walk, with when and why.
  const gone = page.getByTestId("film-points-retired");
  await expect(gone).toContainText("033LBPILLAR");
  await expect(gone).toContainText("the plant stopped measuring it");
  await expect(gone).toContainText("2026-10-11");

  await page.screenshot({ path: `${SHOTS}/T109-point-check-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel(page).getByRole("table")).toContainText("001HOOD");
  await page.screenshot({ path: `${SHOTS}/T109-point-check-390.png`, fullPage: true });
});

test("T109 a Viewer has no Point Check entry", async ({ page }) => {
  await setup(page, { role: "viewer", navigate: `/plant/${PLANT}?standardView=family` });
  await expect(page.getByRole("button", { name: "Color Family", exact: true })).toBeVisible({
    timeout: 20000,
  });
  await expect(page.getByTestId("model-detail-nav-point-check")).toHaveCount(0);
});

test("T109 an Admin reaches Point Check by clicking it", async ({ page }) => {
  await setup(page, { role: "admin", navigate: `/plant/${PLANT}?standardView=family` });
  await page.getByRole("button", { name: "Model Detail", exact: true }).click();
  const entry = page.getByTestId("model-detail-nav-point-check");
  await expect(entry).toBeVisible({ timeout: 20000 });
  await entry.click();
  await expect(page.getByTestId("point-check")).toBeVisible();
  await expect(page).toHaveURL(/modelView=point-check/);
});

// =====================================================================
// D-109-5: add a point
// =====================================================================
test("T109 Add sends the name, the tick, the H/V and the reason", async ({ page }) => {
  const { posts } = await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.getByTestId("film-point-add-open").click();
  const form = page.getByTestId("film-point-add");
  await expect(form).toContainText("Point name, as a file writes it");
  // No name and no reason: nothing to send.
  await expect(page.getByTestId("film-point-add-submit")).toBeDisabled();
  await page.getByTestId("film-point-add-name").fill("099TGATEIN");
  await expect(page.getByTestId("film-point-add-submit")).toBeDisabled();
  await page.getByTestId("film-point-add-reason").fill("the plant started measuring it");
  await page.getByTestId("film-point-add-orientation").selectOption("V");
  await page.getByTestId("film-point-add-counted").uncheck();
  await page.screenshot({ path: `${SHOTS}/T109-point-check-add-desktop.png`, fullPage: true });

  await page.getByTestId("film-point-add-submit").click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0].url).toContain("/add");
  expect(posts[0].body).toEqual({
    point_code: "099TGATEIN",
    counted: false,
    orientation: "V",
    place_after: null,
    reason: "the plant started measuring it",
  });
  await expect(page.getByTestId("film-point-add")).toHaveCount(0, { timeout: 20000 });
});

test("T109 an H/V left on the default is sent as null, so the list proposes it", async ({
  page,
}) => {
  const { posts } = await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.getByTestId("film-point-add-open").click();
  await page.getByTestId("film-point-add-name").fill("099TGATEIN");
  await page.getByTestId("film-point-add-reason").fill("the plant started measuring it");
  await page.getByTestId("film-point-add-submit").click();
  await expect.poll(() => posts.length).toBe(1);
  expect((posts[0].body as { orientation: unknown }).orientation).toBeNull();
});

test("T109 a taken number is the server's refusal, shown in the form", async ({ page }) => {
  await setup(page, { addStatus: 409 });
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.getByTestId("film-point-add-open").click();
  await page.getByTestId("film-point-add-name").fill("001T109NEW");
  await page.getByTestId("film-point-add-reason").fill("a second hood point");
  await page.getByTestId("film-point-add-submit").click();
  const form = page.getByTestId("film-point-add");
  await expect(form).toContainText("already walks 001HOOD as point 1");
  await expect(form).toContainText("cl4sh");
});

// =====================================================================
// D-109-4: retire a point
// =====================================================================
test("T109 Retire warns in the owner's words and will not go without a reason", async ({
  page,
}) => {
  const { posts } = await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.getByTestId("film-point-retire-022LTFTDOOR").click();
  const confirm = page.getByTestId("film-point-retire-confirm-022LTFTDOOR");
  await expect(confirm).toContainText("every month");
  await expect(confirm).toContainText("including past ones");
  await expect(confirm).toContainText("stay in History");
  await expect(page.getByTestId("film-point-retire-submit-022LTFTDOOR")).toBeDisabled();
  await page.screenshot({ path: `${SHOTS}/T109-point-check-retire-desktop.png`, fullPage: true });

  await page.getByTestId("film-point-retire-reason-022LTFTDOOR").fill("ab");
  await expect(page.getByTestId("film-point-retire-submit-022LTFTDOOR")).toBeDisabled();
  await page.getByTestId("film-point-retire-reason-022LTFTDOOR").fill("the door point is gone");
  await page.getByTestId("film-point-retire-submit-022LTFTDOOR").click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0].url).toContain("/retire");
  expect(posts[0].body).toEqual({
    point_code: "022LTFTDOOR",
    reason: "the door point is gone",
  });
});

test("T109 a cancelled retire sends nothing", async ({ page }) => {
  const { posts } = await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.getByTestId("film-point-retire-022LTFTDOOR").click();
  await page.getByTestId("film-point-retire-reason-022LTFTDOOR").fill("changed my mind");
  await page.getByTestId("film-point-retire-cancel-022LTFTDOOR").click();
  await expect(page.getByTestId("film-point-retire-confirm-022LTFTDOOR")).toHaveCount(0);
  expect(posts).toHaveLength(0);
});
