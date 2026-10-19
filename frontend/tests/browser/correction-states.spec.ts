import { expect, test } from "@playwright/test";
import { cleanReview, identity, measurement } from "../fixtures";
import { historyPoint, historyPoints, mockHistory, openHistoryPoint } from "../history-fixtures";

const replacement = {
  ...measurement,
  lw: measurement.lw!,
  sw: measurement.sw!,
  doi: measurement.doi!,
  du: measurement.du!,
  wa: measurement.wa!,
  wb: measurement.wb!,
  wc: measurement.wc!,
  wd: measurement.wd!,
  we: measurement.we!,
  measurement_id: 42,
  cf: "62.1234567890123456789",
  corrects_measurement_id: 41,
  correction_reason: "Instrument check",
};
const result = {
  measurement: replacement,
  superseded_measurement_id: 41,
  supersession_id: 7,
  audit_action: "measurement.correct",
  note: "Original retained.",
};
test.beforeEach(async ({ page }) => {
  await mockHistory(page);
});

test("form rejects invalid values, submits only changed keys, and removes retired ID before delayed refetch", async ({
  page,
}) => {
  let posted = false;
  let release = () => {};
  const waiting = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/history/vehicles/*/points?*", async (route) => {
    if (posted) await waiting;
    await route.fulfill({
      json: historyPoints(posted ? { ...historyPoint, ...replacement } : historyPoint),
    });
  });
  await page.route("**/api/v1/measurements/41/corrections", async (route) => {
    expect(new URL(route.request().url()).search).toBe("");
    expect(route.request().postDataJSON()).toEqual({
      reason: "Instrument check",
      cf: replacement.cf,
    });
    posted = true;
    await route.fulfill({ status: 200, json: result });
  });
  await openHistoryPoint(page);
  await page.getByRole("button", { name: "Edit measurement 41", exact: true }).click();
  const form = page.getByRole("form", { name: "Correct measurement 41", exact: true });
  await form.getByLabel("Reason for correction").fill(" Instrument check ");
  await form.getByRole("button", { name: "Create correction", exact: true }).click();
  await expect(form.getByRole("alert")).toContainText("Change at least one value");
  await form.getByLabel("CF", { exact: false }).fill("101");
  await form.getByRole("button", { name: "Create correction", exact: true }).click();
  await expect(form.getByRole("alert")).toContainText("between 0 and 100");
  expect(posted).toBe(false);
  for (const key of [
    "plant",
    "model",
    "checkzone",
    "color",
    "tolerance_group",
    "paintline",
    "load_id",
    "source_sheet",
    "source_row",
  ]) {
    await expect(form.locator(`[name="${key}"]`)).toHaveCount(0);
  }
  await form.getByLabel("CF", { exact: false }).fill(replacement.cf);
  await form.getByRole("button", { name: "Create correction", exact: true }).click();
  await expect(page.locator('[data-measurement-id="41"]')).toHaveCount(0);
  await expect(page.getByText("Loading vehicle points...")).toBeVisible();
  release();
  await expect(page.locator('[data-measurement-id="42"]')).toBeVisible();
  await expect(page.locator('[data-measurement-id="41"]')).toHaveCount(0);
  await expect(page.getByText("Vehicle points", { exact: true })).toBeVisible();
});

for (const response of [200, 404, 409] as const)
  test(`${response} followed by a failed refresh never renders retired ID or retries correction`, async ({
    page,
  }) => {
    let writes = 0;
    await page.route("**/history/vehicles/*/points?*", (route) =>
      route.fulfill(
        writes
          ? {
              status: 503,
              json: {
                statusCode: 503,
                error: "Unavailable",
                message: "Refresh unavailable",
                correlationId: "t09-refresh",
              },
            }
          : { json: historyPoints() },
      ),
    );
    await page.route("**/api/v1/measurements/41/corrections", (route) => {
      writes++;
      return route.fulfill({
        status: response,
        json:
          response === 200
            ? result
            : {
                statusCode: response,
                error: response === 409 ? "Conflict" : "Not Found",
                message:
                  response === 409
                    ? "Measurement 41 already retired; replaced by measurement 42"
                    : "Measurement 41 was not found",
                correlationId: `t09-${response === 409 ? "retired" : "missing"}`,
              },
      });
    });
    await openHistoryPoint(page);
    await page.getByRole("button", { name: "Edit measurement 41", exact: true }).click();
    await page.getByLabel("CF", { exact: false }).fill("63");
    await page.getByLabel("Reason for correction").fill("Instrument check");
    await page.getByRole("button", { name: "Create correction", exact: true }).click();
    await expect(page.getByText("Refresh unavailable")).toBeVisible();
    await expect(page.locator('[data-measurement-id="41"]')).toHaveCount(0);
    if (response !== 200) {
      await expect(
        page.getByText(
          response === 409
            ? "Measurement 41 already retired; replaced by measurement 42"
            : "Measurement 41 was not found",
        ),
      ).toBeVisible();
      await expect(
        page.getByText(`Correlation ID: t09-${response === 409 ? "retired" : "missing"}`),
      ).toBeVisible();
    }
    expect(writes).toBe(1);
  });

