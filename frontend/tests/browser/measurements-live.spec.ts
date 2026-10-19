import { expect, test } from "@playwright/test";
import type { components } from "../../src/api/types";

test.skip(!process.env.T12_LIVE, "Set T12_LIVE=1 with a populated local API.");

test("live AAT History facets retain API values and FVL opens as an empty plant", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const first = page.waitForResponse((r) => r.url().includes("/history/facets") && r.ok());
  await page.goto("/plant/AAT?dataView=history");
  const initial = (await (await first).json()) as components["schemas"]["HistoryFacetsOut"];
  expect(initial.default_month).toBeTruthy();
  await expect(page.getByRole("heading", { name: /^Week / }).first()).toBeVisible();
  const model = await page
    .getByRole("combobox", { name: "Model", exact: true })
    .locator("option")
    .nth(1)
    .textContent();
  expect(model).toBeTruthy();
  const filtered = page.waitForResponse(
    (r) =>
      r.url().includes("/history/summaries?") &&
      new URL(r.url()).searchParams.get("model") === model &&
      r.ok(),
  );
  await page.getByRole("combobox", { name: "Model", exact: true }).selectOption(model!);
  const response = await filtered;
  expect(new URL(response.url()).searchParams.get("month")).toBe(initial.default_month);
  expect(new URL(response.url()).searchParams.get("model")).toBe(model);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/T24-live-aat-filtered.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/T24-live-aat-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/plant/fvl?dataView=history");
  await expect(
    page.getByText("No approved measurements for this plant", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Model", exact: true })).toHaveCount(0);
  await page.screenshot({ path: "test-results/T24-live-fvl-empty.png" });
  expect(errors).toEqual([]);
  console.log(`T24 live AAT model=${model}; FVL History empty.`);
});
