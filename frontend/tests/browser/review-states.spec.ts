import { expect, test } from "@playwright/test";
import { identity, workspaceMeta } from "../fixtures";
import { detailFixture, fileHash, workbookFixture } from "../workbook-fixtures";
test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/me", (r) =>
    r.fulfill({ json: { ...identity, principal: { ...identity.principal, roles: ["admin"] } } }),
  );
  await page.route("**/api/v1/meta", (r) => r.fulfill({ json: workspaceMeta }));
  await page.route(`**/workbooks/${fileHash}/issues`, (r) =>
    r.fulfill({ json: { file_hash: fileHash, plant_code: "AAT", issues: [] } }),
  );
  await page.route(`**/workbooks/${fileHash}/vehicles?*`, (r) =>
    r.fulfill({
      json: {
        file_hash: fileHash,
        plant_code: "AAT",
        load_id: 123,
        items: [],
        page: { offset: 0, limit: 200, total: 0, returned: 0 },
      },
    }),
  );
  await page.route("**/workbooks?*", (r) =>
    r.fulfill({
      json: {
        items: [workbookFixture],
        page: { offset: 0, limit: 200, total: 1, returned: 1 },
        plant_code: "AAT",
        plant_is_active: true,
      },
    }),
  );
  await page.route("**/mappings/proposals?*", (r) =>
    r.fulfill({ json: { items: [], page: { offset: 0, limit: 10, total: 0, returned: 0 } } }),
  );
});
test.skip("Processing workbook polls to FAILED (T40 replaced per-sheet commit control)", async ({
  page,
}) => {
  await page.clock.install();
  let reads = 0,
    failed = false;
  await page.route(`**/workbooks/${fileHash}`, (r) => {
    reads++;
    return r.fulfill({
      json: {
        ...detailFixture,
        workbook: {
          ...workbookFixture,
          sheets: [
            {
              ...workbookFixture.sheets[0],
              committable: false,
              commit_blockers: ["NOT_PENDING_REVIEW"],
              batch: {
                ...workbookFixture.sheets[0].batch,
                status: failed ? "FAILED" : "RUNNING",
                job: { status: failed ? "FAILED" : "RUNNING" },
              },
            },
          ],
        },
      },
    });
  });
  await page.goto(`/plant/aat?file=${fileHash}`);
  await page.getByText("Details", { exact: true }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByText(/Review1.*RUNNING/).first()).toBeVisible();
  failed = true;
  await page.clock.runFor(10000);
  await expect(sheet.getByText(/Review1.*FAILED/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeDisabled();
  const stopped = reads;
  await page.clock.runFor(60000);
  expect(reads).toBe(stopped);
});
test("leaving Upload Data review aborts an in-flight workbook poll and stops reads", async ({
  page,
}) => {
  await page.clock.install();
  let reads = 0,
    hold = false;
  let release = () => {};
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/workbooks/${fileHash}`, async (r) => {
    reads++;
    if (hold) await pending;
    await r
      .fulfill({
        json: {
          ...detailFixture,
          workbook: {
            ...workbookFixture,
            sheets: [
              {
                ...workbookFixture.sheets[0],
                committable: false,
                batch: {
                  ...workbookFixture.sheets[0].batch,
                  status: "RUNNING",
                  job: { status: "RUNNING" },
                },
              },
            ],
          },
        },
      })
      .catch(() => {});
  });
  await page.goto(`/plant/aat?file=${fileHash}`);
  await expect(page.getByRole("button", { name: "Close" })).toBeVisible();
  hold = true;
  const initial = reads;
  await page.clock.runFor(10000);
  await expect.poll(() => reads).toBeGreaterThan(initial);
  const aborted = page.waitForEvent("requestfailed", (request) =>
    request.url().endsWith(`/workbooks/${fileHash}`),
  );
  await page.getByRole("button", { name: "Close", exact: true }).click();
  expect((await aborted).failure()?.errorText).toContain("ABORTED");
  release();
  const stopped = reads;
  await page.clock.runFor(60000);
  expect(reads).toBe(stopped);
});
test.skip("failed workbook refresh hides stale commit controls (T40 replaced per-sheet commit control)", async ({
  page,
}) => {
  await page.route(`**/workbooks/${fileHash}`, (r) => r.fulfill({ json: detailFixture }));
  await page.goto(`/plant/aat?file=${fileHash}`);
  await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeEnabled();
  await page.route(`**/workbooks/${fileHash}`, (r) =>
    r.fulfill({
      status: 503,
      json: {
        statusCode: 503,
        error: "Unavailable",
        message: "Review service unavailable",
        correlationId: "t20-review-refresh",
      },
    }),
  );
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: "Refresh uploads" }).click();
  await page.getByRole("button", { name: "Review review.xlsx", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("t20-review-refresh");
  await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeDisabled();
});
for (const status of [400, 403, 409, 422])
  test(`upload HTTP ${status} preserves the envelope and does not fabricate success`, async ({
    page,
  }) => {
    await page.route("**/api/v1/uploads", (r) =>
      r.fulfill({
        status,
        json: {
          statusCode: status,
          error: "Refused",
          message: "Workbook refused by server",
          correlationId: `t20-upload-${status}`,
        },
      }),
    );
    await page.goto("/plant/aat?dataView=upload");
    // T111: T106 judgement call 4 - the plant Upload Data input is named
    // "Attach workbook"; "Upload workbooks" is the /batches intake screen.
    await page.getByLabel("Attach workbook", { exact: true }).setInputFiles({
      name: "bad.xlsx",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("mock bytes"),
    });
    await expect(page.getByRole("alert")).toContainText(`t20-upload-${status}`);
    await expect(page.getByRole("alert")).toContainText("Workbook refused by server");
    await expect(page.getByText("Upload accepted.", { exact: false })).toHaveCount(0);
  });
