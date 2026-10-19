import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { catalogueFixture } from "../fixtures";
import { workbookFixture, fileHash } from "../workbook-fixtures";
import { filmStandardsFixture } from "../film-standards-fixtures";
const evidence = "test-results/evidence/T64-FIX";
const book: components["schemas"]["WorkbookOut"] = {
  ...workbookFixture,
  plant_code: "FTM",
  source_file: "navigation-fixture.xlsx",
  sheet_count: 2,
  sheets: [123, 124].map((id) => ({
    ...workbookFixture.sheets[0],
    batch: {
      ...workbookFixture.sheets[0].batch,
      plant_code: "FTM",
      load_id: id,
      source_sheet: `Sheet ${id}`,
      domain: "WAVESCAN",
    },
  })),
};
const worksheet: components["schemas"]["WorksheetOut"] = {
  plant_code: "FTM",
  file_hash: fileHash,
  source_file: book.source_file,
  plant_question: null,
  extra_columns: [],
  missing_optional: [],
  missing_optional_message: null,
  ready_sheet_count: 2,
  rows_ready: 0,
  rows_held: 0,
  rows_already_in_history: 0,
  rows_need_confirmation: 0,
  summary_message: "Navigation fixture only.",
  checklist: [],
  load_button_label: "Yes, load these rows",
  sheets: book.sheets.map((item) => ({
    load_id: item.batch.load_id,
    sheet: item.batch.source_sheet,
    status: "PENDING_REVIEW",
    state: "ready",
    commit_blockers: [],
    rows_ready: 0,
    rows_loaded: 0,
    rows_held: 0,
    rows_already_in_history: 0,
    rows_need_confirmation: 0,
    rows: [],
    extra_columns: [],
    missing_optional: [],
    hole_rows: [],
    plant_texts: [],
    held: [],
    vehicle_count: 0,
    short_vehicles: [],
    operator_message: "Navigation fixture only.",
  })),
};
async function setup(page: Page, role = "admin") {
  await mockHistory(page, role);
  const mutations: string[] = [];
  await page.route("**/api/v1/**", async (r) => {
    if (r.request().method() !== "GET") {
      mutations.push(r.request().url());
      return r.abort();
    }
    return r.fallback();
  });
  await page.route("**/api/v1/standards/catalogue", (r) => r.fulfill({ json: catalogueFixture }));
  await page.route("**/api/v1/plants/*/filmthickness/standards", (r) =>
    r.fulfill({ json: filmStandardsFixture }),
  );
  await page.route("**/api/v1/plants/*/workbooks?*", (r) =>
    r.fulfill({
      json: {
        plant_code: "FTM",
        plant_is_active: true,
        inbox: "all",
        uploaded_month: null,
        items: [book],
        page: { offset: 0, limit: 200, total: 1, returned: 1 },
      } satisfies components["schemas"]["WorkbookPage"],
    }),
  );
  await page.route(`**/workbooks/${fileHash}`, (r) =>
    r.fulfill({
      json: {
        workbook: book,
        profiles: [],
        possible_replacements: [],
        acknowledgements: [],
      } satisfies components["schemas"]["WorkbookDetailOut"],
    }),
  );
  await page.route(`**/workbooks/${fileHash}/worksheet`, (r) => r.fulfill({ json: worksheet }));
  return mutations;
}
const history = (page: Page) =>
  page.getByRole("heading", { name: "Measurement History", exact: true });
const upload = (page: Page) =>
  page.getByRole("heading", { name: "Upload Data", exact: true, includeHidden: true });
async function canonicalData(page: Page, view: "upload" | "history") {
  await expect.poll(() => new URL(page.url()).searchParams.get("standardView")).toBeNull();
  await expect.poll(() => new URL(page.url()).searchParams.get("dataView")).toBe(view);
  await expect(view === "history" ? history(page) : upload(page)).toBeVisible();
}
for (const view of ["family", "model", "film"])
  test(`${view} Standard to Data and History clears Standard and survives refresh`, async ({
    page,
  }) => {
    const mutations = await setup(page);
    await page.goto(
      `/plant/FTM?standardView=${view}&dataDomain=wavescan&month=2026-09&model=P703&color=White&week=2`,
    );
    await expect(
      page.getByRole("button", {
        name: view === "family" ? "Color Family" : view === "model" ? "Model" : "Film Thickness",
        exact: true,
      }),
    ).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Data", exact: true, includeHidden: true }).click();
    await canonicalData(page, "upload");
    const params = new URL(page.url()).searchParams;
    for (const [key, value] of Object.entries({
      dataDomain: "wavescan",
      month: "2026-09",
      model: "P703",
      color: "White",
      week: "2",
    }))
      expect(params.get(key)).toBe(value);
    await page.getByRole("button", { name: "Measurement History", exact: true }).click();
    await canonicalData(page, "history");
    await expect(page.getByRole("region", { name: "FTM Film standards" })).toHaveCount(0);
    await page.reload();
    await canonicalData(page, "history");
    expect(mutations).toEqual([]);
    if (view === "film")
      await page.screenshot({ path: `${evidence}/fixture-film-to-history.png`, fullPage: true });
  });
