import { expect, test } from "@playwright/test";
import { mockLanding } from "../landing-fixture";

// GET /landing/status is controlled so the landing chrome never depends on live data.
test.beforeEach(async ({ page }) => mockLanding(page));

test("landing theme switch works with keyboard and preserves the choice", async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem("ct-theme")) localStorage.setItem("ct-theme", "light");
  });
  await page.goto("/");
  await expect(page.getByRole("banner")).not.toContainText(/critical shipments/i);
  await expect(page.getByRole("img", { name: "Ford", exact: true })).toBeVisible();
  const toggle = page.getByRole("switch", { name: "Dark theme" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.focus();
  await page.keyboard.press("Space");
  await expect(toggle).toHaveAttribute("data-motion", "instant");
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await toggle.click();
  await expect(toggle).toHaveAttribute("data-motion", "animated");
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("rapid theme reversal keeps the final choice", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("ct-theme", "light"));
  await page.goto("/");
  const toggle = page.getByRole("switch", { name: "Dark theme" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.dblclick({ delay: 40 });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  expect(await page.evaluate(() => localStorage.getItem("ct-theme"))).toBe("light");
});

test("header fits on mobile and respects reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const toggle = page.getByRole("switch", { name: "Dark theme" });
  await expect(toggle).toBeVisible();
  const bounds = await toggle.boundingBox();
  expect(bounds!.height).toBeGreaterThanOrEqual(44);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  expect(
    await page.getByRole("banner").evaluate((header) => header.scrollWidth <= header.clientWidth),
  ).toBe(true);
  // The app's global reduced-motion rule uses an effectively instant 0.001ms.
  const duration = await page
    .locator(".theme-toggle__thumb")
    .evaluate((element) => Number.parseFloat(getComputedStyle(element).transitionDuration));
  expect(duration).toBeLessThanOrEqual(0.001);
});

for (const theme of ["light", "dark"] as const) {
  for (const width of [1440, 390]) {
    test(`header evidence: ${theme} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((savedTheme) => localStorage.setItem("ct-theme", savedTheme), theme);
      await page.goto("/");
      const logo = page.getByRole("img", { name: "Ford", exact: true });
      await expect(logo).toBeVisible();
      await expect
        .poll(() => logo.evaluate((img) => (img as HTMLImageElement).naturalWidth))
        .toBeGreaterThan(0);
      await expect(page.getByRole("switch", { name: "Dark theme" })).toHaveAttribute(
        "aria-checked",
        String(theme === "dark"),
      );
      await page.screenshot({
        path: `test-results/screenshots/LANDING-header-${theme}-${width}.png`,
        clip: { x: 0, y: 0, width, height: width === 390 ? 210 : 120 },
        animations: "disabled",
      });
    });
  }
}
