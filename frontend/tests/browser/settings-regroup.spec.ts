import { expect, test } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { catalogueFixture } from "../fixtures";

for (const role of ["admin", "viewer"] as const) {
  test(`settings grouping and legacy links remain usable for ${role}`, async ({ page }) => {
    await mockHistory(page, role);
    await page.route("**/api/v1/standards/catalogue", (route) =>
      route.fulfill({ json: catalogueFixture }),
    );
    await page.route("**/api/v1/plants/*/model-points", (route) =>
      route.fulfill({ json: { plant_code: "FTM", models: [], attachable_models: [] } }),
    );
    await page.goto("/plant/FTM?standardView=model");
    await expect(page.getByRole("button", { name: "Model Detail", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const model = page.getByRole("navigation", { name: "Model Detail views" });
    await expect(model.getByRole("button", { name: "Model", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(model.getByRole("button", { name: "Point Check", exact: true })).toHaveCount(
      role === "admin" ? 1 : 0,
    );
    await expect(model.getByRole("button", { name: "Colours", exact: true })).toBeVisible();
    await expect(
      model.getByRole("button", { name: "Inspection points", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Notes", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Standard", exact: true }).click();
    const standard = page.getByRole("navigation", { name: "Standard views" });
    await expect(standard.getByRole("button", { name: "Color Family" })).toBeVisible();
    await expect(standard.getByRole("button", { name: "Model", exact: true })).toHaveCount(0);
    await expect(standard.getByRole("button", { name: "Point Check", exact: true })).toHaveCount(0);
    await expect(standard.getByRole("button", { name: "Film Thickness" })).toHaveCount(
      role === "admin" ? 1 : 0,
    );
    if (role === "admin") {
      await page.goto("/plant/FTM?standardView=points");
      await expect(model.getByRole("button", { name: "Point Check" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await model.getByRole("button", { name: "Model", exact: true }).click();
      await expect(page).toHaveURL(/modelView=model/);
      await page.reload();
      await expect(model.getByRole("button", { name: "Model", exact: true })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await page.goBack();
      await expect(model.getByRole("button", { name: "Point Check" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    }
    await page.setViewportSize({ width: 390, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: `test-results/settings-regroup-${role}.png`, fullPage: true });
  });
}