for (const role of ["admin", "engineer"])
  test(`${role} Standard to Upload and workbook/sheet navigation retains Data context`, async ({
    page,
  }) => {
    const mutations = await setup(page, role);
    await page.goto("/plant/FTM?standardView=family&dataDomain=wavescan&month=2026-09");
    await page.getByRole("button", { name: "Data", exact: true, includeHidden: true }).click();
    await canonicalData(page, "upload");
    await page.getByRole("button", { name: "Measurement History", exact: true }).click();
    await canonicalData(page, "history");
    await page.getByRole("button", { name: "Upload Data", exact: true }).click();
    await canonicalData(page, "upload");
    await page.getByRole("button", { name: "Review navigation-fixture.xlsx", exact: true }).click();
    const d = page.getByRole("dialog");
    await expect(d).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`file=${fileHash}`));
    await expect(
      d.getByRole("heading", { name: "Confirm this worksheet", exact: true }),
    ).toBeVisible();
    await d.getByRole("combobox", { name: "Sheet", exact: true }).selectOption("124");
    await expect(page).toHaveURL(/sheet=124/);
    await canonicalData(page, "upload");
    expect(new URL(page.url()).searchParams.get("dataDomain")).toBe("wavescan");
    expect(new URL(page.url()).searchParams.get("month")).toBe("2026-09");
    await page.reload();
    await expect(d.getByRole("combobox", { name: "Sheet", exact: true })).toHaveValue("124");
    await canonicalData(page, "upload");
    if (role === "admin") await page.screenshot({ path: `${evidence}/fixture-workbook-sheet.png` });
    await d.getByRole("button", { name: "Close", exact: true }).click();
    await canonicalData(page, "upload");
    expect(new URL(page.url()).searchParams.has("file")).toBe(false);
    expect(new URL(page.url()).searchParams.has("sheet")).toBe(false);
    expect(mutations).toEqual([]);
  });
test("Data to Film Standard canonicalizes and back/forward restores child selection", async ({
  page,
}) => {
  await setup(page);
  await page.goto("/plant/FTM?standardView=film");
  await page.getByRole("button", { name: "Data", exact: true, includeHidden: true }).click();
  await canonicalData(page, "upload");
  await page.getByRole("button", { name: "Measurement History", exact: true }).click();
  await canonicalData(page, "history");
  await page.getByRole("button", { name: "Standard", exact: true }).click();
  await page.getByRole("button", { name: "Film Thickness", exact: true }).click();
  await expect(page.getByRole("region", { name: "FTM Film standards" })).toBeVisible();
  expect(new URL(page.url()).searchParams.has("dataView")).toBe(false);
  expect(new URL(page.url()).searchParams.has("dataDomain")).toBe(false);
  await page.goBack();
  await expect(page).toHaveURL(/standardView=family/);
  await page.goBack();
  await canonicalData(page, "history");
  await expect(
    page.getByRole("button", { name: "Measurement History", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.goBack();
  await canonicalData(page, "upload");
  await page.goForward();
  await canonicalData(page, "history");
  await page.goForward();
  await page.goForward();
  await expect(page.getByRole("region", { name: "FTM Film standards" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("region", { name: "FTM Film standards" })).toBeVisible();
});
for (const selection of ["dataView=history", "dataView=upload", `file=${fileHash}&sheet=124`])
  test(`mixed URL ${selection} gives Data priority on load and refresh`, async ({ page }) => {
    await setup(page);
    let standards = 0;
    page.on("request", (r) => {
      if (r.url().includes("filmthickness/standards")) standards++;
    });
    await page.goto(`/plant/FTM?standardView=film&${selection}&dataDomain=wavescan&month=2026-09`);
    for (let iteration = 0; iteration < 2; iteration++) {
      await expect(selection === "dataView=history" ? history(page) : upload(page)).toBeVisible();
      await expect(page.getByRole("region", { name: "FTM Film standards" })).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "Data", exact: true, includeHidden: true }),
      ).toHaveAttribute("aria-pressed", "true");
      if (selection.startsWith("file")) {
        await expect(page.getByRole("dialog")).toBeVisible();
        await expect(page.getByRole("combobox", { name: "Sheet", exact: true })).toHaveValue("124");
      }
      if (iteration === 0) await page.reload();
    }
    expect(standards).toBe(0);
    if (selection.startsWith("file")) {
      await page.getByRole("combobox", { name: "Sheet", exact: true }).selectOption("123");
      await canonicalData(page, "upload");
      const params = new URL(page.url()).searchParams;
      expect(params.get("file")).toBe(fileHash);
      expect(params.get("sheet")).toBe("123");
      expect(params.get("dataDomain")).toBe("wavescan");
    }
  });
for (const role of ["admin", "engineer", "viewer"])
  test(`${role} Data entry preserves existing history child`, async ({ page }) => {
    await setup(page, role);
    await page.goto(
      "/plant/FTM?standardView=family&dataView=history&dataDomain=wavescan&month=2026-09",
    );
    await expect(history(page)).toBeVisible();
    await page.getByRole("button", { name: "Data", exact: true, includeHidden: true }).click();
    await canonicalData(page, "history");
    expect(new URL(page.url()).searchParams.get("dataDomain")).toBe("wavescan");
  });
test("live read-only Film Standard to History canonical URL and screenshot", async ({ page }) => {
  const mutations: string[] = [];
  await page.route("**/api/v1/**", async (r) => {
    if (r.request().method() !== "GET") {
      mutations.push(r.request().url());
      return r.abort();
    }
    return r.continue();
  });
  await page.goto("/plant/FTM?standardView=film");
  await expect(page.getByRole("region", { name: "FTM Film standards" })).toBeVisible();
  await page.getByRole("button", { name: "Data", exact: true, includeHidden: true }).click();
  await canonicalData(page, "upload");
  await page.getByRole("button", { name: "Measurement History", exact: true }).click();
  await canonicalData(page, "history");
  await page.reload();
  await canonicalData(page, "history");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/live-film-to-history.png`, fullPage: true });
  const info = test.info();
  await info.attach("canonical-live-url", {
    body: JSON.stringify({ url: page.url(), mutations, fixture: false }, null, 2),
    contentType: "application/json",
  });
  console.log("LIVE_AFTER_FIX_URL=" + page.url());
  expect(mutations).toEqual([]);
});
