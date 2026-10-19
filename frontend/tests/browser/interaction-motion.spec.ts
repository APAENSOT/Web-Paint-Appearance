import { expect, test } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { mockLanding } from "../landing-fixture";

test("navigation remains usable without the Web Animations API", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(Element.prototype, "animate", { value: undefined });
  });
  await mockHistory(page, "viewer");
  await mockLanding(page);
  await page.goto("/plant/AAT");
  await page.getByRole("button", { name: "Comparison", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Choose what to compare" })).toBeVisible();
});

test("workspace motion interrupts cleanly and filters do not replay it", async ({ page }) => {
  await mockHistory(page, "viewer");
  await mockLanding(page);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/plant/AAT");
  await expect(page.getByRole("heading", { name: "WaveScan", exact: true })).toBeVisible();
  const surface = page.locator("#workspace-results");
  await page.getByRole("button", { name: "Comparison", exact: true }).click();
  const animation = await surface.evaluate((element) =>
    element.getAnimations().map((a) => a.effect?.getTiming().duration),
  );
  expect(animation).toEqual([240]);
  await page.getByRole("button", { name: "Monthly Overview", exact: true }).click();
  expect(await surface.evaluate((element) => element.getAnimations().length)).toBeLessThanOrEqual(
    1,
  );
  await surface.evaluate((element) =>
    Promise.all(element.getAnimations().map((a) => a.finished.catch(() => {}))),
  );
  await page.getByRole("button", { name: "2026-06", exact: true }).click();
  expect(await surface.evaluate((element) => element.getAnimations().length)).toBe(0);
  await expect(page.getByRole("region", { name: "Monthly Overview", exact: true })).toContainText(
    "June 2026",
  );
});

test("keyboard navigation and reduced motion remain immediate", async ({ page }) => {
  await mockHistory(page, "viewer");
  await mockLanding(page);
  await page.goto("/plant/AAT");
  const surface = page.locator("#workspace-results");
  await page.getByRole("button", { name: "Comparison", exact: true }).focus();
  await page.keyboard.press("Enter");
  expect(await surface.evaluate((element) => element.getAnimations().length)).toBe(0);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Monthly Overview", exact: true }).click();
  expect(await surface.evaluate((element) => element.getAnimations().length)).toBe(0);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.getByRole("button", { name: "Comparison", exact: true }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => surface.evaluate((element) => element.getAnimations().length)).toBe(0);
});

test("live inspection opens and returns with finite motion; 3D zoom remains read-only", async ({
  page,
}, info) => {
  test.setTimeout(60000);
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/") && !["GET", "OPTIONS", "HEAD"].includes(r.method()))
      writes.push(r.method());
  });
  await page.goto("/plant/FTM");
  await page.getByRole("button", { name: "Monthly Detail", exact: true }).click();
  const card = page.getByRole("button", { name: /Open P703 DBL RANGER · Arctic White/ });
  await expect(card).toBeVisible({ timeout: 30000 });
  await card.click();
  const inspection = page.locator(".monthly-inspection");
  await expect(inspection).toBeVisible();
  const zoom = page.getByRole("button", { name: "Zoom in", exact: true });
  await expect(zoom).toBeEnabled({ timeout: 30000 });
  const marker = page.locator('.studio-point-marker[style*="visibility: visible"]').first();
  await expect(marker).toBeVisible();
  const before = await marker.getAttribute("style");
  await zoom.click();
  await zoom.click();
  await expect.poll(() => marker.getAttribute("style")).not.toBe(before);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Zoom out", exact: true }).click();
  await page.screenshot({ path: info.outputPath("inspection-after-zoom.png") });
  await page.getByRole("button", { name: "All profiles", exact: true }).click();
  await expect(card).toBeVisible();
  expect(writes).toEqual([]);
  await page.screenshot({ path: info.outputPath("gallery-return.png") });
});
