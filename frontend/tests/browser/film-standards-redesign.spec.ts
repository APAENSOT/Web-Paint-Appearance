import { expect, test, type Page } from "@playwright/test";
import { mockHistory } from "../history-fixtures";
import { catalogueFixture } from "../fixtures";
import { rule } from "../film-standards-fixtures";
import type {
  FilmStandardsOut,
  FilmStandardPublishIn,
} from "../../src/features/filmthickness/film-standards";
const evidence = "test-results/evidence/T65";
const API = process.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8012";

/** T104 (D-104-2): the plant's latest plant-wide E-coat provenance, read from
 * the API the page reads.
 *
 * The live Sources dialog opens on E-coat / Plant-wide, so this is the rule it
 * must be showing. Pinning the literal `FILM-STANDARDS-AUDIT` instead made
 * these two cases fail every time the owner published a real standard -- the
 * four `Test` rows, then FTM E-coat from the Control Plan -- which is the
 * table working, not a regression. GET only; this spec never publishes.
 */
async function liveEcoatSource(page: Page, code: string) {
  const response = await page.request.get(`${API}/api/v1/plants/${code}/filmthickness/standards`);
  expect(response.ok(), await response.text()).toBe(true);
  const body = (await response.json()) as FilmStandardsOut;
  const found = body.rules.find((r) => r.layer_code === "ECOAT" && r.color_name === null);
  expect(found, `${code} publishes a plant-wide E-coat rule`).toBeTruthy();
  return found!;
}

export function fixture(code = "FTM"): FilmStandardsOut {
  return {
    plant_code: code,
    colors: [
      { color_name: "Zulu", family_name: null },
      { color_name: "Blue", family_name: "Metallics" },
      { color_name: "Amber", family_name: "Solids" },
      { color_name: "Azure", family_name: "Metallics" },
    ],
    rules: [
      { layer_code: "ECOAT", color_name: null, h: rule(0), v: rule(18) },
      {
        layer_code: "PRIMER",
        color_name: code === "AAT" ? "Blue" : null,
        h: rule(20, 25),
        v: rule(20, 25),
      },
      {
        layer_code: "CLEAR",
        color_name: null,
        h: rule(36, null, 46),
        v: rule(30, null, 46, "Vertical provenance"),
      },
      { layer_code: "BASE", color_name: "Blue", h: rule(12, 20, null, "Blue own"), v: null },
      {
        layer_code: "BASE",
        color_name: "Retired",
        h: rule(5, 10, null, "Retained source"),
        v: null,
      },
    ],
  };
}
async function setup(page: Page, code = "FTM", initial = fixture(code)) {
  await mockHistory(page, "admin");
  let data = initial;
  const reads: string[] = [];
  const posts: FilmStandardPublishIn[] = [];
  await page.route("**/api/v1/plants/*/filmthickness/standards", (r) => {
    reads.push(r.request().url());
    return r.fulfill({ json: data });
  });
  await page.route("**/api/v1/standards/catalogue", (r) => r.fulfill({ json: catalogueFixture }));
  await page.route("**/api/v1/filmthickness/standards", (r) => {
    posts.push(r.request().postDataJSON());
    return r.fulfill({
      status: 201,
      json: {
        plant_code: code,
        layer_code: "BASE",
        color_name: "Amber",
        audit_id: 7,
        created_at: "2026-10-06T03:00:00Z",
      },
    });
  });
  return {
    reads,
    posts,
    setData: (next: FilmStandardsOut) => {
      data = next;
    },
  };
}
for (const code of ["FTM", "FVL", "SAP", "AAT"])
  test(`${code} plant template has one panel per shared layer and all offered table colours`, async ({
    page,
  }) => {
    await setup(page, code);
    await page.goto(`/plant/${code}?standardView=film`);
    const shared = page.getByRole("region", { name: "Shared standards", exact: true });
    await expect(shared).toBeVisible();
    await expect(shared).toContainText("Apply to all offered colours");
    const names = await shared
      .getByRole("article")
      .evaluateAll((es) => es.map((e) => e.getAttribute("aria-label")));
    expect(names).toEqual(
      code === "AAT"
        ? ["ECOAT Plant-wide", "CLEAR Plant-wide"]
        : ["ECOAT Plant-wide", "PRIMER Plant-wide", "CLEAR Plant-wide"],
    );
    await expect(shared.getByRole("article", { name: "ECOAT Plant-wide" })).toContainText("0 µm");
    const tableLayers = code === "AAT" ? ["PRIMER", "BASE"] : ["BASE"];
    for (const layer of tableLayers) {
      const table = page.getByRole("region", { name: `${layer} colour standards` });
      await expect(table).toBeVisible();
      for (const color of ["Amber", "Azure", "Blue", "Zulu"])
        await expect(
          table.getByRole("row", { name: `${layer} ${color}`, exact: true }),
        ).toBeVisible();
    }
    await expect(page.getByText("Source details", { exact: true })).toHaveCount(0);
  });

