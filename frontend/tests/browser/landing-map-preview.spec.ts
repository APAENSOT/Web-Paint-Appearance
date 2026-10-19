import { expect, test, type Page } from "@playwright/test";
import { mockLanding } from "../landing-fixture";

// GET /landing/status is controlled so the landing chrome never depends on live data.
test.beforeEach(async ({ page }) => mockLanding(page));

const countryButton = (page: Page, name: string) =>
  page
    .getByRole("navigation", { name: "Explore countries" })
    .getByRole("button", { name: new RegExp(name) });

test("factory landmarks share pause state, stay named, and distinguish all four plant previews", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".plant-map .factory-landmark__model")).toHaveCount(4);
  await expect(page.locator(".plant-map__dot")).toHaveCount(0);
  await expect(
    page.locator(".plant-map__pin .factory-smoke[data-running=true]").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Pause ambient motion" }).click();
  await expect(page.locator(".factory-smoke[data-running=true]")).toHaveCount(0);
  for (const [country, code, design] of [
    ["Thailand", "FTM", "Solar courtyard"],
    ["Thailand", "AAT", "Twin assembly halls"],
    ["Vietnam", "FVL", "Garden entrance"],
    ["South Africa", "SAP", "Solar assembly campus"],
  ]) {
    await countryButton(page, country).click();
    await page
      .getByRole("complementary")
      .locator(".plant-preview__plant-picker")
      .getByRole("button", { name: code })
      .click();
    await expect(page.locator(".factory-stage[data-design]")).toHaveAttribute(
      "data-design",
      design,
    );
    await expect(page.getByRole("link", { name: `Open ${code} dashboard` })).toHaveAttribute(
      "href",
      `/plant/${code.toLowerCase()}`,
    );
    await expect(page.getByRole("button", { name: "Highlight Wave Scan area" })).toBeVisible();
    await page.waitForTimeout(700);
    await page
      .getByRole("complementary")
      .screenshot({ path: `test-results/screenshots/LANDING-factory-${code}.png` });
  }
});

test("pointer navigation uses a view transition, while keyboard navigation remains immediate", async ({
  page,
}) => {
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      document.documentElement.dataset.transitionCalls = "0";
    });
    const original = document.startViewTransition?.bind(document);
    if (original)
      document.startViewTransition = (...args: Parameters<typeof original>) => {
        document.documentElement.dataset.transitionCalls = String(
          Number(document.documentElement.dataset.transitionCalls ?? 0) + 1,
        );
        return Reflect.apply(original, document, args);
      };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Preview FTM, Thailand" }).click();
  await page.getByRole("link", { name: "Open FTM dashboard" }).click();
  await expect(page).toHaveURL(/\/plant\/ftm/);
  await expect(page.locator("html")).toHaveAttribute("data-transition-calls", "1");
  await page.goBack();
  await page.getByRole("button", { name: "Preview FTM, Thailand" }).click();
  await page.getByRole("link", { name: "Open FTM dashboard" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/plant\/ftm/);
  await expect(page.locator("html")).toHaveAttribute("data-transition-calls", "1");
});

test("compact landmarks remain individually clickable and smoke stops when the document is hidden", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 1100 });
  await page.goto("/");
  await page.locator(".plant-map__viewport").scrollIntoViewIfNeeded();
  await expect(page.locator(".plant-map__pin")).toHaveCount(4);
  await expect(page.locator(".factory-smoke[data-running=true]").first()).toBeVisible();
  for (const pin of await page.locator(".plant-map__pin").all()) {
    expect(
      await pin.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return (
          document
            .elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2)
            ?.closest("button") === element
        );
      }),
    ).toBe(true);
  }
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.locator(".factory-smoke[data-running=true]")).toHaveCount(0);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.locator(".factory-smoke[data-running=true]").first()).toBeVisible();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".factory-smoke").first()).toBeHidden();
});

