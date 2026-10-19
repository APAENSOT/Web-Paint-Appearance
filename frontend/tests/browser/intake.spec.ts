import { expect, test } from "@playwright/test";
import { identity, workspaceMeta } from "../fixtures";

const meta = {
  ...workspaceMeta,
  plants: [
    ...workspaceMeta.plants.filter((plant) => plant.plant_code !== "FVL"),
    {
      plant_code: "FVL",
      plant_name: "Ford Vietnam",
      country: "Vietnam",
      is_active: false,
    },
  ],
};

test("Admin batches is a plant chooser including inactive plants, with no upload or batch list", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: { ...identity, principal: { ...identity.principal, roles: ["admin"] } },
    }),
  );
  await page.route("**/api/v1/meta", (route) => route.fulfill({ json: meta }));
  const operationalRequests: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/v1\/(batches|uploads|mappings)/.test(request.url()))
      operationalRequests.push(request.url());
  });

  await page.goto("/batches");
  await expect(page.getByRole("heading", { name: "Choose a plant" })).toBeVisible();
  await expect(page.getByRole("link", { name: /AAT/ })).toBeVisible();
  const inactive = page.getByRole("link", { name: /FVL/ });
  await expect(inactive).toContainText("Not onboarded - plant remains visible");
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(0);
  expect(operationalRequests).toEqual([]);

  await inactive.click();
  await expect(page).toHaveURL(/\/plant\/fvl\?dataView=upload/);
});

test("Engineer batches is parked copy with no picker or operational requests", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: identity }));
  const operationalRequests: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/v1\/(batches|uploads|mappings)/.test(request.url()))
      operationalRequests.push(request.url());
  });

  await page.goto("/batches");
  await expect(page.getByRole("heading", { name: "Plant uploads are Admin-only" })).toBeVisible();
  await expect(page.getByText(/plant's Measurement History/)).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(0);
  expect(operationalRequests).toEqual([]);
});

test("Viewer direct batches is denied and sends no operational request", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: { ...identity, principal: { ...identity.principal, roles: ["viewer"] } },
    }),
  );
  const operationalRequests: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/v1\/(batches|uploads|mappings)/.test(request.url()))
      operationalRequests.push(request.url());
  });

  await page.goto("/batches");
  await expect(page.getByRole("heading", { name: "Engineer access required" })).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(0);
  expect(operationalRequests).toEqual([]);
});