test("AAT family ordering, independent collapse memory and colour-only search", async ({
  page,
}) => {
  const state = await setup(page, "AAT");
  await page.goto("/plant/AAT?standardView=film");
  const primer = page.getByRole("region", { name: "PRIMER colour standards" });
  const base = page.getByRole("region", { name: "BASE colour standards" });
  for (const table of [primer, base]) {
    await expect(table.getByRole("region")).toHaveCount(3);
    expect(
      await table
        .getByRole("region")
        .evaluateAll((es) => es.map((e) => e.getAttribute("aria-label"))),
    ).toEqual([
      `${table === primer ? "PRIMER" : "BASE"} family Metallics`,
      `${table === primer ? "PRIMER" : "BASE"} family Solids`,
      `${table === primer ? "PRIMER" : "BASE"} family No family assigned`,
    ]);
    expect(
      await table
        .getByRole("row")
        .filter({ has: page.locator('th[scope="row"]') })
        .evaluateAll((es) => es.map((e) => e.getAttribute("aria-label"))),
    ).toEqual([
      `${table === primer ? "PRIMER" : "BASE"} Azure`,
      `${table === primer ? "PRIMER" : "BASE"} Blue`,
      `${table === primer ? "PRIMER" : "BASE"} Amber`,
      `${table === primer ? "PRIMER" : "BASE"} Zulu`,
    ]);
  }
  await primer.getByRole("button", { name: "Metallics", exact: true }).click();
  await expect(primer.getByRole("row", { name: "PRIMER Blue", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(primer.getByRole("button", { name: "Metallics", exact: true })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await page.getByLabel("Find a colour").fill("  bLu  ");
  for (const layer of ["PRIMER", "BASE"]) {
    const t = page.getByRole("region", { name: `${layer} colour standards` });
    await expect(t.getByRole("row", { name: `${layer} Blue`, exact: true })).toBeVisible();
    await expect(t.getByRole("row", { name: `${layer} Azure`, exact: true })).toHaveCount(0);
  }
  await page.getByLabel("Find a colour").fill("Metallics");
  await expect(page.getByText("No matching colours", { exact: true })).toHaveCount(2);
  await expect(page.getByRole("article", { name: "ECOAT Plant-wide" })).toBeVisible();
  await page.getByLabel("Find a colour").fill("");
  await expect(primer.getByRole("button", { name: "Metallics", exact: true })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await expect(base.getByRole("button", { name: "Metallics", exact: true })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  expect(state.posts).toEqual([]);
});
test("existing exceptions preserve scope and precedence, retained rows cannot publish", async ({
  page,
}) => {
  const data = fixture();
  data.rules.push(
    { layer_code: "ECOAT", color_name: "Blue", h: rule(12, 20, null, "Exception H"), v: null },
    { layer_code: "ECOAT", color_name: "Lost", h: rule(9, 10, null, "Lost own"), v: null },
    {
      layer_code: "BASE",
      color_name: null,
      h: rule(7, 10, null, "Base-wide H"),
      v: rule(4, 8, null, "Base-wide V"),
    },
  );
  const state = await setup(page, "FTM", data);
  await page.goto("/plant/FTM?standardView=film");
  const shared = page.getByRole("region", { name: "Shared standards", exact: true });
  const base = page.getByRole("region", { name: "BASE colour standards" });
  await expect(shared).toContainText("Existing colour exceptions take precedence");
  await expect(page.getByRole("article", { name: "ECOAT Blue" })).toBeHidden();
  await shared.getByText("Existing exceptions", { exact: true }).click();
  const exception = page.getByRole("article", { name: "ECOAT Blue" });
  await expect(exception).toContainText("12 µm");
  await expect(exception).toContainText("18 µm");
  await expect(exception).toContainText("Inherited");
  await expect(shared.getByRole("article", { name: "ECOAT Lost" })).toBeHidden();
  await exception.getByRole("button", { name: "Adjust standard" }).click();
  const d = page.getByRole("dialog");
  await expect(d).toContainText("FTM · E-coat · Blue");
  await expect(d.locator("#h-lo")).toHaveValue("12");
  await expect(d.locator("#v-lo")).toHaveValue("18");
  await d.locator("#note").fill("Fixture exception");
  await d.getByRole("button", { name: "Review publish", exact: true }).click();
  await d.getByRole("button", { name: "Publish new version" }).click();
  await expect(d).toHaveCount(0);
  expect(state.posts[0]).toMatchObject({
    plant_code: "FTM",
    layer_code: "ECOAT",
    color_name: "Blue",
    h: { lo: 12, hi: 20, target: null },
    v: { lo: 18, hi: null, target: null },
  });
  await expect(base.getByRole("row", { name: "BASE Blue", exact: true })).toContainText("12 µm");
  await expect(base.getByRole("row", { name: "BASE Blue", exact: true })).toContainText("4 µm");
  await expect(base.getByRole("row", { name: "BASE Amber", exact: true })).toContainText(
    "Inherited",
  );
  await expect(
    base
      .getByRole("row", { name: "BASE Amber", exact: true })
      .getByRole("button", { name: "Set standard" }),
  ).toBeVisible();
  await base.getByText("Existing exceptions", { exact: true }).click();
  await base
    .getByRole("article", { name: "BASE Plant-wide" })
    .getByRole("button", { name: "Adjust standard" })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Base · Plant-wide");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await shared.getByText("Not offered · E-coat", { exact: true }).click();
  const retained = page.getByRole("article", { name: "ECOAT Lost" });
  await expect(retained).toContainText("No standard");
  await expect(retained).not.toContainText("Inherited");
  await expect(retained.getByRole("button")).toHaveCount(0);
  await expect(shared.getByRole("article", { name: "ECOAT Lost" })).toHaveCount(1);
  await page.getByLabel("Find a colour").fill("nothing");
  await expect(retained).toBeVisible();
  await expect(exception).toBeVisible();
  await page.screenshot({ path: `${evidence}/fixture-exceptions.png`, fullPage: true });
});
test("Sources defaults, choices, inheritance, retained and missing attribution, keyboard focus", async ({
  page,
}) => {
  const data = fixture();
  data.rules.push({
    layer_code: "ECOAT",
    color_name: "Blue",
    h: rule(12, 20, null, "Exception H"),
    v: null,
  });
  await setup(page, "FTM", data);
  await page.goto("/plant/FTM?standardView=film");
  await page.getByLabel("Find a colour").fill("nothing");
  const trigger = page.getByRole("button", { name: "Sources", exact: true });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const d = page.getByRole("dialog", { name: "Sources", exact: true });
  await expect(d.getByRole("combobox", { name: "Layer", exact: true })).toHaveValue("ECOAT");
  await expect(d.getByRole("combobox", { name: "Rule", exact: true })).toHaveValue("null");
  expect(
    await d
      .getByRole("combobox", { name: "Layer", exact: true })
      .locator("option")
      .allTextContents(),
  ).toEqual(["E-coat", "Primer", "Base", "Clear"]);
  const choose = (color: string | null) =>
    d.getByRole("combobox", { name: "Rule", exact: true }).selectOption(JSON.stringify(color));
  await choose("Blue");
  await expect(d.getByRole("region", { name: "Horizontal source" })).toContainText("Exception H");
  await expect(d.getByRole("region", { name: "Vertical source" })).toContainText(
    "Plant-wide source (Inherited)",
  );
  await expect(d).toContainText("Not provided");
  await expect(d.locator("time").first()).toHaveAttribute("datetime", "2026-10-06T03:00:00Z");
  await expect(d).toContainText("6 Oct 2026, 10:00:00");
  await d.getByRole("combobox", { name: "Layer", exact: true }).selectOption("BASE");
  await expect(d.getByRole("combobox", { name: "Rule", exact: true })).toHaveValue("null");
  await expect(d.getByText("No source available", { exact: true })).toHaveCount(2);
  expect(
    await d
      .getByRole("combobox", { name: "Rule", exact: true })
      .locator("option")
      .allTextContents(),
  ).toEqual(["Plant-wide", "Amber", "Azure", "Blue", "Zulu", "Retired — Not offered"]);
  await choose("Retired");
  await expect(d).toContainText("Retained source");
  await expect(d.getByRole("region", { name: "Vertical source" })).toContainText(
    "No source available",
  );
  await expect(d).not.toContainText("Inherited");
  await expect(d.getByRole("button", { name: /Adjust|Set standard|Publish/ })).toHaveCount(0);
  await d.getByRole("combobox", { name: "Layer", exact: true }).selectOption("CLEAR");
  await expect(d.getByRole("region", { name: "Vertical source" })).toContainText(
    "Vertical provenance",
  );
  await expect.poll(async () => Math.round((await d.boundingBox())!.x)).toBe(960);
  await page.screenshot({ path: `${evidence}/fixture-sources-desktop.png` });
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(d.getByRole("combobox", { name: "Layer", exact: true })).toHaveValue("ECOAT");
  await expect(d.getByRole("combobox", { name: "Rule", exact: true })).toHaveValue("null");
  await page.mouse.click(1, 1);
  await expect(d).toHaveCount(0);
});
test("Sources retains valid choice during refetch and resets removed choice without stale provenance", async ({
  page,
}) => {
  const state = await setup(page);
  await page.goto("/plant/FTM?standardView=film");
  await expect(page.getByRole("row", { name: "BASE Blue", exact: true })).toBeVisible();
  for (const removed of [false, true]) {
    let release!: () => void;
    const hold = new Promise<void>((r) => (release = r));
    const updated = fixture();
    if (removed) {
      updated.colors = updated.colors.filter((c) => c.color_name !== "Blue");
      updated.rules = updated.rules.filter((r) => r.color_name !== "Blue");
    } else
      updated.rules = updated.rules.map((r) =>
        r.color_name === "Blue" ? { ...r, h: rule(12, 20, null, "Refreshed Blue") } : r,
      );
    await page.route("**/api/v1/plants/*/filmthickness/standards", async (r) => {
      await hold;
      await r.fulfill({ json: updated });
    });
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Sources", exact: true }).click();
    const d = page.getByRole("dialog", { name: "Sources", exact: true });
    await d.getByRole("combobox", { name: "Layer", exact: true }).selectOption("BASE");
    await d
      .getByRole("combobox", { name: "Rule", exact: true })
      .selectOption(JSON.stringify("Blue"));
    release();
    await expect(d.getByRole("combobox", { name: "Rule", exact: true })).toHaveValue(
      removed ? "null" : JSON.stringify("Blue"),
    );
    if (removed) {
      await expect(d).not.toContainText("Refreshed Blue");
      await expect(d.getByText("No source available", { exact: true })).toHaveCount(2);
    } else await expect(d).toContainText("Refreshed Blue");
    await page.keyboard.press("Escape");
  }
  expect(state.posts).toEqual([]);
});
test("external catalogue changes update offered families, missing rules and retained values on exact Refresh", async ({
  page,
}) => {
  const state = await setup(page, "AAT");
  await page.goto("/plant/AAT?standardView=film");
  await expect(page.getByRole("row", { name: "BASE Blue", exact: true })).toBeVisible();
  const data = fixture("AAT");
  data.colors = data.colors
    .filter((c) => c.color_name !== "Blue")
    .map((c) => (c.color_name === "Amber" ? { ...c, family_name: "First family" } : c));
  data.colors.push({ color_name: "New Green", family_name: "New family" });
  state.setData(data);
  const other: string[] = [];
  page.on("request", (r) => {
    if (!r.url().includes("filmthickness/standards")) other.push(r.url());
  });
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  for (const layer of ["PRIMER", "BASE"]) {
    const t = page.getByRole("region", { name: `${layer} colour standards` });
    await expect(t.getByRole("row", { name: `${layer} Blue`, exact: true })).toHaveCount(0);
    await expect(t.getByRole("region", { name: `${layer} family First family` })).toContainText(
      "Amber",
    );
    await expect(t.getByRole("row", { name: `${layer} New Green`, exact: true })).toContainText(
      "No standard",
    );
    await t
      .getByText(`Not offered · ${layer === "PRIMER" ? "Primer" : "Base"}`, { exact: true })
      .click();
    await expect(t.getByRole("article", { name: `${layer} Blue` })).toBeVisible();
    await expect(t.getByRole("article", { name: `${layer} Blue` }).getByRole("button")).toHaveCount(
      0,
    );
  }
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  const d = page.getByRole("dialog", { name: "Sources", exact: true });
  await d
    .getByRole("combobox", { name: "Rule", exact: true })
    .selectOption(JSON.stringify("New Green"));
  await expect(d.getByText("Plant-wide source (Inherited)", { exact: true })).toHaveCount(2);
  expect(other).toEqual([]);
  expect(state.posts).toEqual([]);
});

test("Manage colours uses existing fixture mint/offer flow and returning Film refetches without publication", async ({
  page,
}) => {
  const state = await setup(page);
  const catalogue = structuredClone(catalogueFixture);
  catalogue.colors.push({ color_name: "Historical Blue", color_group: null, plants: [] });
  let data = fixture();
  await page.route("**/api/v1/standards/catalogue", (r) => r.fulfill({ json: catalogue }));
  const minted: import("../../src/api/types").components["schemas"]["ColorMintIn"][] = [];
  const offered: import("../../src/api/types").components["schemas"]["PlantColorPatchIn"][] = [];
  const add = (name: string) => {
    catalogue.colors.push({
      color_name: name,
      color_group: null,
      plants: [
        { plant_code: "FTM", is_offered: true, family_code: "MS", family_name: "Medium Solids" },
      ],
    });
    data = {
      ...data,
      colors: [...data.colors, { color_name: name, family_name: "Medium Solids" }],
    };
    state.setData(data);
  };
  await page.route("**/api/v1/standards/colours", (r) => {
    const body = r
      .request()
      .postDataJSON() as import("../../src/api/types").components["schemas"]["ColorMintIn"];
    minted.push(body);
    add(body.color_name);
    return r.fulfill({
      status: 201,
      json: {
        color_name: body.color_name,
        audit_id: 1,
      } satisfies import("../../src/api/types").components["schemas"]["ColourMintOut"],
    });
  });
  await page.route("**/api/v1/standards/plant-colours", (r) => {
    const body = r
      .request()
      .postDataJSON() as import("../../src/api/types").components["schemas"]["PlantColorPatchIn"];
    offered.push(body);
    catalogue.colors = catalogue.colors.filter((c) => c.color_name !== body.color_name);
    add(body.color_name);
    return r.fulfill({
      json: {
        is_offered: true,
        family_name: "Medium Solids",
        audit_id: 2,
      } satisfies import("../../src/api/types").components["schemas"]["PlantColorPatchOut"],
    });
  });
  await page.goto("/plant/FTM?standardView=film");
  await expect(page.getByRole("row", { name: "BASE Blue", exact: true })).toBeVisible();
  const before = state.reads.length;
  await page.getByRole("link", { name: "Manage colours", exact: true }).click();
  await expect(page).toHaveURL(/standardView=family/);
  const card = page.locator('[data-family="MS"]');
  await card.getByRole("combobox").click();
  await page.getByRole("option", { name: /Other/ }).click();
  await card.getByLabel("New colour name").fill("New Colour");
  await card.getByRole("button", { name: "Add colour", exact: true }).click();
  await page
    .getByRole("dialog", { name: "Confirm new colour" })
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(card.getByRole("button", { name: "New Colour", exact: true })).toBeVisible();
  await card.getByRole("combobox").click();
  await page.getByRole("option", { name: "Historical Blue", exact: true }).click();
  await card.getByRole("button", { name: "Add colour", exact: true }).click();
  await expect(card.getByRole("button", { name: "Historical Blue", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Film Thickness", exact: true }).click();
  await expect(page).toHaveURL(/standardView=film/);
  for (const name of ["New Colour", "Historical Blue"])
    await expect(page.getByRole("row", { name: `BASE ${name}`, exact: true })).toContainText(
      "No standard",
    );
  await expect(page.getByRole("region", { name: "BASE family Medium Solids" })).toBeVisible();
  expect(state.reads.length).toBeGreaterThan(before);
  expect(minted).toEqual([{ color_name: "New Colour", family_code: "MS", plants: ["FTM"] }]);
  expect(offered).toEqual([
    { plant_code: "FTM", color_name: "Historical Blue", is_offered: true, family_code: "MS" },
  ]);
  expect(state.posts).toEqual([]);
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  const d = page.getByRole("dialog", { name: "Sources", exact: true });
  await d
    .getByRole("combobox", { name: "Rule", exact: true })
    .selectOption(JSON.stringify("New Colour"));
  await expect(d.getByText("Plant-wide source (Inherited)", { exact: true })).toHaveCount(2);
});
test("empty catalogues and missing rules retain configured panels and permitted blank drafts", async ({
  page,
}) => {
  for (const code of ["FTM", "AAT"]) {
    await setup(page, code, { plant_code: code, colors: [], rules: [] });
    await page.goto(`/plant/${code}?standardView=film`);
    const shared = page.getByRole("region", { name: "Shared standards", exact: true });
    await expect(shared.getByRole("article")).toHaveCount(code === "AAT" ? 2 : 3);
    await expect(page.getByText("No offered colours for this plant", { exact: true })).toHaveCount(
      code === "AAT" ? 2 : 1,
    );
    await page.getByLabel("Find a colour").fill("nothing");
    await expect(page.getByText("No matching colours", { exact: true })).toHaveCount(0);
    await shared
      .getByRole("article", { name: "ECOAT Plant-wide" })
      .getByRole("button", { name: "Set standard" })
      .click();
    const d = page.getByRole("dialog");
    await expect(d.locator("#h-lo")).toHaveValue("");
    await expect(d.locator("#v-hi")).toHaveValue("");
    await expect(d.getByLabel("Same for Horizontal and Vertical")).not.toBeChecked();
    await d.getByRole("button", { name: "Cancel", exact: true }).click();
  }
});
test("shared grids honor viewport breakpoints and reduced motion without overflow", async ({
  page,
}) => {
  await setup(page);
  await page.goto("/plant/FTM?standardView=film");
  await expect(page.getByRole("article", { name: "ECOAT Plant-wide" })).toBeVisible();
  for (const [width, count] of [
    [390, 1],
    [768, 2],
    [940, 3],
    [1279, 3],
    [1280, 3],
    [1440, 3],
  ]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page
        .locator(".film-shared-grid")
        .evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ").length),
    ).toBe(count);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.getByRole("row", { name: "BASE Blue", exact: true })).toBeVisible();
  expect(
    await page
      .getByRole("row", { name: "BASE Blue", exact: true })
      .evaluate((e) => getComputedStyle(e).transitionDuration),
  ).toBe("0s");
});
for (const theme of ["dark", "light"])
  test(`fixture ${theme} 390px table, Sources drawer and publish review`, async ({ page }) => {
    await page.addInitScript((theme) => {
      document.documentElement.classList.toggle("dark", theme === "dark");
      document.documentElement.style.colorScheme = theme;
    }, theme);
    await setup(page, "AAT");
    await page.goto("/plant/AAT?standardView=film");
    await page.evaluate((theme) => {
      document.documentElement.classList.toggle("dark", theme === "dark");
      document.documentElement.style.colorScheme = theme;
    }, theme);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("row", { name: "BASE Blue", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await expect(
      page
        .getByRole("row", { name: "BASE Blue", exact: true })
        .getByText("Horizontal Minimum", { exact: true }),
    ).toBeVisible();
    await page.screenshot({ path: `${evidence}/fixture-mobile-${theme}.png`, fullPage: true });
    await page.getByRole("button", { name: "Sources", exact: true }).click();
    const sources = page.getByRole("dialog", { name: "Sources", exact: true });
    await expect(sources).toBeVisible();
    await expect.poll(async () => Math.round((await sources.boundingBox())!.width)).toBe(390);
    await expect.poll(async () => Math.round((await sources.boundingBox())!.x)).toBe(0);
    await page.screenshot({ path: `${evidence}/fixture-mobile-sources-${theme}.png` });
    await page.keyboard.press("Escape");
    const row = page.getByRole("row", { name: "BASE Amber", exact: true });
    await row.getByRole("button", { name: "Set standard" }).click();
    const d = page.getByRole("dialog");
    await d.locator("#h-lo").fill("0");
    await d.locator("#v-hi").fill("500");
    await d.locator("#note").fill("Fixture mobile review");
    await d.getByRole("button", { name: "Review publish", exact: true }).click();
    await expect(d.getByRole("region", { name: "Proposed values" })).toContainText("500 µm");
    await d.evaluate((e) => {
      e.scrollTop = 0;
    });
    await page.screenshot({ path: `${evidence}/fixture-mobile-review-${theme}.png` });
    await d.getByRole("button", { name: "Publish new version" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${evidence}/fixture-mobile-review-actions-${theme}.png` });
    await d.getByRole("button", { name: "Cancel", exact: true }).click();
  });
for (const theme of ["dark", "light"])
  test(`live read-only ${theme} FTM and AAT desktop and Sources`, async ({ page }) => {
    const mutations: string[] = [];
    await page.route("**/api/v1/**", async (r) => {
      if (r.request().method() !== "GET") {
        mutations.push(r.request().url());
        return r.abort();
      }
      return r.continue();
    });
    for (const code of ["FTM", "AAT"]) {
      await page.goto(`/plant/${code}?standardView=film`);
      await page.evaluate((theme) => {
        document.documentElement.classList.toggle("dark", theme === "dark");
        document.documentElement.style.colorScheme = theme;
      }, theme);
      await expect(
        page
          .getByRole("article", { name: "ECOAT Plant-wide" })
          .getByRole("button", { name: "Adjust standard" }),
      ).toBeVisible();
      await page.screenshot({
        path: `${evidence}/live-${code.toLowerCase()}-${theme}-desktop.png`,
        fullPage: true,
      });
      const latest = await liveEcoatSource(page, code);
      await page.getByRole("button", { name: "Sources", exact: true }).click();
      const d = page.getByRole("dialog", { name: "Sources", exact: true });
      await expect(d).toContainText("Asia/Bangkok");
      for (const orientation of ["Horizontal", "Vertical"] as const) {
        const published = latest[orientation === "Horizontal" ? "h" : "v"];
        const section = d.getByRole("region", { name: `${orientation} source`, exact: true });
        await expect(section).toBeVisible();
        if (!published) {
          await expect(section).toContainText("No source available");
          continue;
        }
        await expect(section).toContainText(published.source_document ?? "Not provided");
        await expect(section).toContainText(published.source_note);
        // The instant itself, so this does not re-implement the page's
        // Intl formatter -- and so "no provenance" still fails.
        await expect(section.locator("time")).toHaveAttribute("datetime", published.created_at);
      }
      await expect.poll(async () => Math.round((await d.boundingBox())!.width)).toBe(480);
      await expect.poll(async () => Math.round((await d.boundingBox())!.x)).toBe(960);
      await page.screenshot({
        path: `${evidence}/live-${code.toLowerCase()}-${theme}-sources.png`,
      });
    }
    expect(mutations).toEqual([]);
  });
