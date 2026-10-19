import { expect, test } from "@playwright/test";
import { landingFixture, mockLanding } from "../landing-fixture";

test("loading and errors never claim empty uploads; retry recovers without losing selection", async ({
  page,
}) => {
  let finish: () => void = () => {};
  const wait = new Promise<void>((resolve) => {
    finish = resolve;
  });
  let recovered = false;
  await page.route("**/api/v1/landing/status**", async (route) => {
    if (!recovered) {
      await wait;
      await route.fulfill({ status: 503, json: { detail: "Unavailable" } });
    } else {
      await route.fulfill({ json: landingFixture() });
    }
  });
  await page.goto("/");
  await expect(page.locator(".landing-data-state")).toContainText("Loading plant status");
  await page.getByRole("button", { name: "Explore FTM score and plant" }).click();
  const summary = page.locator(".plant-preview__summary");
  await expect(summary.locator('dt:text-is("Last upload") + dd')).toHaveText("Checking…");
  await expect(summary).not.toContainText("No uploads yet");
  finish();
  await expect(page.getByRole("button", { name: "Retry plant status" })).toBeVisible();
  await expect(summary.locator('dt:text-is("Last upload") + dd')).toHaveText("Unavailable");
  await expect(summary).not.toContainText("No standard models");
  recovered = true;
  await page.getByRole("button", { name: "Retry plant status" }).click();
  await expect(page.locator(".landing-data-state")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "FTM · Plant preview" })).toBeVisible();
  await expect(summary.locator('dt:text-is("Last upload") + dd')).toHaveText(/\d+[mhd] ago/);
});

test("collapsed feeds stay hidden to accessibility; empty uploads are shown after a successful read", async ({
  page,
}) => {
  await mockLanding(page);
  await page.goto("/");
  await expect(page.getByRole("listitem").filter({ hasText: "No files uploaded yet" })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: /FVL Data Feed/ }).click();
  await expect(page.locator('[aria-hidden="false"]')).toContainText("No files uploaded yet");
  await page.getByRole("button", { name: "Explore FVL score and plant" }).click();
  await expect(page.locator('dt:text-is("Last upload") + dd')).toHaveText("No uploads yet");
});

test("ordinary wheel scrolls the page and map zoom can always reset", async ({ page }) => {
  await mockLanding(page);
  await page.goto("/");
  const map = page.locator(".plant-map__viewport");
  await map.hover();
  await page.mouse.wheel(0, 240);
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
  await expect(map).toHaveAttribute("data-zoom", "1.000");
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(map).toHaveAttribute("data-zoom", "1.400");
  await page.getByRole("button", { name: "Reset map", exact: true }).click();
  await expect(map).toHaveAttribute("data-zoom", "1.000");
});

test("a failed background refresh keeps cached figures and explains their age", async ({
  page,
}) => {
  await page.clock.install();
  await page.emulateMedia({ reducedMotion: "reduce" });
  let unavailable = false;
  await page.route("**/api/v1/landing/status**", (route) =>
    unavailable
      ? route.fulfill({ status: 503, json: {} })
      : route.fulfill({ json: landingFixture() }),
  );
  await page.goto("/");
  const score = page.getByRole("button", { name: "Explore FTM score and plant" });
  await expect(score).toContainText("92.5");
  unavailable = true;
  await page.clock.fastForward(60_001);
  await expect(page.locator(".landing-data-state")).toContainText(
    "Showing the last available data",
  );
  await expect(score).toContainText("92.5");
  await expect(page.getByRole("button", { name: "Retry plant status" })).toBeEnabled();
});

for (const width of [390, 900, 1440]) {
  test(`unavailable status remains usable without overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.route("**/api/v1/landing/status**", (route) =>
      route.fulfill({ status: 503, json: {} }),
    );
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Retry plant status" })).toBeVisible();
    await page.getByRole("button", { name: "Explore AAT score and plant" }).click();
    await expect(page.getByRole("link", { name: "Open AAT dashboard" })).toHaveAttribute(
      "href",
      "/plant/aat",
    );
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: `test-results/landing-polish-${width}.png`, fullPage: true });
  });
}
