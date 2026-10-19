import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { createApiClient } from "../../src/api/client";
import type { components } from "../../src/api/types";

const engineerApi = process.env.T09_API_URL ?? "http://127.0.0.1:8016";
const adminUi = process.env.T09_ADMIN_FRONTEND ?? "http://localhost:5174";
const viewerApi = process.env.T09_VIEWER_API ?? "http://127.0.0.1:8018";
const viewerUi = process.env.T09_VIEWER_FRONTEND ?? "http://localhost:5175";

test.skip(
  process.env.T20_CORRECTION_LIVE_RUN !== "1",
  "Requires dedicated Engineer/Admin/Viewer services and a disposable live database; this test performs writes.",
);

async function rows(request: APIRequestContext) {
  const response = await request.get(`${engineerApi}/api/v1/measurements?plant=AAT&limit=200`);
  expect(response.status()).toBe(200);
  return ((await response.json()) as components["schemas"]["MeasurementPage"]).items;
}

async function openHistoryRow(
  page: Page,
  request: APIRequestContext,
  api: string,
  ui: string,
  row: components["schemas"]["MeasurementOut"],
) {
  const month = row.measured_date.slice(0, 7);
  const summaries = (await (
    await request.get(`${api}/api/v1/plants/AAT/history/summaries`, {
      params: { month, model: row.model, color: row.color },
    })
  ).json()) as components["schemas"]["HistorySummariesOut"];
  const week = summaries.weeks.find(
    (item) =>
      item.measured_date_min <= row.measured_date &&
      item.measured_date_max >= row.measured_date &&
      item.cards.some((card) => card.model === row.model && card.color === row.color),
  )?.week;
  expect(week).toBeDefined();
  const vehicles = (await (
    await request.get(`${api}/api/v1/plants/AAT/history/vehicles`, {
      params: { month, week: week!, model: row.model, color: row.color, limit: 200, offset: 0 },
    })
  ).json()) as components["schemas"]["HistoryVehiclePage"];
  const vehicle = vehicles.items.find(
    (item) =>
      item.load_id === row.load_id &&
      item.serial_no === row.serial_no &&
      item.measured_date === row.measured_date,
  );
  expect(vehicle).toBeDefined();
  const query = new URLSearchParams({
    dataView: "history",
    month,
    model: row.model,
    color: row.color,
    week: String(week),
    vehicle: vehicle!.vehicle_id,
  });
  await page.goto(`${ui}/plant/AAT?${query}`);
  await expect(page.locator(`[data-measurement-id="${row.measurement_id}"]`)).toBeVisible();
}

test("live Engineer corrects active data; Admin supersedes through Upload Data; Viewer stays read-only", async ({
  page,
  browser,
  request,
}) => {
  test.setTimeout(120000);
  const serial = `T20COR-${randomUUID().slice(0, 12)}`;
  const buffer = execFileSync(
    process.env.T09_PYTHON ?? path.resolve("../backend/.venv/Scripts/python.exe"),
    ["-B", path.resolve("tests/make-workbook.py"), serial, "2", "AAT"],
  );
  const upload = await request.post(`${engineerApi}/api/v1/uploads`, {
    multipart: {
      expected_plant: "AAT",
      files: {
        name: `${serial}.xlsx`,
        mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        buffer,
      },
    },
  });
  expect(upload.status()).toBe(202);
  const accepted = (await upload.json()) as components["schemas"]["UploadAccepted"];
  expect(accepted.batches).toHaveLength(2);
  let fileHash = "";
  for (const uploaded of accepted.batches) {
    for (;;) {
      const response = await request.get(`${engineerApi}/api/v1/batches/${uploaded.load_id}`);
      const review = (await response.json()) as components["schemas"]["BatchReviewOut"];
      fileHash = review.batch.file_hash;
      if (review.batch.status !== "RUNNING") {
        expect(review.committable).toBe(true);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    expect(
      (await request.post(`${engineerApi}/api/v1/batches/${uploaded.load_id}/commit`)).status(),
    ).toBe(200);
  }

  const [correctBatch, retireBatch] = accepted.batches.map((sheet) => sheet.load_id);
  const before = await rows(request);
  const original = before.find((row) => row.load_id === correctBatch)!;
  const separate = before.find((row) => row.load_id === retireBatch)!;
  await openHistoryRow(page, request, engineerApi, "", original);
  await page
    .getByRole("button", { name: `Edit measurement ${original.measurement_id}`, exact: true })
    .click();
  await page.getByRole("textbox", { name: /^CF\b/ }).fill("62.1234567890123456789");
  await page.getByLabel("Reason for correction").fill("T20 live instrument verification");
  const correction = page.waitForResponse((response) =>
    response.url().endsWith(`/measurements/${original.measurement_id}/corrections`),
  );
  await page.getByRole("button", { name: "Create correction", exact: true }).click();
  const result = (await (await correction).json()) as components["schemas"]["CorrectionResult"];
  await expect(page.locator(`[data-measurement-id="${original.measurement_id}"]`)).toHaveCount(0);

  await expect(
    createApiClient(engineerApi).supersede(retireBatch, { reason: "Engineer refusal check" }),
  ).rejects.toMatchObject({ status: 403 });
  const admin = await browser.newPage();
  await admin.goto(`${adminUi}/plant/AAT?dataView=upload&file=${fileHash}`);
  await admin
    .getByRole("dialog")
    .getByRole("button", { name: `Retire ${serial}.xlsx`, exact: true })
    .click();
  await admin.getByLabel("Removal reason", { exact: true }).fill("T22 separate sheet retirement");
  const supersede = admin.waitForResponse((response) =>
    response.url().endsWith(`/batches/${retireBatch}/supersede`),
  );
  await admin.getByRole("button", { name: "Confirm retire", exact: true }).click();
  expect((await supersede).status()).toBe(200);
  await expect(admin.getByText(/Original records retained/)).toBeVisible();

  const viewer = await browser.newPage();
  await openHistoryRow(viewer, request, viewerApi, viewerUi, result.measurement);
  await expect(viewer.getByRole("button", { name: "Upload Data", exact: true })).toHaveCount(0);
  await expect(viewer.getByRole("button", { name: /^Edit measurement/ })).toHaveCount(0);
  await expect(
    createApiClient(viewerApi).correct(result.measurement.measurement_id, {
      reason: "Viewer refusal check",
      cf: "63",
    }),
  ).rejects.toMatchObject({ status: 403 });
  await admin.close();
  await viewer.close();
  expect((await rows(request)).some((row) => row.measurement_id === separate.measurement_id)).toBe(
    false,
  );
});
