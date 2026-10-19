import { expect, test } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { mockLanding } from "../landing-fixture";
import { filmOverviewFixture } from "../film-overview-fixtures";

for (const choice of ["Wave Scan", "Film Thickness"] as const) {
  test(`plant preview opens the selected ${choice} dashboard`, async ({ page }) => {
    await mockHistory(page, "viewer");
    await mockLanding(page);
    await page.route("**/api/v1/plants/*/filmthickness/overview**", (route) =>
      route.fulfill({ json: { ...filmOverviewFixture, plant_code: "AAT" } }),
    );
    await page.goto("/");
    await page.getByRole("button", { name: "Explore AAT score and plant" }).click();
    const areas = page.getByLabel("Factory areas", { exact: true });
    // Change away and back so Wave Scan also verifies explicit selection.
    await areas.getByRole("button", { name: "Film Thickness", exact: true }).click();
    await areas.getByRole("button", { name: choice, exact: true }).click();
    const open = page.getByRole("link", { name: "Open AAT dashboard" });
    if (choice === "Film Thickness") await expect(open).toHaveAttribute("href", /paint=film/);
    await open.click();
    await expect(
      page.getByRole("heading", {
        name: choice === "Wave Scan" ? "WaveScan" : choice,
        exact: true,
      }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("heading", {
        name: choice === "Wave Scan" ? "WaveScan" : choice,
        exact: true,
      }),
    ).toBeVisible();
  });
}

test("landing uses plant preview and keeps collapsed filters inaccessible", async ({
  page,
}, info) => {
  await mockHistory(page, "viewer");
  await mockLanding(page);
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Open a plant dashboard" })).toHaveCount(0);
  await page.getByRole("button", { name: "Explore AAT score and plant" }).click();
  await page.getByRole("link", { name: "Open AAT dashboard" }).click();
  await expect(page.getByRole("navigation", { name: "Plant views and settings" })).toBeVisible();
  const colourToggle = page.getByRole("button", { name: "Color", exact: true });
  const contentId = await colourToggle.getAttribute("aria-controls");
  await expect(page.locator(`[id="${contentId}"]`)).toHaveAttribute("inert", "");
  await colourToggle.click();
  await expect(page.locator(`[id="${contentId}"]`)).not.toHaveAttribute("inert", "");
  await page.screenshot({ path: info.outputPath("workspace-desktop.png") });
});

for (const width of [390, 820]) {
  test(`compact workspace ${width}: results first, keyboard drawer, filter persistence`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockHistory(page, "viewer");
    await mockLanding(page);
    await page.goto("/plant/AAT");
    await expect(page.locator(".plant-status-facts")).toBeHidden();
    const content = page.locator("#workspace-results");
    await expect(content).toBeVisible();
    expect((await content.boundingBox())!.y).toBeLessThan(320);
    const trigger = page.getByRole("button", { name: "Views & filters" });
    await trigger.focus();
    await page.keyboard.press("Enter");
    const drawer = page.getByRole("dialog", { name: "AAT workspace" });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("button", { name: "2026-06", exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`navigation-${width}.png`) });
    await drawer.getByRole("button", { name: "2026-06", exact: true }).click();
    await drawer.getByRole("button", { name: "Show results" }).click();
    await expect(drawer).toBeHidden();
    await expect(trigger).toBeFocused();
    await expect(page.getByRole("region", { name: "Monthly Overview", exact: true })).toContainText(
      "June 2026",
    );
    await page.screenshot({ path: info.outputPath(`workspace-${width}.png`) });
    await trigger.click();
    await drawer.getByRole("button", { name: "Comparison", exact: true }).click();
    await expect(drawer).toBeHidden();
    await expect(page.getByRole("heading", { name: "Choose what to compare" })).toBeVisible();
    await trigger.click();
    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();
    await page.getByRole("button", { name: "Plant status" }).click();
    await expect(page.locator(".plant-status-facts")).toBeVisible();
    await page.getByRole("button", { name: "Plant status" }).click();
    await page.getByRole("button", { name: "Switch to light theme" }).click();
    await page.screenshot({ path: info.outputPath(`workspace-light-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.getByRole("link", { name: "Back to tracking home", exact: true }).click();
    await expect(page.getByRole("button", { name: "Explore AAT score and plant" })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`network-light-${width}.png`) });
  });
}

test("responsive layout switches without leaving a modal or scroll lock behind", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  await mockLanding(page);
  await page.setViewportSize({ width: 820, height: 1000 });
  await page.goto("/plant/AAT");
  await page.getByRole("button", { name: "Views & filters" }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Plant views and settings" })).toBeVisible();
  await expect(page.locator("body")).not.toHaveAttribute("data-scroll-locked");
});
