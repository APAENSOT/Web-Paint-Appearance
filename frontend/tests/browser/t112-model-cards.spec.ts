/**
 * T112 Model screen cards, in a real browser (mocked with `page.route`; the
 * live counts are the backend's `test_t112_model_points.py`). What this pins:
 *
 * * D-112-3 -- every card reads the server's live and counted points, a
 *   domain with no list omitted;
 * * T112-FIX (D-112F-7) -- one card design for every model: the model_code
 *   heading, one grey line, then Remove. No display-name heading, no chip;
 * * T112-FIX (D-112F-6) -- a Film-only card reads "Film Thickness only · Film
 *   M points";
 * * T112-FIX (D-112F-8) -- Remove asks once (Remove / Cancel) before it
 *   writes, and a Film-only card's Remove calls the same endpoint;
 * * T112-FIX (D-112F-4) -- the Attach list is the server's, Film-only models
 *   included;
 * * 390 width without horizontal scroll.
 *
 * Every write is answered by the mock -- nothing reaches a server.
 * Screenshots: desktop and 390, written to test-results/screenshots.
 */
import { expect, test, type Page } from "@playwright/test";
import type { components } from "../../src/api/types";
import { mockHistory } from "../history-fixtures";
import { catalogueFixture, cleanReview } from "../fixtures";
import { fileHash, workbookFixture } from "../workbook-fixtures";

type ModelPoints = components["schemas"]["PlantModelPointsOut"];

const SHOTS = "test-results/screenshots";

const card = (
  model_code: string,
  wavescan_points: number | null,
  film_points: number | null,
  display_name: string | null = null,
  wavescan_ok = wavescan_points !== null,
) => ({
  model_code,
  display_name,
  series_code: "P703",
  body_style: "PICKUP",
  wavescan_ok,
  wavescan_offered: wavescan_ok,
  wavescan_points,
  film_points,
});

const MODEL_POINTS: Record<string, ModelPoints> = {
  FTM: {
    plant_code: "FTM",
    models: [
      card("P703 DBL RANGER", 32, 98),
      card("P703 DBL RAPTOR", 32, 98),
      card("P703 RAPCAP", null, 93, "RAPCAP"),
      card("P703 SGL", null, 58, "Single CAP"),
    ],
    attachable_models: ["CX743", "P703 DBL SUPER DUTY"],
  },
  AAT: {
    plant_code: "AAT",
    models: [card("P703 DBL RANGER", 32, 94), card("P703 SGL", null, null, "Single CAP", false)],
    attachable_models: ["P703 DBL RAPTOR", "P703 RAPCAP"],
  },
};

async function setup(page: Page, { reloaded = [] as number[] } = {}) {
  await mockHistory(page, "admin");
  await page.route("**/api/v1/standards/catalogue", (r) => r.fulfill({ json: catalogueFixture }));
  await page.route("**/api/v1/plants/*/model-points", (r) => {
    const plant = new URL(r.request().url()).pathname.split("/")[4] ?? "";
    return r.fulfill({ json: MODEL_POINTS[plant.toUpperCase()] });
  });
  const writes: { url: string; body: unknown }[] = [];
  await page.route("**/api/v1/standards/plant-models**", (r) => {
    const body = r.request().postDataJSON() as Record<string, unknown>;
    writes.push({ url: new URL(r.request().url()).pathname, body });
    return r.request().url().endsWith("/offered")
      ? r.fulfill({ json: { is_offered: false, audit_id: 1 } })
      : r.fulfill({
          status: 201,
          // T115 (D-115-4): the held sheets this Attach reloaded.
          json: {
            plants: body.plants,
            audit_id: 2,
            reloaded_load_ids: reloaded,
            reload_refused: [],
          },
        });
  });
  return { writes };
}

