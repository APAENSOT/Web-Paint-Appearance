/**
 * T100 Part C in a real browser: the Points panel in the Standard tab.
 *
 * Mocked with `page.route` -- the live FTM lists are read by the backend's
 * own tests, and the real files are T101. What this pins:
 *
 * * D-100-3 -- the panel is inside the Standard tab's Film section, so it is
 *   reached without touching `PlantMeasurements.tsx`;
 * * D-100-6 -- Save warns about past months and will not go without a
 *   reason, and the POST carries **only** the points that changed;
 * * D-99-12 -- a plant with no setting gets a read-only list and says so;
 * * a 403 shows its message and its correlation id, like every other error.
 *
 * Screenshots: desktop and 390, written to test-results/screenshots.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { catalogueFixture } from "../fixtures";
import { filmStandardsFixture } from "../film-standards-fixtures";

type Point = components["schemas"]["FilmPointSettingItem"];
type Models = components["schemas"]["FilmModelsOut"];

const SHOTS = "test-results/screenshots";

const MODELS: Models = {
  plant_code: "FTM",
  items: [
    { model_code: "P703 DBL RANGER", display_name: null, point_count: 98, has_setting: true },
    { model_code: "P703 SGL", display_name: "Single CAP", point_count: 58, has_setting: true },
  ],
};

function point(no: number, code: string, overrides: Partial<Point> = {}): Point {
  return {
    point_no: no,
    point_code: code,
    label: code,
    counted: true,
    orientation: code.includes("HOOD") || code.includes("ROOF") ? "H" : "V",
    is_complete_stop: false,
    // T109 (D-109-3): false unless a case says otherwise.
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
  point(3, "023ROOF"),
  point(4, "035LBPILLAR"),
  point(5, "058RTFEND", { is_complete_stop: true }),
];

async function setup(
  page: Page,
  {
    hasSetting = true,
    fail = false,
    role = "admin",
    standards = "ok",
    modelsStatus = 200,
    navigate,
  }: {
    hasSetting?: boolean;
    fail?: boolean;
    role?: string;
    standards?: "ok" | "500";
    modelsStatus?: number;
    navigate?: string;
  } = {},
) {
  await mockHistory(page, role);
  await page.route("**/api/v1/standards/catalogue", (r) => r.fulfill({ json: catalogueFixture }));
  // RO17: the aliases section under each list; empty keeps these tests to their own half.
  await page.route("**/api/v1/plants/*/point-aliases/**", (r) =>
    r.fulfill({ json: { plant_code: "X", domain: "film", model_code: "X", items: [] } }),
  );
  // T100-FIX (D-100-8): the Points panel does not wait on the standards read
  // and is not behind its Admin gate, so these two answer independently.
  await page.route("**/api/v1/plants/*/filmthickness/standards", (r) =>
    standards === "ok"
      ? r.fulfill({ json: filmStandardsFixture })
      : r.fulfill({
          status: 500,
          json: {
            statusCode: 500,
            error: "Internal Server Error",
            message: "Film standards are unavailable.",
            correlationId: "stand4rds",
          },
        }),
  );
  const posts: unknown[] = [];
  await page.route("**/api/v1/plants/FTM/film-points", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    if (modelsStatus !== 200)
      return route.fulfill({
        status: modelsStatus,
        json: {
          statusCode: modelsStatus,
          error: "Forbidden",
          message: "This route requires the 'engineer' role. You hold ['viewer'].",
          correlationId: "v13w3r",
        },
      });
    return route.fulfill({
      json: hasSetting
        ? MODELS
        : { ...MODELS, items: MODELS.items.map((m) => ({ ...m, has_setting: false })) },
    });
  });
  await page.route("**/api/v1/plants/FTM/film-points/*", (route) => {
    if (route.request().method() === "POST") {
      posts.push(route.request().postDataJSON());
      if (fail)
        return route.fulfill({
          status: 403,
          json: {
            statusCode: 403,
            error: "Forbidden",
            message: "This route requires the 'engineer' role.",
            correlationId: "c0rr3lat10n",
          },
        });
      return route.fulfill({
        json: { rows_written: 2, operator_message: "2 point(s) changed." },
      });
    }
    return route.fulfill({
      json: {
        plant_code: "FTM",
        model_code: "P703 DBL RANGER",
        has_setting: hasSetting,
        items: POINTS,
      },
    });
  });
  // T109 (D-109-1): the panel moved out of the Film Thickness standards
  // screen and is the Film section of Point Check now. Same panel, same
  // test ids, one entry along in Standard.
  await page.goto(navigate ?? "/plant/FTM?standardView=points");
  return { posts };
}

