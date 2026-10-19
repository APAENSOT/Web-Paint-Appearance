import { expect, test } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { interactionsFixture } from "../film-overview-interactions-fixtures";

const names = ["E-coat", "Primer", "Base", "Clear"];
for (const width of [390, 768, 1440])
  for (const theme of ["light", "dark"])
    for (const reduced of [false, true]) {
      test(`T71 shared stack ${width} ${theme} ${reduced ? "reduced" : "normal"} motion`, async ({
        page,
      }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.emulateMedia({ reducedMotion: reduced ? "reduce" : "no-preference" });
        await mockHistory(page);
        let reads = 0;
        await page.route("**/api/v1/**", (route) =>
          route.request().method() === "GET" ? route.fallback() : route.abort(),
        );
        await page.route("**/filmthickness/overview**", (route) => {
          reads++;
          return route.fulfill({ json: interactionsFixture });
        });
        await page.goto("/plant/AAT?paint=film&filmMonth=2026-09");
        await expect(page.locator("[data-film-box]")).toHaveCount(8);
        await page.evaluate(
          (t) => document.documentElement.classList.toggle("dark", t === "dark"),
          theme,
        );
        const stack = page.getByRole("tablist", { name: "Coating layers" });
        await expect(stack.locator("svg")).toHaveCount(1);
        await expect(stack.locator("[data-coating-plane]")).toHaveCount(4);
        await expect(stack.getByRole("tab")).toHaveText(names);
        await expect(page.getByRole("button", { name: "All colours", exact: true })).toHaveCount(0);
        const before = reads;
        await stack.scrollIntoViewIfNeeded();
        await page.getByRole("tabpanel").evaluate(async (el) => {
          await Promise.all(el.getAnimations().map((a) => a.finished));
        });
        const bounds = await stack.boundingBox();
        const headingGap =
          (await page.locator(".film-selected-layer").boundingBox())!.y - bounds!.y;
        for (const [index, name] of names.entries()) {
          const tab = stack.getByRole("tab", { name, exact: true });
          const target = (await tab.boundingBox())!;
          expect(target.height).toBeGreaterThanOrEqual(44);
          // The visible plane and label both belong to the same generous target.
          await tab.click({ position: { x: target.width * 0.28, y: target.height / 2 } });
          await expect(tab).toHaveAttribute("aria-selected", "true");
          await expect(page.locator(".film-selected-layer")).toHaveText(name);
          await stack
            .getByRole("tab")
            .nth((index + 1) % 4)
            .click();
          await tab.locator("span").click();
          await expect(tab).toHaveAttribute("aria-selected", "true");
          await page.getByRole("tabpanel").evaluate(async (el) => {
            await Promise.all(el.getAnimations().map((a) => a.finished));
          });
          const plane = (await stack.locator("[data-coating-plane]").nth(index).boundingBox())!;
          const hit = (await tab.boundingBox())!;
          expect(plane.y).toBeGreaterThanOrEqual(hit.y);
          expect(plane.y + plane.height).toBeLessThanOrEqual(hit.y + hit.height);
          expect(plane.x).toBeGreaterThanOrEqual(hit.x);
          expect(plane.x + plane.width).toBeLessThanOrEqual(hit.x + hit.width);
          const current = (await stack.boundingBox())!;
          expect(current.width).toBeCloseTo(bounds!.width, 1);
          expect(current.height).toBeCloseTo(bounds!.height, 1);
          expect(
            (await page.locator(".film-selected-layer").boundingBox())!.y - current.y,
          ).toBeCloseTo(headingGap, 1);
          await expect(page.getByRole("tabpanel")).toHaveCount(1);
          await expect(stack.locator("[data-selected='true']")).toHaveCount(1);
          await expect(stack.locator("svg")).toHaveAttribute("aria-hidden", "true");
        }
        await expect(stack.locator('[role="tab"][tabindex="0"]')).toHaveCount(1);
        const ecoat = stack.getByRole("tab", { name: "E-coat", exact: true });
        await ecoat.focus();
        await ecoat.press("ArrowRight");
        await expect(stack.getByRole("tab", { name: "Primer", exact: true })).toBeFocused();
        await stack.getByRole("tab", { name: "Primer", exact: true }).press("End");
        await expect(stack.getByRole("tab", { name: "Clear", exact: true })).toHaveAttribute(
          "aria-selected",
          "true",
        );
        await stack.getByRole("tab", { name: "Clear", exact: true }).press("Home");
        await expect(ecoat).toBeFocused();
        await expect(ecoat).toHaveAttribute("aria-selected", "true");
        expect(await ecoat.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
        const h = page.getByRole("region", { name: "U704 Horizontal", exact: true });
        const v = page.getByRole("region", { name: "U704 Vertical", exact: true });
        const opener = h.getByRole("button", {
          name: "Absolute / Shadow Black; Horizontal summary",
          exact: true,
        });
        await opener.click();
        const detail = h.getByRole("region", { name: "Box detail" });
        await expect(detail).toBeVisible();
        await expect(detail.locator("summary").last()).toHaveText("Detailed measurements");
        const motion = await page.getByRole("tabpanel").evaluate((el) => ({
          content: getComputedStyle(el).animationName,
          summary: getComputedStyle(el.querySelector(".film-detail")!).animationName,
          plane: getComputedStyle(
            document.querySelector("[data-coating-plane][data-selected='true']")!,
          ).transform,
          duration: getComputedStyle(document.querySelector("[data-coating-plane]")!)
            .transitionDuration,
          dataAnimated: [...el.querySelectorAll(".recharts-wrapper *")].some(
            (node) => getComputedStyle(node).animationName !== "none",
          ),
        }));
        expect(motion.content).toBe(reduced ? "none" : "film-content-enter");
        expect(motion.summary).toBe(reduced ? "none" : "film-summary-enter");
        expect(motion.plane === "none").toBe(reduced);
        expect(motion.duration).toBe(reduced ? "0s" : "0.15s, 0.15s");
        expect(motion.dataAnimated).toBe(false);
        await detail.evaluate(async (el) => {
          await Promise.all(el.getAnimations().map((a) => a.finished));
        });
        const entrances = await detail.evaluate((el) => ({
          summary: el.getAnimations().map((a) => a.startTime),
          content: el
            .closest("[role='tabpanel']")!
            .getAnimations()
            .map((a) => a.startTime),
        }));
        await detail.locator("summary").last().click();
        await detail.hover();
        expect(
          await detail.evaluate((el) => ({
            summary: el.getAnimations().map((a) => a.startTime),
            content: el
              .closest("[role='tabpanel']")!
              .getAnimations()
              .map((a) => a.startTime),
          })),
        ).toEqual(entrances);
        await v.locator("[data-film-box]").first().click();
        await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(2);
        await detail.getByRole("button", { name: "Close detail" }).click();
        await expect(opener).toBeFocused();
        await expect(h.getByRole("region", { name: "Box detail" })).toHaveCount(0);
        await v.locator("[data-film-box]").first().press("Escape");
        await expect(page.getByRole("region", { name: "Box detail" })).toHaveCount(0);
        // Interrupted selections use React state immediately, never transition-end queues.
        for (const index of [3, 1, 2, 0, 3]) {
          await stack.getByRole("tab").nth(index).dispatchEvent("mousedown", { button: 0 });
        }
        await expect(page.locator(".film-selected-layer")).toHaveText("Clear");
        await expect(page.getByRole("tabpanel")).toHaveCount(1);
        await expect(page.locator("[data-film-box]")).toHaveCount(
          interactionsFixture.boxes.filter((b) => b.layer_code === "CLEAR").length,
        );
        expect(reads).toBe(before);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
        // Finish the short entrance before capturing the normal-motion settled state.
        await page.getByRole("tabpanel").evaluate(async (el) => {
          await Promise.all(el.getAnimations().map((animation) => animation.finished));
        });
        await page.screenshot({
          path: `test-results/evidence/T71/stack-${width}-${theme}-${reduced ? "reduced" : "normal"}.png`,
          fullPage: true,
        });
      });
    }

for (const state of ["loading", "error", "empty"])
  test(`T71 latest selection through ${state} and same-scope refetch`, async ({ page }) => {
    await mockHistory(page);
    await page.route("**/api/v1/**", (route) =>
      route.request().method() === "GET" ? route.fallback() : route.abort(),
    );
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let failed = state === "error";
    let empty = state === "empty";
    let reads = 0;
    await page.route("**/filmthickness/overview**", async (route) => {
      reads++;
      if (state === "loading") await gate;
      if (failed)
        return route.fulfill({
          status: 503,
          json: {
            statusCode: 503,
            error: "Read refused",
            message: "T71 fixture unavailable",
            correlationId: "t71-fixture",
          },
        });
      return route.fulfill({
        json: { ...interactionsFixture, boxes: empty ? [] : interactionsFixture.boxes },
      });
    });
    await page.goto("/plant/AAT?paint=film&filmMonth=2026-09");
    if (state === "loading")
      await expect(page.getByText("Loading Film Thickness overview...")).toBeVisible();
    if (state === "error")
      await expect(page.getByRole("alert")).toContainText("T71 fixture unavailable");
    if (state === "empty")
      await expect(
        page.getByText("No active Film Thickness readings for this selection."),
      ).toBeVisible();
    await page.getByRole("tab", { name: "Base", exact: true }).click();
    await page.getByRole("tab", { name: "Clear", exact: true }).click();
    await expect(page.locator(".film-selected-layer")).toHaveText("Clear");
    await expect(page.locator("[data-film-box]")).toHaveCount(0);
    failed = false;
    empty = false;
    release();
    if (state === "error") await page.getByRole("button", { name: "Retry", exact: true }).click();
    if (state === "empty")
      await page.evaluate(() => {
        window.dispatchEvent(new Event("offline"));
        window.dispatchEvent(new Event("online"));
      });
    await expect(page.locator("[data-film-box]")).toHaveCount(
      interactionsFixture.boxes.filter((b) => b.layer_code === "CLEAR").length,
    );
    await expect(page.getByRole("tab", { name: "Clear", exact: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.locator(".film-selected-layer")).toHaveText("Clear");
    await page.getByRole("tab", { name: "Primer", exact: true }).click();
    await expect(page.getByText("No readings for this layer.")).toBeVisible();
    const before = reads;
    await page.getByRole("tab", { name: "Clear", exact: true }).click();
    expect(reads).toBe(before);
  });