test("mobile correction is usable and Viewer stays read-only", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openHistoryPoint(page);
  await page.getByRole("button", { name: "Edit measurement 41", exact: true }).click();
  await expect(page.getByLabel("Reason for correction")).toBeVisible();
  const formBounds = await page
    .getByRole("form", { name: "Correct measurement 41", exact: true })
    .boundingBox();
  expect(formBounds!.x + formBounds!.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/t09-correction-mobile.png", fullPage: true });
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: { ...identity, principal: { ...identity.principal, roles: ["viewer"] } },
    }),
  );
  await page.reload();
  await expect(page.getByText("Read only", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Edit measurement/ })).toHaveCount(0);
  await expect(page.getByRole("form", { name: /^Correct measurement/ })).toHaveCount(0);
});

for (const refreshFails of [false, true])
  test.skip(`Admin supersedes from Upload Data review (refresh fails: ${refreshFails}; T40 moved vehicle evidence)`, async ({
    page,
  }) => {
    const hash = "a".repeat(64);
    let retired = false;
    let writes = 0;
    const batch = () => ({
      ...cleanReview.batch,
      status: retired ? "SUPERSEDED" : "COMMITTED",
      file_hash: hash,
      fixture_verified: true,
      review_revision: "b".repeat(64),
    });
    const workbook = () => ({
      file_hash: hash,
      plant_code: "AAT",
      source_file: "review.xlsx",
      operational_summary: retired ? "SUPERSEDED" : "ACTIVE",
      measured_date_min: "2026-09-01",
      measured_date_max: "2026-09-01",
      uploaded_at: "2026-09-13T00:00:00Z",
      loaded_by: "fixture-admin",
      counts: cleanReview.batch.counts,
      sheet_count: 1,
      superseded: retired,
      sheets: [
        {
          batch: batch(),
          committable: false,
          commit_blockers: ["NOT_PENDING_REVIEW"],
          required_acknowledgements: [],
          acknowledged: [],
        },
      ],
    });
    await page.route("**/api/v1/auth/me", (route) =>
      route.fulfill({
        json: { ...identity, principal: { ...identity.principal, roles: ["admin"] } },
      }),
    );
    await page.route("**/api/v1/plants/AAT/workbooks?*", (route) =>
      route.fulfill({
        json: {
          items: [workbook()],
          plant_code: "AAT",
          plant_is_active: true,
          page: { limit: 200, offset: 0, total: 1, returned: 1 },
        },
      }),
    );
    await page.route(`**/api/v1/plants/AAT/workbooks/${hash}`, (route) =>
      route.fulfill(
        retired && refreshFails
          ? {
              status: 503,
              json: {
                statusCode: 503,
                error: "Unavailable",
                message: "Workbook refresh unavailable",
                correlationId: "t20-workbook-refresh",
              },
            }
          : {
              json: {
                workbook: workbook(),
                profiles: [],
                possible_replacements: [],
                acknowledgements: [],
              },
            },
      ),
    );
    await page.route("**/api/v1/batches/123/supersede", (route) => {
      writes++;
      expect(route.request().postDataJSON()).toEqual({ reason: "Wrong workbook" });
      retired = true;
      return route.fulfill({
        json: {
          load_id: 123,
          status: "SUPERSEDED",
          previous_status: "COMMITTED",
          superseded_by: null,
          reason: "Wrong workbook",
          measurements_hidden: 1,
          audit_action: "batch.supersede",
        },
      });
    });

    await page.goto(`/plant/AAT?dataView=files&file=${hash}`);
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Retire review.xlsx", exact: true })
      .click();
    await expect(page.getByRole("button", { name: "Confirm retire" })).toBeDisabled();
    await page.getByLabel("Removal reason", { exact: true }).fill(" Wrong workbook ");
    await page.getByRole("button", { name: "Confirm retire", exact: true }).click();
    expect(writes).toBe(1);
    await expect(
      page.getByText(
        "Retired from active reads. Original records retained. Re-upload the same file to continue this batch.",
        { exact: true },
      ),
    ).toBeVisible();
    if (refreshFails) {
      await expect(page.getByText("Workbook refresh unavailable")).toBeVisible();
      await expect(page.getByText("Correlation ID: t20-workbook-refresh")).toBeVisible();
    } else {
      await expect(
        page.getByText("Review1: Retired from active reads", { exact: false }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Retire review.xlsx", exact: true }),
      ).toHaveCount(0);
    }
  });
