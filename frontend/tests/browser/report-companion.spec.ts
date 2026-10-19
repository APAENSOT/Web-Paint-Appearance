import { expect, test, type Page } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { filmData, report, wsData } from "../ar03-fixtures";

async function openReport(page: Page) {
  await mockHistory(page, "viewer");
  await page.route("**/api/v1/plants/*/analysis/report**", (r) => r.fulfill({ json: report }));
  await page.route("**/api/v1/plants/*/wavescan/overview**", (r) => r.fulfill({ json: wsData }));
  await page.route("**/api/v1/plants/*/filmthickness/overview**", (r) =>
    r.fulfill({ json: filmData }),
  );
  await page.goto("/plant/FTM");
  if ((page.viewportSize()?.width ?? 1440) < 1024)
    await page.getByRole("button", { name: "Views & filters" }).click();
  await page.getByRole("button", { name: "Analysis & Report", exact: true }).click();
  await expect(page.getByTestId("analysis-workspace")).toBeVisible();
  await expect(page.locator(".report-companion")).toHaveAttribute("data-renderer", "3d");
  await expect
    .poll(() =>
      page
        .locator(".report-companion__base")
        .evaluate((img) => (img as HTMLImageElement).naturalWidth),
    )
    .toBeGreaterThan(0);
}

async function sample(page: Page, top: number, height: number) {
  const box = (await page.locator(".report-companion__scene canvas").boundingBox())!;
  // Sample the character, excluding the circuit ring and its hover/focus colours.
  if (top === 0 && height === 1) {
    top = 0.15;
    height = 0.7;
  }
  return (
    await page.screenshot({
      clip: {
        x: box.x + box.width * 0.3,
        y: box.y + box.height * top,
        width: box.width * 0.4,
        height: box.height * height,
      },
      scale: "css",
    })
  ).toString("base64");
}
async function settled(page: Page) {
  let previous = "";
  await expect
    .poll(async () => {
      const current = await sample(page, 0, 1);
      const same = current === previous;
      previous = current;
      return same;
    })
    .toBe(true);
}

test("3D head and eyes follow independently while the torso stays fixed", async ({
  page,
}, info) => {
  const writes: string[] = [];
  const shaderErrors: string[] = [];
  page.on("console", (message) => {
    if (/THREE.WebGLProgram|VALIDATE_STATUS|shader error/i.test(message.text()))
      shaderErrors.push(message.text());
  });
  page.on("request", (r) => {
    if (r.url().includes("/api/") && !["GET", "OPTIONS", "HEAD"].includes(r.method()))
      writes.push(r.method());
  });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await openReport(page);
  const guide = page.getByRole("button", { name: "Greet the report guide" });
  const box = (await guide.boundingBox())!;
  const centerX = box.x + box.width / 2,
    centerY = box.y + box.height / 2;
  await page.mouse.move(centerX - 320, centerY);
  await settled(page);
  await page
    .locator(".report-companion")
    .screenshot({ path: info.outputPath("guide-look-left.png") });
  const left = await sample(page, 0, 0.8),
    body = await sample(page, 0.9, 0.1);
  await page.mouse.move(centerX + 320, centerY);
  await settled(page);
  expect(await sample(page, 0, 0.8)).not.toBe(left);
  expect(await sample(page, 0.9, 0.1)).toBe(body);
  await page
    .locator(".report-companion")
    .screenshot({ path: info.outputPath("guide-look-right.png") });
  // Head rotation is bounded before eye travel: gaze can continue without moving hair/body.
  const hair = await sample(page, 0.08, 0.23),
    eyes = await sample(page, 0.43, 0.24);
  await page.mouse.move(centerX + 320 * 0.72, centerY);
  await settled(page);
  expect(await sample(page, 0.08, 0.23)).toBe(hair);
  expect(await sample(page, 0.43, 0.24)).not.toBe(eyes);
  await guide.click();
  await expect(guide).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".report-companion__message")).toBeVisible();
  await settled(page);
  await page.screenshot({ path: info.outputPath("report-character-desktop.png") });
  await page.keyboard.press("Escape");
  await expect(page.locator(".report-companion__message")).toBeHidden();
  await page.getByRole("button", { name: "Pause character animation" }).click();
  await settled(page);
  const paused = await sample(page, 0, 1);
  await page.mouse.move(centerX - 320, centerY - 100);
  await settled(page);
  expect(await sample(page, 0, 1)).toBe(paused);
  await page.getByRole("button", { name: "Play character animation" }).click();
  await page.mouse.move(centerX + 320, centerY);
  await settled(page);
  expect(await sample(page, 0, 1)).not.toBe(paused);
  await page.evaluate(() =>
    window.dispatchEvent(new PointerEvent("pointerout", { relatedTarget: null })),
  );
  await settled(page);
  expect(await sample(page, 0, 1)).toBe(paused);
  expect(shaderErrors).toEqual([]);
  await expect(page.getByTestId("analysis-export")).toBeEnabled();
  expect(writes).toEqual([]);
});

test("reduced motion and keyboard greetings keep the 3D character still", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openReport(page);
  await settled(page);
  const still = await sample(page, 0, 1);
  await page.mouse.move(1100, 500);
  const guide = page.getByRole("button", { name: "Greet the report guide" });
  await guide.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".report-companion__message")).toBeVisible();
  await settled(page);
  expect(await sample(page, 0, 1)).toBe(still);
  await page.keyboard.press("Tab");
  await expect(page.locator(".report-companion__message")).toBeHidden();
});

test("lost WebGL context restores the static portrait", async ({ page }) => {
  await openReport(page);
  await page.locator(".report-companion__scene canvas").dispatchEvent("webglcontextlost");
  await expect(page.locator(".report-companion")).toHaveAttribute("data-renderer", "fallback");
  await expect(page.locator(".report-companion__base")).toBeVisible();
  await page.getByRole("button", { name: "Greet the report guide" }).click();
  await expect(page.locator(".report-companion__message")).toBeVisible();
});

test("character and greeting fit on a phone", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 1000 });
  await openReport(page);
  await page.getByRole("button", { name: "Greet the report guide" }).click();
  const bubble = (await page.locator(".report-companion__message").boundingBox())!;
  expect(bubble.x).toBeGreaterThanOrEqual(0);
  expect(bubble.x + bubble.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("report-character-phone.png") });
});
