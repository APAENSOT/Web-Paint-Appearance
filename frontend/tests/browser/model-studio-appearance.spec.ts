import { expect, test } from "@playwright/test";

test("Model Detail saves a canonical colour and reads it again after reload", async ({
  page,
  request,
}, testInfo) => {
  const endpoint = "http://127.0.0.1:8012/api/v1/plants/FTM/color-appearances";
  const response = await request.get(endpoint);
  expect(response.ok()).toBeTruthy();
  const catalogue = await response.json();
  const name: string = catalogue.items[0].color_name;
  let saved = false;
  let writes = 0;

  await page.route(endpoint, async (route) => {
    const items = catalogue.items.map((item: { color_name: string }) =>
      item.color_name === name
        ? saved
          ? {
              ...item,
              appearance: {
                hex: "#123456",
                revision: 1,
                saved_at: "2026-10-12T00:00:00Z",
                saved_by: "Test Engineer",
                inherited_from: null,
              },
            }
          : { ...item, appearance: null }
        : item,
    );
    await route.fulfill({ json: { ...catalogue, items } });
  });
  await page.route(`${endpoint}/**`, async (route) => {
    writes += 1;
    const body = route.request().postDataJSON();
    expect(body).toEqual({ hex: "#123456", expected_revision: null });
    expect(route.request().url()).toContain(encodeURIComponent(name));
    saved = true;
    await route.fulfill({
      json: {
        color_name: name,
        hex: "#123456",
        revision: 1,
        saved_at: "2026-10-12T00:00:00Z",
        saved_by: "Test Engineer",
        replayed: false,
      },
    });
  });

  await page.goto("/plant/FTM");
  await page.getByRole("button", { name: "Model Detail" }).click();
  const edit = page.getByRole("button", { name: `Edit appearance for ${name}` });
  await expect(edit).toBeVisible();
  await edit.click();
  await page.getByRole("textbox", { name: "HEX" }).fill("#123456");
  await page.getByRole("button", { name: "Save appearance" }).click();
  await expect(edit.locator(".studio-swatch")).toHaveCSS("background-color", "rgb(18, 52, 86)");
  await page.screenshot({
    path: testInfo.outputPath("model-studio-desktop-dark.png"),
    fullPage: true,
  });
  expect(writes).toBe(1);
  await page.reload();
  await page.getByRole("button", { name: "Model Detail" }).click();
  await page.getByRole("button", { name: `Edit appearance for ${name}` }).click();
  await expect(page.getByRole("textbox", { name: "HEX" })).toHaveValue("#123456");
  await expect(page.getByText("Saved appearance", { exact: true }).first()).toBeVisible();
});

test("a revision conflict keeps the draft until the editor reloads the saved profile", async ({
  page,
  request,
}) => {
  const endpoint = "http://127.0.0.1:8012/api/v1/plants/FTM/color-appearances";
  const response = await request.get(endpoint);
  expect(response.ok()).toBeTruthy();
  const catalogue = await response.json();
  const name: string = catalogue.items[0].color_name;
  let conflict = false;
  await page.route(endpoint, async (route) => {
    await route.fulfill({
      json: {
        ...catalogue,
        items: catalogue.items.map((item: { color_name: string }) =>
          item.color_name === name && conflict
            ? {
                ...item,
                appearance: {
                  hex: "#AABBCC",
                  revision: 1,
                  saved_at: "2026-10-12T00:00:00Z",
                  saved_by: "Other Engineer",
                  inherited_from: null,
                },
              }
            : item,
        ),
      },
    });
  });
  await page.route(`${endpoint}/**`, async (route) => {
    conflict = true;
    await route.fulfill({
      status: 409,
      json: {
        statusCode: 409,
        error: "Conflict",
        message: "Current revision 1 (#AABBCC)",
        correlationId: "browser-fixture",
      },
    });
  });
  await page.goto("/plant/FTM");
  await page.getByRole("button", { name: "Model Detail" }).click();
  await page.getByRole("button", { name: `Edit appearance for ${name}` }).click();
  const hex = page.getByRole("textbox", { name: "HEX" });
  await hex.fill("#123456");
  await page.getByRole("button", { name: "Save appearance" }).click();
  await expect(page.getByText("Current revision 1 (#AABBCC)")).toBeVisible();
  await expect(hex).toHaveValue("#123456");
  await page.getByRole("button", { name: "Reload saved appearance" }).click();
  await expect(hex).toHaveValue("#AABBCC");
});

test("a Viewer can preview on a phone but cannot save an appearance", async ({
  page,
  request,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem("ct-theme", "light"));
  const response = await request.get("http://127.0.0.1:8012/api/v1/auth/me");
  expect(response.ok()).toBeTruthy();
  const identity = await response.json();
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: { ...identity, principal: { ...identity.principal, roles: ["viewer"] } },
    }),
  );
  await page.goto("/plant/FTM");
  await page.getByRole("button", { name: "Views & filters" }).click();
  await page.getByRole("button", { name: "Model Detail" }).click();
  await page.locator(".studio-edit-swatch").first().click();
  await page.getByRole("textbox", { name: "HEX" }).fill("#123456");
  await expect(page.getByRole("button", { name: "Save appearance" })).toBeDisabled();
  await expect(
    page.getByText("An Engineer or Admin can save appearances.", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("model-editor-mobile-light.png"),
    fullPage: true,
  });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});

test("dirty colour drafts are guarded when leaving Model Detail", async ({ page }) => {
  await page.goto("/plant/FTM");
  await page.getByRole("button", { name: "Model Detail" }).click();
  await page.locator(".studio-edit-swatch").first().click();
  await page.getByRole("textbox", { name: "HEX" }).fill("#123456");
  await page.getByRole("link", { name: "Back to tracking home" }).click();
  const guard = page.getByRole("alertdialog", { name: "Unsaved colour changes" });
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "Keep editing" }).click();
  await expect(page.getByRole("textbox", { name: "HEX" })).toHaveValue("#123456");
  await page.getByRole("link", { name: "Back to tracking home" }).click();
  await guard.getByRole("button", { name: "Discard and leave" }).click();
  await expect(page).toHaveURL("http://localhost:5173/");
});
