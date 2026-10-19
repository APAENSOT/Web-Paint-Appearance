import { expect, test } from "@playwright/test";

for (const width of [1440, 390])
  test(`body colour previews at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/tests/fixtures/profile-photo.html");
    await expect(page.locator(".monthly-painted-photo")).toHaveCount(7);
    await page.waitForLoadState("networkidle");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
    await page.screenshot({ path: info.outputPath(`body-colours-${width}.png`), fullPage: true });
    if (width === 1440) {
      for (const hex of ["#1C1C1C", "#F4F6F7"]) {
        await page.goto(`/tests/fixtures/profile-photo.html?hex=${encodeURIComponent(hex)}`);
        await page.waitForLoadState("networkidle");
        await page.screenshot({
          path: info.outputPath(`body-colours-${hex.slice(1)}.png`),
          fullPage: true,
        });
      }
    }
    await page.goto("/tests/fixtures/profile-photo.html?original=1");
    await expect(page.locator(".monthly-photo img")).toHaveCount(7);
  });
