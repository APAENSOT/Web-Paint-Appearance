/**
 * T114 Point Check, Wave Scan, in a real browser.
 *
 * Mocked with `page.route` -- the live lists and the real writes are the
 * backend's own tests (`test_t114_point_check_wavescan.py`). What this file
 * pins:
 *
 * * D-114-1 -- the Wave Scan section replaces the "not part of this screen
 *   yet" sentence: the walk in order with zone code, H / V (shown, not
 *   editable), Counted, the extra tag and the last change; retired points
 *   below with when and why;
 * * D-114-2 -- Counted saves only with a reason, after the warning;
 * * D-114-4 -- Retire asks for a reason, warns in Film's shape and says
 *   a retired point can be restored (RO17);
 * * D-114-6 -- Add takes a picked or typed zone code, shows H / V read-only
 *   (from the code, or from the new name), and shows the server's refusal;
 * * D-114-3..5 -- History's point tags: retired point, not counted, extra;
 * * a Viewer has no Point Check entry; 390 width.
 *
 * Screenshots: desktop and 390, written to test-results/screenshots.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { catalogueFixture } from "../fixtures";
import { historyPoint, historyPoints, mockHistory, openHistoryPoint } from "../history-fixtures";

type Point = components["schemas"]["WsPointItem"];
type Retired = components["schemas"]["WsRetiredPointItem"];

const SHOTS = "test-results/point-check-polish";
const PLANT = "FTM";
const MODEL = "P703 DBL RAPTOR";

function point(no: number, code: string, overrides: Partial<Point> = {}): Point {
  return {
    point_no: no,
    zone_code: code,
    label: code,
    tolerance_group: /HOOD|ROOF|FLOOR/i.test(code) ? "Horizontal" : "Vertical",
    counted: true,
    is_extra: false,
    note: "T58 owner lock 2026-10-05",
    created_at: "2026-10-05T19:46:02+07:00",
    reason: null,
    changed_by: null,
    changed_at: null,
    ...overrides,
  };
}

const POINTS: Point[] = [
  point(1, "RRHOOD"),
  point(2, "RFHOOD"),
  point(6, "LFFENDER", {
    counted: false,
    reason: "Sensor bracket in the way since August",
    // T115 (D-115-1): the server sends the person's display name, not the uuid.
    changed_by: "Development bypass",
    changed_at: "2026-10-12T09:15:00+07:00",
  }),
  point(11, "LCROOF"),
  point(32, "RFFENDER"),
  point(33, "T114 Mark Door", {
    is_extra: true,
    note: "T114 Point Check add by Owner",
    reason: "Plant measures the new door seam",
    changed_at: "2026-10-12T09:20:00+07:00",
  }),
];

const RETIRED: Retired[] = [
  {
    point_no: 33,
    zone_code: "01HOOD",
    label: "01HOOD",
    tolerance_group: "Horizontal",
    is_extra: false,
    retired_at: "2026-10-11T10:00:00+07:00",
    retired_reason: "T113: FTM's unused duplicate 32-panel block (D-113-1)",
  },
];

const CHOICES = [
  { zone_code: "01RHS Hood Rr28", tolerance_group: "Horizontal" },
  { zone_code: "RTTAILGATE", tolerance_group: "Vertical" },
];

const REFUSAL =
  "'rr hood' is the same panel as 'RRHOOD', spelled differently -- pick RRHOOD instead. " +
  "Nothing was changed.";

async function setup(
  page: Page,
  { role = "engineer", addStatus = 200, navigate = `/plant/${PLANT}?standardView=points` } = {},
) {
  await mockHistory(page, role);
  await page.route("**/api/v1/standards/catalogue", (r) => r.fulfill({ json: catalogueFixture }));
  // RO17: the aliases section under each list; empty keeps these tests to their own half.
  await page.route("**/api/v1/plants/*/point-aliases/**", (r) =>
    r.fulfill({ json: { plant_code: "X", domain: "film", model_code: "X", items: [] } }),
  );
  const posts: { url: string; body: unknown }[] = [];
  // Film is T109's; an empty Film list keeps this page to the Wave Scan half.
  await page.route(`**/api/v1/plants/${PLANT}/film-points`, (route) =>
    route.fulfill({ json: { plant_code: PLANT, items: [] } }),
  );
  await page.route(`**/api/v1/plants/${PLANT}/ws-points`, (route) =>
    route.fulfill({
      json: {
        plant_code: PLANT,
        items: [
          {
            model_code: MODEL,
            display_name: null,
            point_count: POINTS.length,
            counted_count: POINTS.length - 1,
            extra_count: 1,
          },
        ],
      },
    }),
  );
  await page.route(`**/api/v1/plants/${PLANT}/ws-points/*/add`, (route) => {
    posts.push({ url: route.request().url(), body: route.request().postDataJSON() });
    if (addStatus !== 200)
      return route.fulfill({
        status: addStatus,
        json: { statusCode: addStatus, error: "Conflict", message: REFUSAL, correlationId: "tw1n" },
      });
    return route.fulfill({
      json: {
        zone_code: "33 Rr Roof",
        point_no: 34,
        tolerance_group: "Horizontal",
        operator_message: "33 Rr Roof is now point 34 of FTM's P703 DBL RAPTOR Wave Scan walk.",
      },
    });
  });
  await page.route(`**/api/v1/plants/${PLANT}/ws-points/*/retire`, (route) => {
    posts.push({ url: route.request().url(), body: route.request().postDataJSON() });
    return route.fulfill({
      json: {
        zone_code: "LCROOF",
        point_no: 11,
        tolerance_group: "Horizontal",
        operator_message: "LCROOF is off FTM's P703 DBL RAPTOR Wave Scan walk.",
      },
    });
  });
  await page.route(`**/api/v1/plants/${PLANT}/ws-points/*`, (route) => {
    if (route.request().method() === "POST") {
      posts.push({ url: route.request().url(), body: route.request().postDataJSON() });
      return route.fulfill({ json: { rows_written: 1, operator_message: "1 point changed." } });
    }
    return route.fulfill({
      json: {
        plant_code: PLANT,
        model_code: MODEL,
        items: POINTS,
        retired_items: RETIRED,
        zone_choices: CHOICES,
        horizontal_words: ["HOOD", "ROOF", "FLOOR"],
      },
    });
  });
  await page.goto(navigate);
  if (role !== "viewer") await page.getByRole("tab", { name: "Wave Scan", exact: true }).click();
  return { posts };
}