function panel(page: Page) {
  return page.getByTestId("film-points-panel");
}

test("T100 the Points panel lists the walk and sends only what changed, with a reason", async ({
  page,
}) => {
  const { posts } = await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  // Walk order, the stop marker, and the seed's provenance.
  const table = panel(page).getByRole("table");
  await expect(table).toContainText("001HOOD");
  await expect(table).toContainText("058RTFEND");
  await expect(table).toContainText("Complete stop");
  await expect(table).toContainText("seed");
  await expect(page.getByTestId("film-points-changed")).toContainText("Nothing has changed");
  await expect(page.getByTestId("film-points-save")).toBeDisabled();

  // Two changes: one tick off, one orientation flipped.
  await page.getByTestId("film-point-counted-035LBPILLAR").uncheck();
  await page.getByTestId("film-point-orientation-023ROOF").selectOption("V");
  await expect(page.getByTestId("film-points-changed")).toContainText("2 points changed");

  await page.screenshot({
    path: `${SHOTS}/T100-points-page-desktop.png`,
    fullPage: true,
  });

  // D-100-6: the warning, then the reason, then the save.
  await page.getByTestId("film-points-save").click();
  const confirm = page.getByTestId("film-points-confirm");
  await expect(confirm).toContainText("including past ones");
  await expect(confirm).toContainText("FTM");
  await expect(page.getByTestId("film-points-save-confirm")).toBeDisabled();
  await page.getByTestId("film-points-reason").fill("ab");
  await expect(page.getByTestId("film-points-save-confirm")).toBeDisabled();
  await page.getByTestId("film-points-reason").fill("the box walk changed in September");
  await expect(page.getByTestId("film-points-save-confirm")).toBeEnabled();
  await page.getByTestId("film-points-save-confirm").click();

  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toEqual({
    points: [
      { point_code: "023ROOF", counted: true, orientation: "V" },
      { point_code: "035LBPILLAR", counted: false, orientation: "V" },
    ],
    reason: "the box walk changed in September",
  });
});

test("T100 a 403 on save shows its message and correlation id", async ({ page }) => {
  await setup(page, { fail: true });
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.getByTestId("film-point-counted-001HOOD").uncheck();
  await page.getByTestId("film-points-save").click();
  await page.getByTestId("film-points-reason").fill("not walked any more");
  await page.getByTestId("film-points-save-confirm").click();
  await expect(panel(page)).toContainText("This route requires the 'engineer' role.");
  await expect(panel(page)).toContainText("c0rr3lat10n");
});

test("T100 a plant with no setting gets a read-only list that says so", async ({ page }) => {
  await setup(page, { hasSetting: false });
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("film-points-read-only")).toContainText("not switched on");
  // RO17 (D-RO17-11): without the rules there is no Counted control at all.
  await expect(page.getByTestId("film-point-counted-001HOOD")).toHaveCount(0);
  await expect(page.getByTestId("film-points-save")).toHaveCount(0);
});

