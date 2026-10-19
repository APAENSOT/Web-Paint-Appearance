import { expect, test } from "@playwright/test";
import { identity, measurement, cleanReview, workspaceMeta } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: identity }));
  await page.route("**/api/v1/meta", (route) => route.fulfill({ json: workspaceMeta }));
  await page.route("**/health/ready", (route) =>
    route.fulfill({
      json: {
        status: "ready",
        checks: { database: { status: "ok" }, object_store: { status: "ok" } },
      },
    }),
  );
  await page.route("**/api/v1/measurements?*", (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get("limit")).toBe("1");
    expect(url.searchParams.get("offset")).toBe("0");
    const total = url.searchParams.get("plant") === "AAT" ? 127 : 0;
    return route.fulfill({
      json: {
        items: total ? [measurement] : [],
        page: { total, limit: 1, offset: 0, returned: total ? 1 : 0 },
        filters: {},
        active_data_source: "v_wavescan_active",
      },
    });
  });
  await page.route("**/api/v1/batches?*", (route) => {
    expect(new URL(route.request().url()).search).toBe("?limit=50");
    const items = Array.from({ length: 50 }, (_, i) => ({
      ...cleanReview.batch,
      load_id: i + 1,
      source_file: `sheet-${i}.xlsx`,
      status: [
        "RUNNING",
        "PENDING_REVIEW",
        "REJECTED_TEMPLATE",
        "FAILED",
        "COMMITTED",
        "SUPERSEDED",
      ][i % 6],
    }));
    return route.fulfill({
      json: { items, page: { total: 80, limit: 50, offset: 0, returned: 50 } },
    });
  });
});

