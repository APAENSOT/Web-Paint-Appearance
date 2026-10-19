import { expect, test } from "@playwright/test";
import { identity, measurement, workspaceMeta } from "../fixtures";
import type { components } from "../../src/api/types";

const preview: components["schemas"]["DashboardPreview"] = {
  dimension: "checkzone",
  filters: {
    plant: null,
    model: null,
    color: null,
    checkzone: null,
    date_from: null,
    date_to: null,
  },
  point_limit: 5000,
  truncated: false,
  grading_available: false,
  grading_note: "Grouping remains unresolved.",
  active_data_source: "v_wavescan_active",
  series: [{ key: "RRHOOD", points: [{ ...measurement, cf: "62.1234567890123456789" }] }],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/me", (r) =>
    r.fulfill({ json: { ...identity, principal: { ...identity.principal, roles: ["viewer"] } } }),
  );
  await page.route("**/api/v1/meta", (r) => r.fulfill({ json: workspaceMeta }));
  await page.route("**/api/v1/dashboard/preview*", (r) => r.fulfill({ json: preview }));
});

// parked until owner names this function

test.skip("Viewer chart, exact CF table and tooltip, display grouping, empty FVL and cap", async ({
  page,
}) => {
  const urls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/v1/")) urls.push(r.url());
  });
  await page.goto("/analysis");
  await expect(page.getByRole("heading", { name: "Raw CF", exact: true })).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "62.1234567890123456789", exact: true }),
  ).toBeVisible();
  await page.locator(".recharts-scatter-symbol").first().hover();
  await expect(page.getByRole("tooltip")).toContainText("62.1234567890123456789");
  await expect(page.getByRole("link", { name: "Open plant", exact: true })).toHaveAttribute(
    "href",
    "/plant/AAT",
  );
  await page.getByRole("combobox", { name: "Display grouping", exact: true }).selectOption("color");
  const grouped = page.waitForRequest((r) => r.url().includes("preview?dimension=color"));
  await page.getByRole("button", { name: "Apply filters" }).click();
  await grouped;
  await page.route("**/api/v1/dashboard/preview*", (r) =>
    r.fulfill({ json: { ...preview, series: [] } }),
  );
  await page.getByRole("combobox", { name: "Plant", exact: true }).selectOption("FVL");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByText("No measurements match these filters.")).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  await page.route("**/api/v1/dashboard/preview*", (r) =>
    r.fulfill({
      json: {
        ...preview,
        dimension: "color",
        truncated: true,
        series: [{ key: "White", points: preview.series[0].points }],
      },
    }),
  );
  await page.getByRole("combobox", { name: "Plant", exact: true }).selectOption("AAT");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("status")).toContainText("5000");
  await page.screenshot({
    path: "test-results/screenshots/T11-truncated-unavailable.png",
    fullPage: true,
  });
  expect(urls.some((u) => u.includes("standards"))).toBe(false);
  for (const url of urls.filter((u) => u.includes("preview"))) {
    const params = new URL(url).searchParams;
    expect(params.has("point_limit")).toBe(false);
    expect(params.has("color_group")).toBe(false);
    expect(params.has("grading_family")).toBe(false);
  }
});

// parked until owner names this function

test.skip("invalid date range makes no GET; loading hides old points; error retries", async ({
  page,
}) => {
  let calls = 0;
  await page.route("**/api/v1/dashboard/preview*", (r) => {
    calls++;
    return r.fulfill({ json: preview });
  });
  await page.goto("/analysis");
  await expect(page.getByRole("table")).toBeVisible();
  const initialCalls = calls;
  await page.getByLabel("From date").fill("2026-09-14");
  await page.getByLabel("To date").fill("2026-09-13");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("alert")).toContainText("From date");
  expect(calls).toBe(initialCalls);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/dashboard/preview*", async (r) => {
    await gate;
    await r.fulfill({
      status: 503,
      json: {
        statusCode: 503,
        error: "Unavailable",
        message: "Preview offline",
        correlationId: "t11-preview",
      },
    });
  });
  await page.getByLabel("From date").fill("2026-09-12");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByText("Loading raw CF measurements...")).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  release();
  await expect(page.getByRole("alert")).toContainText("Preview offline");
  await expect(page.getByRole("alert")).toContainText("t11-preview");
  await page.route("**/api/v1/dashboard/preview*", (r) =>
    r.fulfill({ json: { ...preview, series: [{ key: "RRHOOD", points: [] }] } }),
  );
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByText("No measurements match these filters.")).toBeVisible();
});

