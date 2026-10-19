import { expect, test } from "@playwright/test";
import type { components } from "../../src/api/types";

test.skip(!process.env.T11_LIVE, "Set T11_LIVE=1 when the local database is available.");
// parked until owner names this function
test.skip("live AAT preview renders API points and captures desktop and mobile", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/analysis");
  await page.getByRole("combobox", { name: "Plant", exact: true }).selectOption("AAT");
  const response = page.waitForResponse(
    (r) =>
      r.url().includes("dashboard/preview") && new URL(r.url()).searchParams.get("plant") === "AAT",
  );
  await page.getByRole("button", { name: "Apply filters" }).click();
  const reply = await response;
  expect(reply.ok()).toBe(true);
  const preview = (await reply.json()) as components["schemas"]["DashboardPreview"];
  const point = preview.series.flatMap((s) => s.points)[0];
  expect(point).toBeTruthy();
  await expect(page.getByRole("cell", { name: point.cf, exact: true }).first()).toBeVisible();
  await expect(page.locator(".recharts-scatter-symbol").first()).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/screenshots/T11-analysis-aat.png" });
  await page.getByRole("complementary", { name: "Grading unavailable" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/screenshots/T11-unavailable-live.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/screenshots/T11-analysis-mobile.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect(errors).toEqual([]);
});
