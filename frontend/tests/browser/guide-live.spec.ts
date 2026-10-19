import { expect, test } from "@playwright/test";

// Standing dev services, read-only: verifies the new conversation against real API answers.
for (const width of [1440, 390]) {
  test(`report guide with live measurements at ${width}px`, async ({ page }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width, height: 1000 });
    const writes: string[] = [];
    const errors: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/api/") && !["GET", "HEAD", "OPTIONS"].includes(request.method()))
        writes.push(request.method());
    });
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/plant/FTM");
    if (width < 1024) await page.getByRole("button", { name: "Views & filters" }).click();
    await page.getByRole("button", { name: "Analysis & Report", exact: true }).click();
    const chat = page.getByTestId("assistant");
    await expect(chat.getByRole("heading", { name: "Talk through your report" })).toBeVisible({
      timeout: 30000,
    });
    await expect(page.locator(".report-companion")).toHaveAttribute("data-renderer", "3d");
    expect((await page.locator(".report-companion").boundingBox())!.width).toBeGreaterThan(
      width < 1024 ? 85 : 105,
    );
    const input = chat.getByLabel("Ask your report guide");
    await input.fill("How are we doing?");
    await input.press("Enter");
    const answer = chat.locator('[data-answer="summary"]');
    await expect(answer.locator("[data-explanation]")).toBeVisible({ timeout: 30000 });
    await expect(answer.locator(".guide-takeaway").first()).toBeVisible();
    const comparison = chat.getByTestId("supporting-comparison");
    await expect(comparison).toBeVisible({ timeout: 30000 });
    expect(await comparison.locator("[data-shift]").count()).toBeGreaterThan(0);
    await answer
      .locator("[data-headline]")
      .evaluate((element) => element.scrollIntoView({ block: "start", behavior: "instant" }));
    await expect(answer.locator("[data-headline]")).toBeInViewport();
    await page.screenshot({
      path: `test-results/screenshots/AR08-live-${width}.png`,
      animations: "disabled",
    });
    await comparison.locator("[data-shift]").first().scrollIntoViewIfNeeded();
    await page.screenshot({
      path: `test-results/screenshots/AR08-month-comparison-${width}.png`,
      animations: "disabled",
    });
    await page.getByLabel("Month", { exact: true }).selectOption("2026-09");
    await expect(chat.locator("[data-turn]")).toHaveCount(0);
    await expect(input).toHaveValue("");
    await input.fill("What about Ranger?");
    await input.press("Enter");
    await expect(chat.locator('[data-answer="model_report"] [data-headline]')).toContainText(
      /Ranger/i,
      { timeout: 30000 },
    );
    await input.fill("Compare it with Raptor");
    await input.press("Enter");
    const pair = chat.locator('[data-answer="compare_models"]');
    await expect(pair.locator("[data-choice]").first()).toBeVisible({ timeout: 30000 });
    await input.fill("Clear");
    await input.press("Enter");
    await expect(pair.locator("[data-box]")).toHaveCount(2, { timeout: 30000 });
    await expect(pair.locator(".guide-group-values")).toContainText("Typical reading");
    await expect(chat.locator("[data-turn]")).toHaveCount(2);
    await pair.locator(".guide-group-values").scrollIntoViewIfNeeded();
    await page.screenshot({
      path: `test-results/screenshots/AR08-model-comparison-${width}.png`,
      animations: "disabled",
    });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}
