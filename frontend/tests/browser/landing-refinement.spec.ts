import { expect, test } from "@playwright/test";
import { mockLanding } from "../landing-fixture";

// GET /landing/status is controlled so the landing chrome never depends on live data.
test.beforeEach(async ({ page }) => mockLanding(page));

test("score selection, photo focus and map feedback lead to the same plant", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Plant scores" }).getByRole("button")).toHaveCount(
    4,
  );
  await page.getByRole("button", { name: "Explore AAT score and plant" }).click();
  await expect(page.getByRole("heading", { name: "AAT · Plant preview" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Explore AAT score and plant" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page
    .getByRole("navigation", { name: "Explore countries" })
    .getByRole("button", { name: /Thailand/ })
    .click();
  const photo = page.getByRole("button", { name: "Explore FTM factory photo" });
  await expect(photo.locator("img")).toBeVisible();
  expect(
    await photo.locator("img").evaluate((image) => (image as HTMLImageElement).naturalWidth),
  ).toBeGreaterThan(0);
  await photo.focus();
  await expect(page.getByRole("button", { name: "Preview FTM, Thailand" })).toHaveAttribute(
    "data-highlighted",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByRole("link", { name: "Open FTM dashboard" })).toBeVisible();
  await page.getByRole("button", { name: "Preview FTM, Thailand" }).focus();
  await expect(page.getByRole("tooltip")).toContainText(/Last upload: (\d+[mhd] ago|None yet)/);
  await page.getByRole("button", { name: "Show all plants", exact: true }).click();
  await expect(page.locator(".plant-map__pin")).toHaveCount(4);
});

test("photos and selectors stay usable in both themes and on compact screens", async ({ page }) => {
  for (const width of [1440, 390]) {
    for (const theme of ["light", "dark"]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((theme) => localStorage.setItem("ct-theme", theme), theme);
      await page.goto("/");
      await expect(page.locator(".plant-map__pin")).toHaveCount(4);
      await page.evaluate(() => document.fonts.ready);
      await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark)/);
      await page.screenshot({
        path: `test-results/screenshots/LANDING-refined-${theme}-${width}.png`,
        fullPage: true,
      });
      await page
        .getByRole("navigation", { name: "Explore countries" })
        .getByRole("button", { name: /Thailand/ })
        .click();
      await expect(page.locator(".plant-photo")).toHaveCount(2);
      await expect
        .poll(() => page.locator(".plant-map__viewport").getAttribute("data-zoom").then(Number))
        .toBeGreaterThan(1.5);
      await page.waitForTimeout(550);
      await page.locator(".plant-photo").first().scrollIntoViewIfNeeded();
      await expect(page.getByRole("button", { name: "Explore AAT factory photo" })).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await page.screenshot({
        path: `test-results/screenshots/LANDING-photos-${theme}-${width}.png`,
        fullPage: true,
      });
      await page
        .getByRole("navigation", { name: "Explore countries" })
        .getByRole("button", { name: /South Africa/ })
        .click();
      await expect(page.locator(".plant-photo")).toHaveCount(1);
      await expect(page.locator(".plant-photo")).toContainText("location unconfirmed");
    }
  }
});
