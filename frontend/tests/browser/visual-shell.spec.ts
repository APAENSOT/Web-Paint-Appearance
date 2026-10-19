import { expect, test } from "@playwright/test";
import { identity, workspaceMeta, catalogueFixture } from "../fixtures";
import { mockHistory } from "../history-fixtures";

test("Lovable overview shows map, KPI tiles and plant feeds", async ({ page }) => {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("ct-theme", "dark"));
  await page.route(/\/api\/v1\/|\/health\//, async (route) => {
    requests.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    return route.fulfill({ status: 500, json: { message: "Unexpected API call" } });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Paint Appearance", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "IMG Plant Location" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Overview Status" })).toBeVisible();
  for (const code of ["FTM", "AAT", "FVL", "SAP"]) {
    await expect(page.getByText(code, { exact: true }).first()).toBeVisible();
  }
  await expect(page.locator("body")).toContainText("96.4");
  await expect(page.locator("body")).toHaveCSS("font-family", /Barlow/);
  await page.screenshot({
    path: "test-results/T14-shell-overview-lovable.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
});

for (const code of ["ftm", "aat", "fvl", "sap"]) {
  test(`${code} Overview is the default lens and Data stays isolated`, async ({ page }) => {
    const requests: URL[] = [];
    await mockPlant(page);
    page.on("request", (r) => {
      if (r.url().includes("/history/")) requests.push(new URL(r.url()));
    });
    await page.goto(`/plant/${code}`);
    await expect(
      page.getByRole("button", { name: "Monthly Overview", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Data", exact: true })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await expect(page.locator("header")).toContainText(`Official ${code.toUpperCase()}`);
    for (const title of ["First Run OK", "Line Status", "Data Backup"]) {
      const bay = page.locator(`header [aria-label="${title}"]`);
      await expect(bay).toContainText("no API field");
      await expect(bay).not.toContainText(/[0-9%]|NOMINAL|CAUTION|CRITICAL/);
    }
    if (code === "fvl" || code === "sap")
      await expect(page.getByText("There are no active readings for this month.")).toBeVisible();
    else {
      await expect(
        page.getByRole("heading", { name: "P703 DBL RAPTOR", exact: true }),
      ).toBeVisible();
      // T112: owner 2026-10-11 — WARNING reads Acceptable
      await expect(page.getByText("Acceptable", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("61.2", { exact: true }).first()).toBeVisible();
    }
    expect(requests).toEqual([]);
    await page.screenshot({
      path: `test-results/T15-${code}-data-mock.png`,
      fullPage: true,
      animations: "disabled",
    });
    await page.getByRole("button", { name: "Data", exact: true }).click();
    await expect(page.getByRole("region", { name: "Measurement History" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Data", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    if (code === "fvl" || code === "sap")
      await expect(
        page.getByText("No approved measurements for this plant", { exact: true }),
      ).toBeVisible();
    else await expect(page.getByRole("heading", { name: "Week 2", exact: true })).toBeVisible();
    expect(requests.length).toBeGreaterThan(0);
    expect(
      requests.every((url) => url.pathname.includes(`/plants/${code.toUpperCase()}/history/`)),
    ).toBe(true);
  });
}

async function mockPlant(page: import("@playwright/test").Page) {
  await mockHistory(page);
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ json: identity }));
  await page.route("**/api/v1/meta", (r) =>
    r.fulfill({
      json: {
        ...workspaceMeta,
        plants: ["FTM", "AAT", "FVL", "SAP"].map((plant_code) => ({
          plant_code,
          plant_name: `Official ${plant_code}`,
          country: "Test",
          is_active: true,
        })),
      },
    }),
  );
}

for (const role of ["viewer", "engineer", "admin"] as const) {
  test(`${role} parked analysis, intake and admin stay unreachable from Lovable chrome`, async ({
    page,
  }) => {
    await page.route(/\/api\/v1\/|\/health\//, async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/v1/auth/me")
        return route.fulfill({
          json: { ...identity, principal: { ...identity.principal, roles: [role] } },
        });
      if (path === "/api/v1/meta") return route.fulfill({ json: workspaceMeta });
      if (path === "/api/v1/standards/catalogue") return route.fulfill({ json: catalogueFixture });
      return route.fulfill({ status: 500, json: { message: "Forbidden parked request" } });
    });
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Ingest" })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Administration", exact: true })).toHaveCount(
      0,
    );
    await page.goto("/analysis");
    await expect(page.getByRole("heading", { name: "Analysis", exact: true })).toBeVisible();
    await expect(page.locator("main")).toContainText("Not wired this phase");
    await page.goto("/batches");
    await expect(
      page.getByRole("heading", {
        name:
          role === "viewer"
            ? "Engineer access required"
            : role === "admin"
              ? "Choose a plant"
              : "Plant uploads are Admin-only",
        exact: true,
      }),
    ).toBeVisible();
    await page.goto("/admin");
    await expect(
      page.getByRole("heading", {
        name: role === "admin" ? "Administration" : "Admin access required",
        exact: true,
      }),
    ).toBeVisible();
  });
}

test("mobile overview and FTM plant fit both themes", async ({ page }) => {
  await mockPlant(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const theme of ["dark", "light"]) {
    await page.goto("/");
    if (theme === "light")
      await page.getByRole("button", { name: "Switch to light theme" }).click();
    await expect(page.getByRole("heading", { name: "IMG Plant Location" })).toBeVisible();
    await page.screenshot({
      path: `test-results/T14-shell-mobile-overview-${theme}.png`,
      fullPage: true,
      animations: "disabled",
    });
    await page.goto("/plant/ftm");
    await expect(
      page.getByRole("button", { name: "Monthly Overview", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await page.screenshot({
      path: `test-results/T15-mobile-plant-${theme}.png`,
      fullPage: true,
      animations: "disabled",
    });
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^$/);
  }
});