const panel = (page: Page) => page.getByTestId("ws-points-panel");

test("Point Check filters keep drafts across measurement tabs", async ({ page }) => {
  await setup(page);
  await page.getByRole("textbox", { name: "Find a Wave Scan point" }).fill("RRHOOD");
  await expect(panel(page).locator("tr[data-ws-point]")).toHaveCount(1);
  await page.getByTestId("ws-point-counted-RRHOOD").uncheck();
  await expect(page.getByTestId("ws-points-model")).toBeDisabled();
  await page.getByRole("tab", { name: "Film Thickness", exact: true }).click();
  await page.getByRole("tab", { name: "Wave Scan", exact: true }).click();
  await expect(page.getByTestId("ws-point-counted-RRHOOD")).not.toBeChecked();
  await page.getByRole("button", { name: "Discard point changes", exact: true }).click();
  await expect(page.getByTestId("ws-point-counted-RRHOOD")).toBeChecked();
  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(panel(page).locator("tr[data-ws-point]")).toHaveCount(POINTS.length);
  await page.getByRole("combobox", { name: "Wave Scan dashboard use" }).selectOption("no");
  await expect(panel(page).locator("tr[data-ws-point]")).toHaveCount(1);
});

// T115 (D-115-1): "Last change" names the person; a row nobody named shows "-".
test("T115 Wave Scan Last change shows the person's name, and - for none", async ({ page }) => {
  await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  const row = (code: string) => panel(page).locator(`tr[data-ws-point="${code}"]`);
  await expect(row("LFFENDER")).toContainText("Development bypass · 2026-10-12");
  await expect(row("T114 Mark Door")).toContainText("- · 2026-10-12");
  await expect(panel(page)).not.toContainText("4f1c2a90");
  await row("LFFENDER").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/T115-last-change-wavescan-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(row("LFFENDER")).toContainText("Development bypass");
  await page.screenshot({ path: `${SHOTS}/T115-last-change-wavescan-390.png`, fullPage: true });
});