test("T112-FIX Model cards: one design, Remove on every card, confirm before writing", async ({
  page,
}) => {
  // T112-FIX (D-112F-7): was "no Remove on Film-only"; every card is the same now.
  const { writes } = await setup(page);
  await page.goto("/plant/FTM?standardView=model");
  const series = page.getByRole("article").filter({ hasText: "4 models" });
  await expect(series.getByRole("heading", { name: "P703", exact: true })).toBeVisible();
  const items = series.getByRole("listitem");
  await expect(items).toHaveCount(4);

  for (const [code, line] of [
    ["P703 DBL RANGER", "Wave Scan 32 points · Film 98 points"],
    ["P703 DBL RAPTOR", "Wave Scan 32 points · Film 98 points"],
    ["P703 RAPCAP", "Film Thickness only · Film 93 points"],
    ["P703 SGL", "Film Thickness only · Film 58 points"],
  ]) {
    const item = items.filter({ hasText: code });
    // heading = model_code, then exactly one line, then Remove.
    await expect(item.locator("span.font-medium")).toHaveText(code);
    await expect(item.locator("span.text-muted-foreground")).toHaveText([line]);
    await expect(item.getByRole("button", { name: "Remove from FTM" })).toBeVisible();
    await expect(item).not.toContainText("zones");
  }
  // No display-name heading and no chip box anywhere (D-112F-7).
  await expect(series.getByText("RAPCAP", { exact: true })).toHaveCount(0);
  await expect(series.getByText("Single CAP", { exact: true })).toHaveCount(0);
  await expect(series.getByText("Film Thickness only", { exact: true })).toHaveCount(0);

  // Remove asks first (D-112F-8); Cancel writes nothing.
  const rapcap = items.filter({ hasText: "P703 RAPCAP" });
  await rapcap.getByRole("button", { name: "Remove from FTM" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(
    "New Wave Scan and Film files of P703 RAPCAP at FTM will be refused. Readings already loaded stay. Attach brings it back.",
  );
  await expect(dialog.getByRole("button", { name: "Remove", exact: true })).toBeVisible();
  await expect(dialog).toHaveCSS("opacity", "1"); // the open animation has finished
  await page.screenshot({ path: `${SHOTS}/T112-FIX-remove-confirm-desktop.png` });
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  expect(writes).toEqual([]);

  // Remove on a Film-only card calls the same endpoint as any other.
  await rapcap.getByRole("button", { name: "Remove from FTM" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(writes).toEqual([
    {
      url: "/api/v1/standards/plant-models/offered",
      body: { plant_code: "FTM", model_code: "P703 RAPCAP", is_offered: false },
    },
  ]);

  await page.getByRole("combobox", { name: "Attach existing model" }).click();
  await expect(page.getByRole("option")).toHaveText(["CX743", "P703 DBL SUPER DUTY"]);
  await page.keyboard.press("Escape");

  await page.screenshot({ path: `${SHOTS}/T112-FIX-model-cards-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(items).toHaveCount(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: `${SHOTS}/T112-FIX-model-cards-390.png`, fullPage: true });
});

test("T112-FIX Attach lists Film-only models; an attached one has no Film points yet", async ({
  page,
}) => {
  const { writes } = await setup(page);
  await page.goto("/plant/AAT?standardView=model");
  const sgl = page.getByRole("listitem").filter({ hasText: "P703 SGL" });
  await expect(sgl).toContainText("Film Thickness only · no Film points yet");
  await expect(sgl.getByRole("button", { name: "Remove from AAT" })).toBeVisible();

  await page.getByRole("combobox", { name: "Attach existing model" }).click();
  await expect(page.getByRole("option")).toHaveText(["P703 DBL RAPTOR", "P703 RAPCAP"]);
  await page.getByRole("option", { name: "P703 RAPCAP" }).click();
  await page.getByRole("button", { name: "Attach model" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(writes).toEqual([
    {
      url: "/api/v1/standards/plant-models",
      body: { model_code: "P703 RAPCAP", plants: ["AAT"] },
    },
  ]);
  // T115 (D-115-4): nothing was held, so no reload line.
  await expect(page.getByText(/held sheets? from the stored/)).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

// =====================================================================
// T115 (D-115-4, D-115-5)
// =====================================================================
test("T115 Attach says how many held sheets it reloaded", async ({ page }) => {
  await setup(page, { reloaded: [63101, 63102] });
  await page.goto("/plant/AAT?standardView=model");
  await page.getByRole("combobox", { name: "Attach existing model" }).click();
  await page.getByRole("option", { name: "P703 RAPCAP" }).click();
  await page.getByRole("button", { name: "Attach model" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "Reloaded" })).toHaveText(
    "Reloaded 2 held sheets from the stored files. They are back in review on Upload Data.",
  );
});

const MODEL_SENTENCE =
  "P703 DBL RANGER is not on FTM's list (it was removed, or never attached), so these rows " +
  "will not load. An Admin attaches it on Standard → Model; this file then loads by itself.";

test("T115 a held model row says Attach loads it, with nothing to pick", async ({ page }) => {
  const sheet = {
    ...workbookFixture.sheets[0],
    batch: { ...workbookFixture.sheets[0].batch, plant_code: "FTM", source_sheet: "Removed model" },
  };
  const book = {
    ...workbookFixture,
    plant_code: "FTM",
    source_file: "Removed model.xlsx",
    sheets: [sheet],
  };
  const held: components["schemas"]["HeldLabelGroup"][] = [
    {
      reason: "MODEL_NOT_OFFERED",
      column: "model",
      raw_value: "P703 DBL RANGER",
      count: 2,
      teachable_kind: null,
      candidates: [],
      display_group: "plant_offer",
      operator_message: MODEL_SENTENCE,
    },
  ];
  const row = (source_row: number, panel: string) => ({
    source_sheet: "Removed model",
    film_tail: false,
    source_row,
    panel_label: panel,
    checkzone: null,
    model_text: "P703 DBL RANGER",
    model: null,
    color_text: "Arctic White",
    color: "Arctic White",
    date_text: "7 June 2026",
    measured_date: "2026-06-07",
    outcome: "held_out" as const,
    operator_message: MODEL_SENTENCE,
  });
  const worksheet: components["schemas"]["WorksheetOut"] = {
    plant_code: "FTM",
    file_hash: fileHash,
    source_file: book.source_file,
    plant_question: null,
    extra_columns: [],
    missing_optional: [],
    missing_optional_message: null,
    ready_sheet_count: 0,
    rows_ready: 0,
    rows_held: 2,
    rows_already_in_history: 0,
    rows_need_confirmation: 0,
    summary_message: "0 readings ready to add, 2 held out.",
    checklist: [],
    load_button_label: "Yes, load these rows",
    sheets: [
      {
        load_id: sheet.batch.load_id,
        sheet: "Removed model",
        status: "PENDING_REVIEW",
        state: "needs_answer",
        commit_blockers: [],
        rows_ready: 0,
        rows_loaded: 0,
        rows_held: 2,
        rows_already_in_history: 0,
        rows_need_confirmation: 0,
        rows: [row(2, "RRHOOD"), row(3, "LFFENDER")],
        extra_columns: [],
        missing_optional: [],
        hole_rows: [],
        plant_texts: [],
        held,
        vehicle_count: 1,
        short_vehicles: [],
        operator_message: "Nothing on this sheet can load yet.",
      },
    ],
  };
  await mockHistory(page, "engineer");
  await page.route("**/api/v1/plants/FTM/workbooks?*", (r) =>
    r.fulfill({
      json: {
        plant_code: "FTM",
        plant_is_active: true,
        inbox: "all",
        uploaded_month: null,
        items: [book],
        page: { offset: 0, limit: 200, total: 1, returned: 1 },
      },
    }),
  );
  await page.route(`**/workbooks/${fileHash}`, (r) =>
    r.fulfill({
      json: { workbook: book, profiles: [], possible_replacements: [], acknowledgements: [] },
    }),
  );
  await page.route(`**/workbooks/${fileHash}/worksheet`, (r) => r.fulfill({ json: worksheet }));
  await page.route(`**/api/v1/batches/${sheet.batch.load_id}`, (r) =>
    r.fulfill({ json: { ...cleanReview, batch: sheet.batch, held_labels: held } }),
  );
  await page.goto(`/plant/ftm?file=${fileHash}`);
  const dialog = page.getByRole("dialog").first();
  await expect(dialog.getByRole("heading", { name: "Plant list" })).toBeVisible({ timeout: 20000 });
  await expect(dialog.getByText(MODEL_SENTENCE).first()).toBeVisible();
  await expect(dialog).not.toContainText("confirming adds it to the list");
  // D-115-5: nothing to pick or confirm for this hold, before and after T115.
  await expect(dialog.getByLabel(/Official catalogue|Choose model|Pick model/)).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/T115-held-model-row-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(dialog.getByText(MODEL_SENTENCE).first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/T115-held-model-row-390.png`, fullPage: true });
});
