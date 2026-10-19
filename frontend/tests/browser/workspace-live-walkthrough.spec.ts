import { expect, test } from "@playwright/test";

// Standing localhost + database, read-only. No mocked quality facts or writes.
for (const width of [1440, 390]) {
  test(`live plant walkthrough at ${width}px`, async ({ page }, info) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width, height: 1000 });
    const writes: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/api/") && !["GET", "HEAD", "OPTIONS"].includes(request.method()))
        writes.push(`${request.method()} ${request.url()}`);
    });
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Open a plant dashboard" })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Explore FTM score and plant" }),
    ).not.toContainText("Loading plant status", { timeout: 30000 });
    await page.screenshot({ path: info.outputPath(`live-network-${width}.png`) });
    await page.getByRole("button", { name: "Explore FTM score and plant" }).click();
    await page.getByRole("link", { name: "Open FTM dashboard" }).click();
    await expect(page.getByRole("heading", { name: "WaveScan", exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`live-workspace-${width}.png`) });
    const choose = async (name: string) => {
      if (width < 1024) await page.getByRole("button", { name: "Views & filters" }).click();
      await page.getByRole("button", { name, exact: true }).click();
    };
    await choose("Monthly Detail");
    await expect(page.locator(".monthly-profile-card").first()).toBeVisible({ timeout: 30000 });
    await page.screenshot({ path: info.outputPath(`live-monthly-detail-${width}.png`) });
    await choose("Comparison");
    await expect(page.getByRole("heading", { name: "Choose what to compare" })).toBeVisible();
    await page
      .getByRole("group", { name: "Measurement", exact: true })
      .getByRole("button", { name: "Film Thickness", exact: true })
      .click();
    if (width < 1024) await expect(page.locator(".workspace-domain")).toHaveText("Film Thickness");
    await choose("Analysis & Report");
    await expect(page.getByRole("region", { name: "Report choices" })).toBeVisible({
      timeout: 30000,
    });
    await expect(page.locator(".report-companion")).toHaveAttribute("data-renderer", "3d");
    await expect
      .poll(() =>
        page
          .locator(".report-companion__base")
          .evaluate((img) => (img as HTMLImageElement).naturalWidth),
      )
      .toBeGreaterThan(0);
    await page.screenshot({ path: info.outputPath(`live-analysis-${width}.png`) });
    await page
      .locator(".report-companion")
      .screenshot({ path: info.outputPath(`live-report-guide-${width}.png`) });
    await choose("Standard");
    await expect(page.getByRole("region", { name: "FTM standard" })).toBeVisible();
    await choose("Model Detail");
    await expect(page.getByRole("heading", { name: "Model Detail", exact: true })).toBeVisible({
      timeout: 30000,
    });
    if (width < 1024) await page.getByRole("button", { name: "Views & filters" }).click();
    await page.getByTestId("model-detail-nav-point-check").click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Point Check", exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`live-point-check-${width}.png`) });
    await choose("Data");

    await expect(page.locator("#workspace-results h2").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(writes).toEqual([]);
  });
}
