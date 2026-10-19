import { expect, test } from "@playwright/test";
import { mockLanding } from "../landing-fixture";

// GET /landing/status is controlled so the landing chrome never depends on live data.
test.beforeEach(async ({ page }) => mockLanding(page));

test("wave motion can be paused and the preference survives reload", async ({ page }) => {
  await page.goto("/");
  const pause = page.getByRole("button", { name: "Pause ambient motion" });
  await expect(pause).toBeVisible();
  await pause.click();
  await expect(page.getByRole("button", { name: "Resume ambient motion" })).toBeVisible();
  await expect(page.locator(".landing-waves")).toHaveAttribute("data-motion", "paused");
  await page.reload();
  await page.getByRole("button", { name: "Resume ambient motion" }).click();
  await expect(page.locator(".landing-waves")).toHaveAttribute("data-motion", "running");
});

test("reduced motion renders a static background", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator(".landing-waves")).toHaveAttribute("data-motion", "reduced");
  await expect(page.getByRole("button", { name: "Pause ambient motion" })).not.toBeVisible();
});

test("background has a fallback when WebGL is unavailable", async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      kind: string,
      ...args: unknown[]
    ) {
      if (kind === "webgl") return null;
      return Reflect.apply(original, this, [kind, ...args]);
    } as typeof original;
  });
  await page.goto("/");
  await expect(page.locator(".landing-waves")).toHaveAttribute("data-renderer", "fallback");
  await expect(page.getByRole("heading", { name: "Paint Appearance", exact: true })).toBeVisible();
});

for (const theme of ["light", "dark"] as const) {
  for (const width of [1440, 390]) {
    test(`wave evidence: ${theme} at ${width}px`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((value) => localStorage.setItem("ct-theme", value), theme);
      await page.goto("/");
      await expect(page.locator(".landing-waves")).toHaveAttribute("data-renderer", "webgl");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.getByRole("button", { name: "Pause ambient motion" }).click();
      await page.screenshot({
        path: `test-results/screenshots/LANDING-waves-${theme}-${width}.png`,
        fullPage: true,
        animations: "disabled",
      });
      expect(errors).toEqual([]);
    });
  }
}
