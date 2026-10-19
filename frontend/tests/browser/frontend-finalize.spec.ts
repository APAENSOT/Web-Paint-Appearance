import { expect, test } from "@playwright/test";

// Standing local API; this walkthrough must never change engineering data.
for (const theme of ["dark", "light"] as const) {
  for (const width of [1440, 390]) {
    test(`route and theme smoke: ${theme}, ${width}px`, async ({ page }, info) => {
      test.setTimeout(90000);
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((value) => localStorage.setItem("ct-theme", value), theme);
      const errors: string[] = [];
      const writes: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.route("**/api/**", (route) => {
        if (!["GET", "HEAD", "OPTIONS"].includes(route.request().method())) {
          writes.push(`${route.request().method()} ${route.request().url()}`);
          return route.abort();
        }
        return route.continue();
      });
      const fits = async () => {
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
        await expect(page.locator("html")).toHaveCSS("color-scheme", theme);
      };
      await page.goto("/");
      await expect(page.getByRole("heading", { name: "IMG Plant Location" })).toBeVisible();
      await fits();
      for (const code of ["FTM", "AAT", "FVL", "SAP"]) {
        const loaded = page.waitForResponse(
          (response) =>
            response.url().includes(`/plants/${code}/wavescan/overview`) &&
            response.request().method() === "GET",
        );
        await page.goto(`/plant/${code}`);
        expect((await loaded).status()).toBe(200);
        await expect(page.getByRole("button", { name: "Views & filters" })).toHaveCount(
          width < 1024 ? 1 : 0,
        );
        await expect(page.locator("#workspace-results")).toBeVisible();
        await expect(page.getByRole("heading", { name: "WaveScan", exact: true })).toBeVisible();
        await expect(
          page
            .locator("#workspace-results")
            .getByRole("status")
            .filter({ hasText: /Loading/ }),
        ).toHaveCount(0);
        await fits();
        if (code === "FTM") {
          await page.screenshot({ path: info.outputPath(`workspace-${theme}-${width}.png`) });
          const filmLoaded = page.waitForResponse(
            (response) =>
              response.url().includes("/plants/FTM/filmthickness/overview") &&
              response.url().includes("2026-05"),
          );
          await page.goto("/plant/FTM?paint=film&filmMonth=2026-05");
          expect((await filmLoaded).status()).toBe(200);
          await expect(page.getByText("May 2026", { exact: true }).first()).toBeVisible();
          const layers = page.getByRole("tablist", { name: "Coating layers" });
          await expect(layers.getByRole("tab")).toHaveCount(4);
          const ecoat = layers.getByRole("tab", { name: "E-coat", exact: true });
          await ecoat.focus();
          await page.keyboard.press("ArrowRight");
          const primer = layers.getByRole("tab", { name: "Primer", exact: true });
          await expect(primer).toBeFocused();
          await expect(primer).toHaveAttribute("aria-selected", "true");
          expect((await primer.boundingBox())!.height).toBeGreaterThanOrEqual(44);
          await fits();
          await page.screenshot({ path: info.outputPath(`film-${theme}-${width}.png`) });
        }
      }
      for (const path of ["/admin", "/batches", "/analysis"]) {
        await page.goto(path);
        await expect(page.locator("main")).toBeVisible();
        await expect(page.locator("main h1, main h2").first()).toBeVisible();
        const themeButton = page.getByRole("button", { name: /Switch to (light|dark) theme/ });
        expect((await themeButton.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        await fits();
        await page.screenshot({
          path: info.outputPath(`${path.slice(1)}-${theme}-${width}.png`),
          fullPage: true,
        });
      }
      await page.goto("/plant/FTM/model/ranger-ignite-orange");
      await expect(
        page.getByRole("complementary", { name: "Design preview notice" }),
      ).toContainText("Sample data");
      await expect(page.getByText("Sample data", { exact: true }).first()).toBeVisible();
      await fits();
      await page.screenshot({
        path: info.outputPath(`preview-${theme}-${width}.png`),
        fullPage: true,
      });
      const stage = page.getByRole("region", { name: "3D vehicle model — drag to rotate" });
      await stage.focus();
      await page.keyboard.press("ArrowRight");
      await expect(stage).toBeFocused();
      await page.getByRole("link", { name: "Open plant dashboard", exact: true }).click();
      await expect(page.locator("#workspace-results")).toBeVisible();
      expect(errors).toEqual([]);
      expect(writes).toEqual([]);
    });
  }
}
