import { expect, test } from "@playwright/test";
import { mockLanding } from "../landing-fixture";

test("plant header: feed, last upload and cars come from the landing status read", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await mockLanding(page);
  await page.goto("/plant/ftm");
  const header = page
    .getByRole("banner", { name: "Plant dashboard" })
    .or(page.locator('header[aria-label="Plant dashboard"]'));
  const feed = header.getByLabel("Data Feed");
  await expect(feed).toContainText("Update");
  await expect(feed).toContainText("week 2");
  await expect(feed).toContainText("late 0 · missing 0 · 62.5% of plan");
  const upload = header.getByLabel("Last Upload");
  await expect(upload).toContainText("2h ago");
  await expect(upload).toContainText("FTM film 4.xlsx");
  const cars = header.getByLabel("Cars on File");
  await expect(cars).toContainText("47");
  await expect(cars).toContainText("169");
  await expect(cars).toContainText("Month-to-date quality 92.5%");
  await expect(header).not.toContainText("this slice has no API field");
  await header.first().screenshot({ path: "test-results/screenshots/PLANT-HEADER.png" });
});

test("plant header says so when the status read fails", async ({ page }) => {
  await page.route("**/api/v1/landing/status**", (route) =>
    route.fulfill({ status: 500, json: {} }),
  );
  await page.goto("/plant/ftm");
  await expect(page.getByLabel("Data Feed")).toContainText("Status unavailable");
});