test("T100 the Points panel fits a 390px screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.screenshot({ path: `${SHOTS}/T100-points-page-390.png`, fullPage: true });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});

// =====================================================================
// T100-FIX (D-100-8): the panel reaches the people who upload
// =====================================================================
test("T100-FIX an Engineer is refused the standards but gets the whole Points panel", async ({
  page,
}) => {
  const { posts } = await setup(page, { role: "engineer" });
  // T109 (D-109-1): the two are separate screens now, so this is read on
  // Point Check and the Admin gate is asserted where it lives -- on Film
  // Thickness, below. Publishing a standard is still Admin-only: the owner's
  // "ignore roles" decision was about Film points.
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await expect(panel(page).getByRole("table")).toContainText("001HOOD");
  await page.getByTestId("film-point-counted-035LBPILLAR").uncheck();
  await page.getByTestId("film-points-save").click();
  await expect(page.getByTestId("film-points-confirm")).toContainText("including past ones");
  await page.getByTestId("film-points-reason").fill("the box walk changed in September");
  await page.getByTestId("film-points-save-confirm").click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toEqual({
    points: [{ point_code: "035LBPILLAR", counted: false, orientation: "V" }],
    reason: "the box walk changed in September",
  });

  await page.getByRole("button", { name: "Film Thickness", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Admin access required" })).toBeVisible();
});

test("T100-FIX a Viewer sees the panel's own 403 with its correlation id and no Save", async ({
  page,
}) => {
  await setup(page, { role: "viewer", modelsStatus: 403 });
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await expect(panel(page)).toContainText("This route requires the 'engineer' role.");
  await expect(panel(page)).toContainText("v13w3r");
  await expect(page.getByTestId("film-points-save")).toHaveCount(0);
  await expect(page.getByTestId("film-points-model")).toHaveCount(0);
});

test("T100-FIX a failed standards read does not hide the Points panel", async ({ page }) => {
  // T109 (D-109-1): it cannot, because Point Check does not read the
  // standards at all -- so this now asserts the stronger thing: the panel is
  // whole, works end to end, and no standards request is made while it is
  // the screen. The 500 is still mocked, and nothing asks for it.
  const asked: string[] = [];
  const { posts } = await setup(page, { standards: "500" });
  page.on("request", (request) => {
    if (request.url().includes("/filmthickness/standards")) asked.push(request.url());
  });
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("Film standards are unavailable.")).toHaveCount(0);
  await expect(panel(page).getByRole("table")).toContainText("058RTFEND");
  await page.getByTestId("film-point-orientation-023ROOF").selectOption("V");
  await page.getByTestId("film-points-save").click();
  await page.getByTestId("film-points-reason").fill("roof is read vertically here");
  await page.getByTestId("film-points-save-confirm").click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toEqual({
    points: [{ point_code: "023ROOF", counted: true, orientation: "V" }],
    reason: "roof is read vertically here",
  });
  expect(asked).toEqual([]);
});

test("T100-FIX2 an Engineer clicks Point Check in the Standard menu and lands on the panel", async ({
  page,
}) => {
  // D-100-9: the entry is drawn for anyone who can upload, so the panel is
  // reachable by clicking and not only by URL.
  // T109 (D-109-1): that entry is **Point Check** now. Film Thickness is
  // still there and still holds the standards; this panel is no longer on
  // it, which is the other half of the same decision.
  await setup(page, { role: "engineer", navigate: "/plant/FTM?standardView=family" });
  const entry = page.getByRole("button", { name: "Point Check", exact: true });
  await expect(entry).toBeVisible({ timeout: 20000 });
  await entry.click();
  await expect(panel(page)).toBeVisible();
  await expect(panel(page).getByRole("table")).toContainText("001HOOD");
  await expect(page.getByTestId("film-points-save")).toBeDisabled();

  // And the Film Thickness entry no longer carries it.
  await page.getByRole("button", { name: "Film Thickness", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Admin access required" })).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
});

test("T100-FIX2 a Viewer has no Film Thickness entry", async ({ page }) => {
  await setup(page, {
    role: "viewer",
    modelsStatus: 403,
    navigate: "/plant/FTM?standardView=family",
  });
  await expect(page.getByRole("button", { name: "Color Family", exact: true })).toBeVisible({
    timeout: 20000,
  });
  await expect(page.getByRole("button", { name: "Film Thickness", exact: true })).toHaveCount(0);
  // T109 (D-109-1): Point Check is shown to the same people, so a Viewer
  // has neither entry.
  await expect(page.getByRole("button", { name: "Point Check", exact: true })).toHaveCount(0);
});

test("T100-FIX2 an Admin still sees the entry", async ({ page }) => {
  await setup(page, { navigate: "/plant/FTM?standardView=family" });
  await expect(page.getByRole("button", { name: "Film Thickness", exact: true })).toBeVisible({
    timeout: 20000,
  });
  await expect(page.getByRole("button", { name: "Point Check", exact: true })).toBeVisible();
});