test("country to plant preview stays on landing, supports both Thai plants and opens the dashboard", async ({
  page,
}) => {
  await page.goto("/");
  await countryButton(page, "Thailand").click();
  await expect(page.getByRole("heading", { name: "Explore the plants" })).toBeVisible();
  await expect
    .poll(() => page.locator(".plant-map__viewport").getAttribute("data-zoom").then(Number))
    .toBeGreaterThan(1.5);
  const panel = page.getByRole("complementary", { name: "Plant preview" });
  await panel.locator(".plant-preview__plant-picker").getByRole("button", { name: "FTM" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(panel.getByRole("heading", { name: "FTM · Plant preview" })).toBeVisible();
  await expect(panel.locator("canvas")).toBeVisible();
  // Live weekly feed sentence from GET /landing/status (no demo copy).
  await expect(panel.getByText(/colours in so far|No standard models/)).toBeVisible();
  await panel.getByRole("button", { name: "Film Thickness", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: "Highlight Film Thickness area" }),
  ).toHaveAttribute("aria-pressed", "true");
  await panel.locator(".plant-preview__plant-picker").getByRole("button", { name: "AAT" }).click();
  await expect(panel.getByRole("link", { name: "Open AAT dashboard" })).toHaveAttribute(
    "href",
    "/plant/aat",
  );
  await expect(panel.getByText("Last upload", { exact: true })).toBeVisible();
  await expect(panel.locator('dt:text-is("Last upload") + dd')).toHaveText(
    /^(\d+[mhd] ago|No uploads yet)$/,
  );
  await panel.getByRole("link", { name: "Open AAT dashboard" }).click();
  await expect(page).toHaveURL(/\/plant\/aat/);
});

test("rapid country changes settle on the latest country and Escape restores overview with focus", async ({
  page,
}) => {
  await page.goto("/");
  await countryButton(page, "Thailand").click();
  await countryButton(page, "Vietnam").click();
  await countryButton(page, "South Africa").click();
  await expect(page.locator(".plant-map__viewport")).toHaveAttribute(
    "data-country",
    "South Africa",
  );
  await expect(page.getByRole("button", { name: "Preview SAP, South Africa" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Preview FVL, Vietnam" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "Overview Status" })).toBeVisible();
  await expect(countryButton(page, "All plants")).toBeFocused();
  await expect
    .poll(() => page.locator(".plant-map__viewport").getAttribute("data-zoom"))
    .toBe("1.000");
});

test("map plant dot opens inline preview and every country has a keyboard path", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Preview FTM, Thailand" }).click();
  await expect(page.getByRole("heading", { name: "FTM · Plant preview" })).toBeVisible();
  await countryButton(page, "Vietnam").focus();
  await page.keyboard.press("Enter");
  const plant = page
    .getByRole("complementary", { name: "Plant preview" })
    .locator(".plant-preview__plant-picker")
    .getByRole("button", { name: "FVL" });
  await plant.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("link", { name: "Open FVL dashboard" })).toBeVisible();
});

test("click country geometry selects it, dragging the same geometry only pans", async ({
  page,
}) => {
  await page.goto("/");
  const path = page.locator('[data-country-name="South Africa"]');
  const point = await path.evaluate((element) => {
    const path = element as SVGPathElement;
    const box = path.getBBox();
    const matrix = path.getScreenCTM()!;
    for (let x = box.x; x < box.x + box.width; x += box.width / 12) {
      for (let y = box.y; y < box.y + box.height; y += box.height / 12) {
        const point = new DOMPoint(x, y);
        const screen = point.matrixTransform(matrix);
        if (path.isPointInFill(point) && document.elementFromPoint(screen.x, screen.y) === path)
          return { x: screen.x, y: screen.y };
      }
    }
    throw new Error("No visible country hit target");
  });
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.mouse.move(point.x + 25, point.y + 15, { steps: 5 });
  await page.mouse.up();
  await expect(page.locator(".plant-map__viewport")).toHaveAttribute("data-country", "all");
  await page.mouse.click(point.x + 25, point.y + 15);
  await expect(page.locator(".plant-map__viewport")).toHaveAttribute(
    "data-country",
    "South Africa",
  );
});

test("reduced motion selects without a traveling zoom and missing WebGL preserves plant details", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      kind: string,
      ...args: unknown[]
    ) {
      if (kind === "webgl" || kind === "webgl2" || kind === "experimental-webgl") return null;
      return Reflect.apply(getContext, this, [kind, ...args]);
    } as typeof getContext;
  });
  await page.goto("/");
  await countryButton(page, "Vietnam").click();
  const zoom = await page.locator(".plant-map__viewport").getAttribute("data-zoom");
  expect(Number(zoom)).toBeGreaterThan(1.5);
  await page
    .getByRole("complementary")
    .locator(".plant-preview__plant-picker")
    .getByRole("button", { name: "FVL" })
    .click();
  await expect(page.getByText("3D view unavailable on this device.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open FVL dashboard" })).toBeVisible();
  await expect(page.getByText("Last upload", { exact: true })).toBeVisible();
  await expect(page.locator('dt:text-is("Last upload") + dd')).toHaveText(
    /^(\d+[mhd] ago|No uploads yet)$/,
  );
});

for (const theme of ["light", "dark"]) {
  for (const width of [1440, 390]) {
    test(`factory preview evidence ${theme} ${width}`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.setViewportSize({ width, height: 1100 });
      await page.addInitScript((theme) => {
        localStorage.setItem("ct-theme", theme);
        localStorage.setItem("landing-waves-paused", "true");
      }, theme);
      await page.goto("/");
      await countryButton(page, "Thailand").click();
      await page
        .getByRole("complementary")
        .locator(".plant-preview__plant-picker")
        .getByRole("button", { name: "FTM" })
        .click();
      await expect(page.locator(".factory-stage canvas")).toBeVisible();
      await expect(page.getByRole("button", { name: "Highlight Wave Scan area" })).toBeVisible();
      await page.waitForTimeout(900);
      await page.screenshot({
        path: `test-results/screenshots/LANDING-map-${theme}-${width}.png`,
        fullPage: true,
      });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      expect(errors).toEqual([]);
    });
  }
}