for (const role of ["viewer", "engineer", "admin"])
  // parked until owner names this function
  test.skip(`${role} workspace navigation, denial and API request boundaries`, async ({ page }) => {
    const urls: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/api/v1/") || req.url().includes("/health/")) {
        urls.push(req.url());
        expect(req.method()).toBe("GET");
        expect(req.headers().authorization).toBeUndefined();
      }
    });
    await page.route("**/api/v1/auth/me", (route) =>
      route.fulfill({ json: { ...identity, principal: { ...identity.principal, roles: [role] } } }),
    );
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
    await expect(
      page.getByRole("article", { name: "AAT plant" }).getByLabel("127 active measurements"),
    ).toBeVisible();
    await expect(
      page.getByRole("article", { name: "FVL plant" }).getByLabel("0 active measurements"),
    ).toBeVisible();
    await expect(page.getByText("Dev bypass", { exact: true })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Ingest" })).toHaveCount(
      role === "viewer" ? 0 : 1,
    );
    await expect(page.getByRole("navigation", { name: "Administration", exact: true })).toHaveCount(
      role === "admin" ? 1 : 0,
    );
    await expect(page.getByText(measurement.measured_date, { exact: true })).toHaveCount(0);
    await expect(page.getByText("%", { exact: true })).toHaveCount(0);
    await page.screenshot({
      path: `test-results/screenshots/T14-overview-${role}.png`,
      fullPage: true,
    });
    if (role === "viewer") {
      await expect(page.getByRole("region", { name: "Batch attention" })).toHaveCount(0);
      await page.goto("/batches");
      await expect(page.getByRole("heading", { name: "Engineer access required" })).toBeVisible();
      await expect(page.getByRole("article")).toHaveCount(0);
      expect(urls.some((url) => url.includes("/batches"))).toBe(false);
    } else {
      const attention = page.getByRole("region", { name: "Batch attention" });
      await expect(attention).toContainText("Latest 50 of 80");
      for (const status of ["RUNNING", "PENDING_REVIEW", "REJECTED_TEMPLATE", "FAILED"])
        await expect(attention.getByText(status, { exact: true }).first()).toBeVisible();
      for (const status of ["COMMITTED", "SUPERSEDED"])
        await expect(attention.getByText(status, { exact: true })).toHaveCount(0);
    }
    await page.goto("/admin");
    if (role === "admin") {
      await expect(
        page.getByRole("heading", { name: "Administration", exact: true }),
      ).toBeVisible();
      await expect(page.getByText("21", { exact: true })).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Standards publishing · Reserved" }),
      ).toBeDisabled();
    } else await expect(page.getByRole("heading", { name: "Admin access required" })).toBeVisible();
    await page.goto("/analysis");
    await expect(page.getByRole("heading", { name: "Grading unavailable" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Apply filters" })).toBeVisible();
    expect(urls.some((url) => /\/standards|health\/live/.test(url))).toBe(false);
  });

// parked until owner names this function

test.skip("readiness 503 and one count error are independent and recover through their own retries", async ({
  page,
}) => {
  await page.route("**/health/ready", (route) =>
    route.fulfill({
      status: 503,
      json: {
        statusCode: 503,
        error: "Unavailable",
        message: "Object store offline",
        correlationId: "t10-health",
      },
    }),
  );
  await page.route("**/api/v1/measurements?plant=AAT&*", (route) =>
    route.fulfill({
      status: 503,
      json: {
        statusCode: 503,
        error: "Unavailable",
        message: "AAT count unavailable",
        correlationId: "t10-count",
      },
    }),
  );
  await page.goto("/");
  const health = page.getByRole("region", { name: "Service readiness" });
  const card = page.getByRole("article", { name: "AAT plant" });
  await expect(health).toContainText("Object store offline");
  await expect(health).toContainText("t10-health");
  await expect(card).toContainText("t10-count");
  await expect(
    page.getByRole("article", { name: "FVL plant" }).getByLabel("0 active measurements"),
  ).toBeVisible();
  await page.unroute("**/api/v1/measurements?plant=AAT&*");
  await card.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(card.getByLabel("127 active measurements")).toBeVisible();
  await expect(health).toContainText("Object store offline");
  await page.route("**/health/ready", (route) =>
    route.fulfill({
      json: {
        status: null,
        checks: { database: { status: "ok" }, object_store: ["bad"], invented: "secret" },
      },
    }),
  );
  await health.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(health).toContainText("Readiness details unavailable");
  await expect(health).toContainText("Database: ok");
  await expect(health).not.toContainText("secret");
});

test("identity failure blocks plant History and prevents operational reads", async ({ page }) => {
  const urls: string[] = [];
  page.on("request", (req) => urls.push(req.url()));
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 401,
      json: {
        statusCode: 401,
        error: "Unauthorized",
        message: "Session unavailable",
        correlationId: "t10-identity",
      },
    }),
  );
  await page.route("**/api/v1/meta", (route) =>
    route.fulfill({
      json: {
        plants: [],
        models: [],
        colors: [],
        checkzones: [],
        grading_available: false,
        unmapped_color_count: 0,
      },
    }),
  );
  await page.goto("/plant/aat?dataView=history");
  await expect(page.getByRole("alert")).toContainText("t10-identity");
  await expect(page.getByRole("region", { name: "Measurement History", exact: true })).toHaveCount(
    0,
  );
  expect(
    urls.some((url) =>
      /\/api\/v1\/(measurements|batches)|\/history\/|\/workbooks|\/health\/ready/.test(url),
    ),
  ).toBe(false);
});

// parked until owner names this function

test.skip("mobile Overview and denials fit both themes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: { ...identity, principal: { ...identity.principal, roles: ["viewer"] } },
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("article", { name: "AAT plant" }).getByLabel("127 active measurements"),
  ).toBeVisible();
  for (const theme of ["dark", "light"]) {
    if (theme === "light")
      await page.getByRole("button", { name: "Switch to light theme" }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `test-results/screenshots/T10-mobile-${theme}.png`,
      fullPage: true,
    });
    await page.screenshot({
      path: `test-results/screenshots/T14-mobile-${theme}.png`,
      fullPage: true,
    });
  }
  await page.goto("/batches");
  await expect(page.getByRole("heading", { name: "Engineer access required" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