// parked until owner names this function

test.skip("canonical metadata filters, same-date observations and mobile table paging", async ({
  page,
}) => {
  await page.route("**/api/v1/meta", (r) =>
    r.fulfill({
      json: {
        ...workspaceMeta,
        models: [
          {
            model_code: "P703",
            model_family: "Ranger",
            body_style: "truck",
            expected_zone_count: 1,
            is_active: true,
          },
        ],
        colors: [
          {
            color_name: "White",
            color_group: "DO NOT FILTER",
            grading_family: null,
            grading_family_status: "unmapped",
            is_active: true,
          },
        ],
        checkzones: [
          {
            zone_code: "RRHOOD",
            zone_name: "Hood",
            panel_group: "Hood",
            tolerance_group: "Horizontal",
          },
        ],
      } satisfies components["schemas"]["MetaResponse"],
    }),
  );
  const points = Array.from({ length: 51 }, (_, i) => ({
    ...measurement,
    measurement_id: 100 + i,
    cf: i === 50 ? "61.99999999999999" : "62.1234567890123456789",
  }));
  await page.route("**/api/v1/dashboard/preview*", (r) =>
    r.fulfill({ json: { ...preview, series: [{ key: "RRHOOD", points }] } }),
  );
  await page.goto("/analysis");
  for (const [label, value] of [
    ["Plant", "AAT"],
    ["Model", "P703"],
    ["Colour", "White"],
    ["Zone", "RRHOOD"],
  ])
    await page.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  const pending = page.waitForRequest(
    (r) => r.url().includes("preview") && new URL(r.url()).searchParams.has("model"),
  );
  await page.getByRole("button", { name: "Apply filters" }).click();
  expect(Object.fromEntries(new URL((await pending).url()).searchParams)).toEqual({
    dimension: "checkzone",
    plant: "AAT",
    model: "P703",
    color: "White",
    checkzone: "RRHOOD",
  });
  await expect(page.locator(".recharts-scatter-symbol")).toHaveCount(51);
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(51);
  await page.getByRole("button", { name: "Next rows" }).click();
  await expect(page.getByRole("cell", { name: "61.99999999999999", exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/screenshots/T11-analysis-mobile-mock.png",
    fullPage: true,
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await page.screenshot({
    path: "test-results/screenshots/T11-analysis-mobile-light-mock.png",
    fullPage: true,
  });
  await page.getByRole("combobox", { name: "Plant", exact: true }).selectOption("FVL");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("button", { name: "Previous rows" })).toBeDisabled();
});

// parked until owner names this function

test.skip("metadata recovery preserves typed codes and Retry never applies draft filters", async ({
  page,
}) => {
  await page.route("**/api/v1/meta", (r) =>
    r.fulfill({
      status: 503,
      json: {
        statusCode: 503,
        error: "Unavailable",
        message: "Metadata offline",
        correlationId: "t11-meta",
      },
    }),
  );
  let calls = 0;
  await page.route("**/api/v1/dashboard/preview*", (r) => {
    calls++;
    return r.fulfill({ json: preview });
  });
  await page.goto("/analysis");
  const main = page.getByRole("main");
  await expect(main.getByRole("alert")).toContainText("Metadata offline");
  await expect(page.getByRole("table")).toBeVisible();
  await main.getByRole("textbox", { name: /^Plant/ }).fill("SAP");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await main.getByRole("textbox", { name: /^Model/ }).fill("P999");
  const beforeRetry = calls;
  await page.route("**/api/v1/meta", (r) => r.fulfill({ json: workspaceMeta }));
  await main.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Plant", exact: true })).toHaveValue("SAP");
  await expect(main.getByRole("textbox", { name: /^Model/ })).toHaveValue("P999");
  expect(calls).toBe(beforeRetry);
  const applied = page.waitForRequest(
    (r) => r.url().includes("preview") && new URL(r.url()).searchParams.get("model") === "P999",
  );
  await page.getByRole("button", { name: "Apply filters" }).click();
  expect(new URL((await applied).url()).searchParams.get("plant")).toBe("SAP");
});
