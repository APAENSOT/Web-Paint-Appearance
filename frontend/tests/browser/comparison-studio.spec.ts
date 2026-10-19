import { expect, test } from "@playwright/test";
import { mockStudio } from "../studio-fixtures";
async function open(page: import("@playwright/test").Page) {
  const calls = await mockStudio(page);
  await page.goto("/plant/AAT");
  await page.getByRole("button", { name: "Comparison", exact: true }).click();
  return calls;
}
test("T82 vehicle visuals preserve nine selections, n=0/1/many, raw duplicate traces, zeros and source fields", async ({
  page,
}) => {
  const calls = await open(page);
  await page.getByRole("button", { name: "Vehicles", exact: true }).click();
  await page.getByRole("radio", { name: "P703", exact: true }).check();
  await page.getByRole("checkbox", { name: "Measured month 2026-06" }).check();
  for (let i = 1; i <= 9; i++)
    await page.getByRole("button", { name: `Add vehicle ${i}`, exact: true }).click();
  await page.getByRole("button", { name: "Vehicle CF distributions", exact: true }).click();
  await expect(page.getByTestId("studio-month-box")).toHaveCount(16);
  await expect(page.getByRole("region", { name: "Vertical distributions" })).toContainText(
    "Not measured",
  );
  const h = page.getByRole("region", { name: "Horizontal distributions" });
  await expect(h.locator("svg circle")).toHaveCount(1);
  await expect(h.locator("svg rect")).toHaveCount(7);
  await page.screenshot({
    path: `test-results/screenshots/${process.env.COMPARISON_EVIDENCE_PREFIX ?? "T85"}-vehicle-cf-desktop.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Raw DU-WE profiles", exact: true }).click();
  const raw = page.getByRole("region", { name: "Raw vehicle profile card" });
  await expect(raw.getByRole("region", { name: "Horizontal DU-WE", exact: true })).toHaveCount(1);
  await expect(raw.getByRole("button", { name: /HOOD \/ measurement/ })).toHaveCount(2);
  await raw.getByRole("button", { name: /HOOD \/ measurement 1 \/ / }).click();
  await expect(raw.getByRole("region", { name: "Profile exact values" })).toContainText("DU: 0");
  await expect(raw.getByRole("region", { name: "Profile exact values" })).toContainText(
    "10.00000000000000001",
  );
  await expect(raw.getByRole("region", { name: "Profile exact values" })).toContainText(
    "source_row",
  );
  await raw.getByText("Historical unaligned raw rows (1)", { exact: true }).click();
  await expect(raw).toContainText("OLDHOOD");
  await page.screenshot({
    path: `test-results/screenshots/${process.env.COMPARISON_EVIDENCE_PREFIX ?? "T85"}-vehicle-profile-desktop.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: `test-results/screenshots/${process.env.COMPARISON_EVIDENCE_PREFIX ?? "T85"}-vehicle-profile-mobile.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Next columns", exact: true }).click();
  await expect(page.getByLabel("Profile vehicle").locator("option")).toHaveCount(1);
  expect(calls.visuals.at(-1)).toHaveLength(1);
  expect(calls.visuals.every((ids) => ids.length <= 8)).toBe(true);
  await page.getByRole("radio", { name: "Film Thickness", exact: true }).check();
  await page.getByRole("radio", { name: "P703", exact: true }).check();
  await page.getByRole("button", { name: "Add vehicle 1", exact: true }).click();
  await expect(page.getByTestId("cell-1-0")).toContainText("18.2500");
  await expect(page.getByRole("region", { name: "WaveScan vehicle visuals" })).toHaveCount(0);
});
