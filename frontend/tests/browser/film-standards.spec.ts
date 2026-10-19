import { expect, test, type Page } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { catalogueFixture } from "../fixtures";
import { filmStandardsFixture, rule } from "../film-standards-fixtures";
import type { FilmStandardPublishIn } from "../../src/features/filmthickness/film-standards";
const evidence = "test-results/evidence/T64";
async function setup(page: Page, role = "admin") {
  await mockHistory(page, role);
  await page.route("**/api/v1/standards/catalogue", (r) => r.fulfill({ json: catalogueFixture }));
  // T100 mounted a Points panel beside the standards; this file is about the
  // standards, so the panel is given an empty model list and draws nothing.
  await page.route("**/api/v1/plants/*/film-points", (r) =>
    r.fulfill({ json: { plant_code: "FTM", items: [] } }),
  );
  const reads: string[] = [];
  await page.route("**/api/v1/plants/*/filmthickness/standards", (r) => {
    reads.push(r.request().url());
    return r.fulfill({
      json: {
        ...filmStandardsFixture,
        rules: [
          ...filmStandardsFixture.rules,
          { layer_code: "BASE", color_name: null, h: rule(20, 25), v: rule(20, 25) },
        ],
      },
    });
  });
  // Every fixture test intercepts POST, so publication cannot reach the standing API.
  const posts: FilmStandardPublishIn[] = [];
  await page.route("**/api/v1/filmthickness/standards", (r) => {
    posts.push(r.request().postDataJSON());
    return r.fulfill({
      status: 201,
      json: {
        plant_code: "FTM",
        layer_code: "BASE",
        color_name: "Amber",
        audit_id: 1,
        created_at: "2026-10-06T03:00:00Z",
      },
    });
  });
  return { reads, posts };
}
test("Admin navigation, reload/back, separate family/model and responsive provenance", async ({
  page,
}) => {
  const { reads } = await setup(page);
  await page.goto("/plant/FTM?standardView=film");
  await expect(page.getByRole("heading", { name: "Film Thickness", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  const sources = page.getByRole("dialog", { name: "Sources", exact: true });
  await sources
    .getByRole("combobox", { name: "Rule", exact: true })
    .selectOption(JSON.stringify("Blue"));
  await expect(sources).toContainText("Own horizontal");
  await expect(sources).toContainText("Plant-wide source (Inherited)");
  await expect(sources).toContainText("Asia/Bangkok");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("article", { name: "ECOAT Plant-wide" })).toContainText("0 µm");
  await page.getByText("Not offered · Base", { exact: true }).click();
  await expect(page.getByRole("article", { name: "BASE Retired" }).getByRole("button")).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Model Detail", exact: true }).click();
  await page.getByRole("button", { name: "Model", exact: true }).click();
  await expect(page).toHaveURL(/modelView=model/);
  await expect(page.getByRole("heading", { name: "Film Thickness", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Standard", exact: true }).click();
  await expect(page).toHaveURL(/standardView=family/);
  await page.goBack();
  await expect(page).toHaveURL(/modelView=model/);
  await page.goBack();
  await expect(page).toHaveURL(/modelView=colours/);
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Film Thickness", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Film Thickness", exact: true })).toBeVisible();
  expect(reads.length).toBeGreaterThan(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${evidence}/fixture-mobile.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
// T100-FIX2 CHANGE (D-100-9): the Film **entry** is now shown to anyone who
// can upload, because the Points panel behind it is theirs (D-99-4). The
// denial half of this claim is unchanged for both roles -- neither may read
// or publish a standard -- and a Viewer's entry stays hidden.
for (const [role, entries] of [
  ["viewer", 0],
  ["engineer", 1],
] as const)
  test(`${role} entry and direct denial without Film requests`, async ({ page }) => {
    const { reads, posts } = await setup(page, role);
    await page.goto("/plant/FTM?standardView=film");
    await expect(page.getByRole("heading", { name: "Admin access required" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Film Thickness", exact: true })).toHaveCount(
      entries,
    );
    expect(reads).toEqual([]);
    expect(posts).toEqual([]);
  });
test("identity pending/error do not request standards", async ({ page }) => {
  const { reads, posts } = await setup(page);
  let release!: () => void;
  const hold = new Promise<void>((r) => (release = r));
  await page.route("**/api/v1/auth/me", async (r) => {
    await hold;
    await r.fulfill({
      status: 403,
      json: {
        statusCode: 403,
        error: "Forbidden",
        message: "Identity unavailable",
        correlationId: "identity-test",
      },
    });
  });
  await page.goto("/plant/FTM?standardView=film");
  await expect(page.getByText("Loading API identity...")).toBeVisible();
  expect(reads).toEqual([]);
  release();
  await expect(page.getByText("Correlation ID: identity-test")).toBeVisible();
  expect(reads).toEqual([]);
  expect(posts).toEqual([]);
});
test("edit/review draft, toggle, limits, exact POST, pending lock and failed refresh", async ({
  page,
}) => {
  const { posts } = await setup(page);
  await page.goto("/plant/FTM?standardView=film");
  const row = page.getByRole("row", { name: "BASE Amber", exact: true });
  const opener = row.getByRole("button", { name: "Set standard" });
  await opener.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Same for Horizontal and Vertical")).toBeChecked();
  await expect(dialog.getByLabel("Source note (required, maximum 500 characters)")).toHaveValue("");
  await dialog.getByRole("button", { name: "Review publish", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Source note is required");
  await dialog.locator("#h-lo").fill("1e2");
  await dialog.locator("#note").fill("Fixture publish");
  await dialog.getByRole("button", { name: "Review publish", exact: true }).click();
  await expect(dialog.locator("#h-lo-error")).toBeVisible();
  await dialog.locator("#h-lo").fill("0");
  await dialog.getByLabel("Same for Horizontal and Vertical").uncheck();
  await expect(dialog.locator("#v-lo")).toHaveValue("0");
  await dialog.locator("#v-lo").fill("12.25");
  await dialog.getByLabel("Same for Horizontal and Vertical").check();
  await dialog.getByRole("button", { name: "Review publish", exact: true }).click();
  await expect(dialog.getByRole("region", { name: "Proposed values" })).toContainText("0 µm");
  await expect(dialog).toContainText("Horizontal changes from inheritance");
  await page.screenshot({ path: `${evidence}/fixture-review.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(async () => {
      const b = await dialog.boundingBox();
      return Boolean(b && b.y >= 0 && b.height <= 760);
    })
    .toBe(true);
  await dialog.evaluate((e) => {
    e.scrollTop = 0;
  });
  await page.screenshot({ path: `${evidence}/fixture-mobile-review.png` });
  await dialog.getByRole("button", { name: "Publish new version" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${evidence}/fixture-mobile-review-actions.png` });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await dialog.getByRole("button", { name: "Back to edit" }).click();
  await expect(dialog.locator("#note")).toHaveValue("Fixture publish");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(opener).toBeFocused();
  await opener.click();
  await expect(dialog.locator("#note")).toHaveValue("");
  await dialog.locator("#note").fill("Fixture publish");
  await dialog.getByRole("button", { name: "Review publish", exact: true }).click();
  let release!: () => void;
  const hold = new Promise<void>((r) => (release = r));
  await page.route("**/api/v1/filmthickness/standards", async (r) => {
    posts.push(r.request().postDataJSON());
    await hold;
    await r.fulfill({
      status: 201,
      json: {
        plant_code: "FTM",
        layer_code: "BASE",
        color_name: "Amber",
        audit_id: 1,
        created_at: "2026-10-06T03:00:00Z",
      },
    });
  });
  const otherReads: string[] = [];
  page.on("request", (r) => {
    if (!r.url().includes("filmthickness/standards")) otherReads.push(r.url());
  });
  await dialog.getByRole("button", { name: "Publish new version" }).click();
  await expect(dialog.getByRole("button", { name: "Publishing..." })).toBeDisabled();
  await page.keyboard.press("Escape");
  await page.mouse.click(1, 1);
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Back to edit" })).toBeDisabled();
  await page.route("**/api/v1/plants/*/filmthickness/standards", (r) =>
    r.fulfill({
      status: 503,
      json: {
        statusCode: 503,
        error: "Unavailable",
        message: "Refresh failed",
        correlationId: "refresh-test",
      },
    }),
  );
  release();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("New standard version published")).toBeVisible();
  await expect(page.getByText("Correlation ID: refresh-test")).toBeVisible();
  expect(posts).toEqual([
    {
      plant_code: "FTM",
      layer_code: "BASE",
      color_name: "Amber",
      h: { lo: 20, hi: 25, target: null },
      v: { lo: 20, hi: 25, target: null },
      source_note: "Fixture publish",
    },
  ]);
  expect(otherReads).toEqual([]);
});
for (const status of [403, 404, 422])
  test(`${status} preserves review and draft with correlation`, async ({ page }) => {
    const { posts } = await setup(page);
    await page.route("**/api/v1/filmthickness/standards", (r) => {
      posts.push(r.request().postDataJSON());
      return r.fulfill({
        status,
        json: {
          statusCode: status,
          error: "Refused",
          message: "Colour no longer offered",
          correlationId: `film-${status}`,
        },
      });
    });
    await page.goto("/plant/FTM?standardView=film");
    await page
      .getByRole("article", { name: "PRIMER Plant-wide" })
      .getByRole("button", { name: "Adjust standard" })
      .click();
    const d = page.getByRole("dialog");
    await d.locator("#note").fill("Keep draft");
    await d.getByRole("button", { name: "Review publish", exact: true }).click();
    await expect(d).toContainText("Colour-specific overrides keep precedence");
    await d.getByRole("button", { name: "Publish new version" }).click();
    await expect(d).toContainText(`Correlation ID: film-${status}`);
    await expect(d).toContainText("Keep draft");
    await d.getByRole("button", { name: "Back to edit" }).click();
    await expect(d.locator("#note")).toHaveValue("Keep draft");
    expect(posts).toHaveLength(1);
  });
test("empty offered colours and absent rules keep plant creation", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/plants/*/filmthickness/standards", (r) =>
    r.fulfill({ json: { plant_code: "FTM", rules: [], colors: [] } }),
  );
  await page.goto("/plant/FTM?standardView=film");
  await expect(
    page.getByRole("region", { name: "Shared standards", exact: true }).getByRole("article"),
  ).toHaveCount(3);
  await expect(page.getByText("No offered colours for this plant")).toHaveCount(1);
  await page
    .getByRole("article", { name: "CLEAR Plant-wide" })
    .getByRole("button", { name: "Set standard" })
    .click();
  await expect(page.getByLabel("Same for Horizontal and Vertical")).not.toBeChecked();
});
test("live read-only FTM and AAT screenshots with source", async ({ page }) => {
  await page.route("**/api/v1/**", (r) =>
    r.request().method() === "GET" ? r.continue() : r.abort(),
  );
  for (const code of ["FTM", "AAT"]) {
    await page.goto(`/plant/${code}?standardView=film`);
    await expect(page.getByRole("heading", { name: "Film Thickness", exact: true })).toBeVisible();
    const row = page.getByRole("article", { name: "ECOAT Plant-wide" });
    await expect(row.getByRole("button", { name: "Adjust standard" })).toBeVisible();
    await page.getByRole("button", { name: "Sources", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Sources", exact: true })).toContainText(
      "Asia/Bangkok",
    );
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `${evidence}/live-${code.toLowerCase()}-viewport.png` });
    await page.screenshot({
      path: `${evidence}/live-${code.toLowerCase()}-desktop.png`,
      fullPage: true,
    });
  }
});

test("mixed inherited draft, source limits and trimmed optional document on successful refetch", async ({
  page,
}) => {
  const { reads, posts } = await setup(page);
  await page.goto("/plant/FTM?standardView=film");
  const row = page.getByRole("article", { name: "ECOAT Blue" });
  const sourceTrigger = page.getByRole("button", { name: "Sources", exact: true });
  await sourceTrigger.focus();
  await page.keyboard.press("Enter");
  await page
    .getByRole("combobox", { name: "Rule", exact: true })
    .selectOption(JSON.stringify("Blue"));
  await expect(page.getByRole("dialog", { name: "Sources", exact: true })).toContainText(
    "Own horizontal",
  );
  await page.keyboard.press("Escape");
  await page
    .getByRole("region", { name: "Shared standards", exact: true })
    .getByText("Existing exceptions", { exact: true })
    .click();
  const opener = row.getByRole("button", { name: "Adjust standard" });
  await opener.focus();
  await page.keyboard.press("Enter");
  const d = page.getByRole("dialog");
  await expect(d.locator("#h-lo")).toHaveValue("12");
  await expect(d.locator("#v-lo")).toHaveValue("18");
  await expect(d.getByLabel("Same for Horizontal and Vertical")).not.toBeChecked();
  await expect(d.locator("#document")).toHaveValue("");
  await d.locator("#note").fill(" ");
  await d.getByRole("button", { name: "Review publish", exact: true }).click();
  await expect(d.locator("#note-error")).toBeVisible();
  await d.locator("#note").fill("x".repeat(501));
  await d.locator("#document").fill("x".repeat(129));
  await d.getByRole("button", { name: "Review publish", exact: true }).click();
  await expect(d.locator("#note-error")).toBeVisible();
  await expect(d.locator("#document-error")).toBeVisible();
  await d.locator("#note").fill("  New source  ");
  await d.locator("#document").fill("  DOC-1  ");
  await d.locator("#h-lo").fill("");
  await d.locator("#h-hi").fill("500");
  await d.getByRole("button", { name: "Review publish", exact: true }).click();
  await expect(d).toContainText("Vertical changes from inheritance");
  await expect(d.getByRole("region", { name: "Proposed values" })).toContainText("500 µm");
  const before = reads.length;
  await page.route("**/api/v1/plants/*/filmthickness/standards", (r) => {
    reads.push(r.request().url());
    return r.fulfill({
      json: {
        ...filmStandardsFixture,
        rules: filmStandardsFixture.rules.map((ruleRow) =>
          ruleRow.color_name === "Blue"
            ? {
                ...ruleRow,
                h: rule(null, 500, null, "New source"),
                v: rule(18, null, null, "New source"),
              }
            : ruleRow,
        ),
      },
    });
  });
  await d.getByRole("button", { name: "Publish new version" }).click();
  await expect(d).toHaveCount(0);
  await expect(row).toContainText("500 µm");
  await expect(page.getByText("New standard version published")).toBeVisible();
  expect(reads).toHaveLength(before + 1);
  expect(posts).toEqual([
    {
      plant_code: "FTM",
      layer_code: "ECOAT",
      color_name: "Blue",
      h: { lo: null, hi: 500, target: null },
      v: { lo: 18, hi: null, target: null },
      source_note: "New source",
      source_document: "DOC-1",
    },
  ]);
});
for (const code of ["FTM", "FVL", "SAP", "AAT"])
  test(`${code} typed seed shapes, layer separation and no family fallback`, async ({ page }) => {
    await setup(page);
    const flat = code === "FTM",
      aat = code === "AAT";
    await page.route("**/api/v1/plants/*/filmthickness/standards", (r) =>
      r.fulfill({
        json: {
          plant_code: code,
          colors: [
            { color_name: "Arctic White", family_name: "Same family" },
            { color_name: "Seismic Tan", family_name: "Same family" },
          ],
          rules: [
            {
              layer_code: "ECOAT",
              color_name: null,
              h: rule(aat ? 15 : 18, aat ? 25 : null),
              v: rule(aat ? 15 : 18, aat ? 25 : null),
            },
            {
              layer_code: "PRIMER",
              color_name: aat ? "Arctic White" : null,
              h: rule(aat ? 24 : flat ? 20 : 23, aat ? 26 : flat ? 25 : 31),
              v: rule(aat ? 24 : flat ? 20 : 18, aat ? 26 : 25),
            },
            {
              layer_code: "BASE",
              color_name: "Arctic White",
              h: rule(aat ? 11 : 25, aat ? 13 : 30),
              v: rule(aat ? 11 : 25, aat ? 13 : 30),
            },
            {
              layer_code: "CLEAR",
              color_name: null,
              // T67: Clear has no Maximum at any plant; AAT's 35 is its Minimum requirement.
              h: rule(aat ? 30 : 36, null, aat ? 35 : 46),
              v: rule(30, null, aat ? 35 : 46),
            },
          ],
        } satisfies import("../../src/features/filmthickness/film-standards").FilmStandardsOut,
      }),
    );
    await page.goto(`/plant/${code}?standardView=film`);
    const primer = aat
      ? page.getByRole("row", { name: "PRIMER Arctic White", exact: true })
      : page.getByRole("article", { name: "PRIMER Plant-wide" });
    const base = page.getByRole("row", { name: "BASE Arctic White", exact: true });
    await expect(primer).toContainText(aat ? "24 µm" : flat ? "20 µm" : "23 µm");
    await expect(primer).toContainText(aat ? "26 µm" : "25 µm");
    await expect(base).toContainText(aat ? "11 µm" : "25 µm");
    await expect(page.getByRole("row", { name: "BASE Seismic Tan", exact: true })).toContainText(
      "No standard",
    );
    if (aat)
      await expect(
        page.getByRole("row", { name: "PRIMER Seismic Tan", exact: true }),
      ).toContainText("No standard");
    const clear = page.getByRole("article", { name: "CLEAR Plant-wide" });
    await expect(clear).toContainText("No point below");
    await expect(clear).toContainText("Minimum requirement");
    await expect(clear).toContainText(aat ? "35 µm" : "46 µm");
    await expect(clear).not.toContainText("Maximum");
  });
