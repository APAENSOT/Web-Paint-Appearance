import { expect, test, type Page } from "@playwright/test";
import { mockHistory } from "../history-fixtures";

const cards = [
  {
    model: "P703",
    color: "White",
    vehicle_count: 3,
    point_count: 3,
    measured_date_min: "2026-09-13",
    measured_date_max: "2026-09-13",
  },
  {
    model: "U704",
    color: "Blue",
    vehicle_count: 1,
    point_count: 2,
    measured_date_min: "2026-09-14",
    measured_date_max: "2026-09-14",
  },
];

// Two cards in one week, filtered the way the API filters them, so a filter
// that is still set after Back is visible as a missing card.
async function mockTwoCardWeek(page: Page) {
  const reads: URL[] = [];
  await page.route("**/history/summaries?*", (r) => {
    const url = new URL(r.request().url());
    reads.push(url);
    const model = url.searchParams.get("model"),
      color = url.searchParams.get("color");
    const kept = cards.filter(
      (c) => (!model || c.model === model) && (!color || c.color === color),
    );
    return r.fulfill({
      json: {
        plant_code: "AAT",
        plant_is_active: true,
        month: url.searchParams.get("month"),
        model,
        color,
        weeks: kept.length
          ? [
              {
                week: 2,
                measured_date_min: "2026-09-13",
                measured_date_max: "2026-09-14",
                cards: kept,
              },
            ]
          : [],
        active_data_source: "v_wavescan_active",
      },
    });
  });
  return reads;
}

const modelFilter = (page: Page) => page.getByLabel("Model", { exact: true });
const colourFilter = (page: Page) => page.getByLabel("Colour", { exact: true });
const card = (page: Page, name: RegExp) => page.getByRole("button", { name });

test("T105 opening a week card leaves the Model and Colour filters as they were", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  const summaries = await mockTwoCardWeek(page);
  await page.goto("/plant/aat?dataView=history&dataDomain=wavescan");
  await expect(card(page, /P703.*White/)).toBeVisible();
  await expect(card(page, /U704.*Blue/)).toBeVisible();

  await card(page, /P703.*White/).click();
  await expect(page.getByRole("heading", { name: "Week 2 / P703 / White" })).toBeVisible();
  await expect(page).toHaveURL(/cardModel=P703/);
  await expect(page).toHaveURL(/cardColor=White/);
  await expect(page).not.toHaveURL(/[?&]model=/);
  await expect(page).not.toHaveURL(/[?&]color=/);
  await expect(modelFilter(page)).toHaveValue("");
  await expect(colourFilter(page)).toHaveValue("");

  await page.getByRole("button", { name: "Back to week cards", exact: true }).click();
  await expect(modelFilter(page)).toHaveValue("");
  await expect(colourFilter(page)).toHaveValue("");
  await expect(card(page, /P703.*White/)).toBeVisible();
  await expect(card(page, /U704.*Blue/)).toBeVisible();
  await expect(page).toHaveURL(/dataDomain=wavescan/);
  await expect(page).not.toHaveURL(/cardModel=|cardColor=|week=/);
  expect(summaries.at(-1)?.searchParams.has("model")).toBe(false);
  expect(summaries.at(-1)?.searchParams.has("color")).toBe(false);
});

test("T105 a filter set before the card is still set after Back to week cards", async ({
  page,
}) => {
  await mockHistory(page, "viewer");
  await mockTwoCardWeek(page);
  await page.goto("/plant/aat?dataView=history&dataDomain=wavescan");
  await modelFilter(page).selectOption("P703");
  await expect(page).toHaveURL(/model=P703/);
  await expect(card(page, /U704.*Blue/)).toHaveCount(0);

  await card(page, /P703.*White/).click();
  await expect(page.getByRole("heading", { name: "Week 2 / P703 / White" })).toBeVisible();
  await page.getByRole("button", { name: "Back to week cards", exact: true }).click();
  await expect(modelFilter(page)).toHaveValue("P703");
  await expect(colourFilter(page)).toHaveValue("");
  await expect(card(page, /P703.*White/)).toBeVisible();
  await expect(card(page, /U704.*Blue/)).toHaveCount(0);
  await expect(page).not.toHaveURL(/cardModel=|cardColor=|week=/);
});

test("T105 the vehicle walk returns to empty filters and every week card", async ({ page }) => {
  await mockHistory(page, "viewer");
  await mockTwoCardWeek(page);
  await page.goto("/plant/aat?dataView=history&dataDomain=wavescan");
  await card(page, /P703.*White/).click();
  await page.getByRole("button", { name: /T09-TEST/ }).click();
  await expect(page.locator('[data-measurement-id="41"]')).toBeVisible();

  await page.getByRole("button", { name: "Back to vehicle sets", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Vehicle sets", exact: true })).toBeVisible();
  await expect(page).not.toHaveURL(/vehicle=/);

  await page.getByRole("button", { name: "Back to week cards", exact: true }).click();
  await expect(modelFilter(page)).toHaveValue("");
  await expect(colourFilter(page)).toHaveValue("");
  await expect(card(page, /P703.*White/)).toBeVisible();
  await expect(card(page, /U704.*Blue/)).toBeVisible();
  await expect(page).toHaveURL(/dataDomain=wavescan/);
  await expect(page).not.toHaveURL(/cardModel=|cardColor=|week=|vehicle=/);
});