test("T114 the Wave Scan section lists the walk with H/V, Counted, extra and retired", async ({
  page,
}) => {
  await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("point-check-wave-later")).toHaveCount(0);
  const table = panel(page).getByRole("table");
  await expect(table).toContainText("RRHOOD");
  await expect(page.getByTestId("ws-point-hv-RRHOOD")).toHaveText("H");
  await expect(page.getByTestId("ws-point-hv-LFFENDER")).toHaveText("V");
  // H / V is shown, never edited: no control in that column.
  await expect(panel(page).getByRole("combobox", { name: /Horizontal or Vertical/ })).toHaveCount(
    0,
  );
  await expect(page.getByTestId("ws-point-counted-RRHOOD")).toBeChecked();
  await expect(page.getByTestId("ws-point-counted-LFFENDER")).not.toBeChecked();
  await expect(table).toContainText("Sensor bracket in the way since August");
  await expect(page.getByTestId("ws-point-extra-T114 Mark Door")).toContainText("Extra");
  await expect(page.getByTestId("ws-point-extra-RRHOOD")).toHaveCount(0);
  const rows = panel(page).locator("tbody tr");
  await expect(rows.first()).toHaveAttribute("data-ws-point", "RRHOOD");
  await expect(rows.last()).toHaveAttribute("data-ws-point", "T114 Mark Door");

  const gone = page.getByTestId("ws-points-retired");
  await expect(gone).toContainText("01HOOD");
  await expect(gone).toContainText("unused duplicate 32-panel block");
  await expect(gone).toContainText("2026-10-11");

  await page.screenshot({ path: `${SHOTS}/T114-point-check-wavescan-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(table).toContainText("RRHOOD");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${SHOTS}/T114-point-check-wavescan-390.png`, fullPage: true });
});

test("T114 Counted saves only after the warning and with a reason", async ({ page }) => {
  const { posts } = await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("ws-points-save")).toBeDisabled();
  await page.getByTestId("ws-point-counted-RFHOOD").uncheck();
  await expect(page.getByTestId("ws-points-changed")).toHaveText("1 point changed.");
  await page.getByTestId("ws-points-save").click();
  const confirm = page.getByTestId("ws-points-confirm");
  await expect(confirm).toContainText("for every month, including past ones");
  await expect(confirm).toContainText("History and Comparison keep every reading");
  await expect(page.getByTestId("ws-points-save-confirm")).toBeDisabled();
  await page.getByTestId("ws-points-reason").fill("no");
  await expect(page.getByTestId("ws-points-save-confirm")).toBeDisabled();
  await page.getByTestId("ws-points-reason").fill("Bracket covers it");
  await page.getByTestId("ws-points-save-confirm").click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0].url).toContain(`/ws-points/${encodeURIComponent(MODEL)}`);
  expect(posts[0].body).toEqual({
    points: [{ zone_code: "RFHOOD", counted: false }],
    reason: "Bracket covers it",
  });
});

test("T114 Retire warns, needs a reason and says it can be restored", async ({ page }) => {
  const { posts } = await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.getByTestId("ws-point-retire-LCROOF").click();
  const confirm = page.getByTestId("ws-point-retire-confirm-LCROOF");
  await expect(confirm).toContainText("stops counting on the dashboard for every month");
  await expect(confirm).toContainText("The readings stay in History, marked retired.");
  await expect(confirm).toContainText("It can be restored from Retired points below.");
  await expect(page.getByTestId("ws-point-retire-submit-LCROOF")).toBeDisabled();
  await page.getByTestId("ws-point-retire-reason-LCROOF").fill("Roof panel no longer measured");
  await page.screenshot({ path: `${SHOTS}/T114-point-check-retire-desktop.png`, fullPage: true });
  await page.getByTestId("ws-point-retire-submit-LCROOF").click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0].url).toContain("/retire");
  expect(posts[0].body).toEqual({ zone_code: "LCROOF", reason: "Roof panel no longer measured" });
});

test("T114 Add picks or types a code, shows H/V read-only and sends it", async ({ page }) => {
  const { posts } = await setup(page);
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.getByTestId("ws-point-add-open").click();
  const box = page.getByTestId("ws-point-add-code");
  await expect(box).toHaveAttribute("list", /ws-zone-choices/);
  await box.fill("RTTAILGATE");
  await expect(page.getByTestId("ws-point-add-hv")).toHaveText("Vertical");
  await expect(page.getByTestId("ws-point-add-kind")).toContainText("Existing zone code");
  await box.fill("33 Rr Roof");
  await expect(page.getByTestId("ws-point-add-hv")).toHaveText("Horizontal");
  await expect(page.getByTestId("ws-point-add-kind")).toContainText("New zone code");
  // No H / V control anywhere in the form: it comes from the name.
  await expect(page.getByTestId("ws-point-add").locator("select")).toHaveCount(0);
  await expect(page.getByTestId("ws-point-add-submit")).toBeDisabled();
  await page.getByTestId("ws-point-add-reason").fill("New roof seam point");
  await page.screenshot({ path: `${SHOTS}/T114-point-check-add-desktop.png`, fullPage: true });
  await page.getByTestId("ws-point-add-submit").click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0].url).toContain("/add");
  expect(posts[0].body).toEqual({
    zone_code: "33 Rr Roof",
    counted: true,
    counted_in_completeness: false,
    reason: "New roof seam point",
  });
});

test("T114 Add shows the server's refusal and keeps the form", async ({ page }) => {
  await setup(page, { addStatus: 409 });
  await expect(panel(page)).toBeVisible({ timeout: 20000 });
  await page.getByTestId("ws-point-add-open").click();
  await page.getByTestId("ws-point-add-code").fill("rr hood");
  await page.getByTestId("ws-point-add-reason").fill("Typed by hand");
  await page.getByTestId("ws-point-add-submit").click();
  await expect(page.getByTestId("ws-point-add")).toContainText("same panel as 'RRHOOD'");
  await expect(page.getByTestId("ws-point-add-code")).toHaveValue("rr hood");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("ws-point-add")).toContainText("pick RRHOOD instead");
  await page.screenshot({ path: `${SHOTS}/T114-point-check-add-refused-390.png`, fullPage: true });
});

test("T114 a Viewer has no Point Check entry", async ({ page }) => {
  await setup(page, { role: "viewer", navigate: `/plant/${PLANT}?standardView=family` });
  await expect(page.getByRole("button", { name: "Color Family", exact: true })).toBeVisible({
    timeout: 20000,
  });
  await expect(page.getByTestId("model-detail-nav-point-check")).toHaveCount(0);
});

test("T114 History tags a reading's point: retired, not counted, extra", async ({ page }) => {
  await mockHistory(page);
  const rows = [
    { ...historyPoint, measurement_id: 41 },
    {
      ...historyPoint,
      measurement_id: 42,
      checkzone: "01HOOD",
      panel_label: "01HOOD",
      retired: true,
    },
    {
      ...historyPoint,
      measurement_id: 43,
      checkzone: "LFFENDER",
      panel_label: "LFFENDER",
      counted: false,
    },
    {
      ...historyPoint,
      measurement_id: 44,
      checkzone: "T114 Mark Door",
      panel_label: "T114 Mark Door",
      is_extra: true,
    },
  ];
  await page.route("**/api/v1/plants/*/history/vehicles/*/points**", (route) =>
    route.fulfill({
      json: {
        ...historyPoints(),
        items: rows,
        page: { offset: 0, limit: 50, total: rows.length, returned: rows.length },
      },
    }),
  );
  await openHistoryPoint(page);
  await expect(page.locator("[data-measurement-id='44']")).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("history-point-tags-41")).toHaveCount(0);
  await expect(page.getByTestId("history-point-tags-42")).toHaveText("Retired point");
  await expect(page.getByTestId("history-point-tags-43")).toHaveText("Not counted");
  await expect(page.getByTestId("history-point-tags-44")).toHaveText("Extra");
  await page.locator("[data-measurement-id='42']").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/T114-history-point-tags-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("history-point-tags-42")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/T114-history-point-tags-390.png`, fullPage: true });
});
