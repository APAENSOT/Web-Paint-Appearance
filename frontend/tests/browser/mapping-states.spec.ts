import { expect, test } from "@playwright/test";
import { identity, workspaceMeta } from "../fixtures";
import { detailFixture, fileHash, workbookFixture } from "../workbook-fixtures";
import type { components } from "../../src/api/types";
const mapping: components["schemas"]["ProposalOut"] = {
  id: "test-proposal",
  load_id: 123,
  kind: "COLUMN",
  status: "PROPOSED",
  payload: { raw_header: "panel", logical_field: "checkzone" },
  similarity: "0.99",
  proposed_by: null,
  decided_by: null,
  created_at: "2026-09-13T00:00:00Z",
  decided_at: null,
};
const diagnostic = {
  ...mapping,
  id: "diagnostic",
  payload: { missing_required: ["model"], unrecognised_headers: ["truck"], after_replay: true },
};
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
  await page.route(`**/workbooks/${fileHash}`, (r) => r.fulfill({ json: detailFixture }));
  await page.route("**/mappings/proposals?*", (r) =>
    r.fulfill({
      json: { items: [mapping], page: { offset: 0, limit: 10, total: 1, returned: 1 } },
    }),
  );
});
async function open(page: import("@playwright/test").Page) {
  await page.goto(`/plant/aat?file=${fileHash}`);
  await page.getByText("Details", { exact: true }).click();
  await page.getByText("Mapping review", { exact: true }).click();
}
test.skip("Admin validates placeholders and submits exact ALIAS_MODEL payload (T40 moved mapping to worksheet)", async ({
  page,
}) => {
  let posts = 0;
  await page.route("**/mappings/proposals", (r) => {
    posts++;
    expect(r.request().postDataJSON()).toEqual({
      kind: "ALIAS_MODEL",
      load_id: 123,
      payload: {
        raw_value: "test truck spelling",
        model_code: "U704",
        note: "Verified against source",
      },
    });
    return r.fulfill({
      status: 422,
      json: {
        statusCode: 422,
        error: "Unprocessable Entity",
        message: "Mapping payload refused",
        correlationId: "t20-alias-validation",
      },
    });
  });
  await open(page);
  await page.getByLabel("Mapping kind", { exact: true }).selectOption("ALIAS_MODEL");
  await page.getByLabel("Raw model spelling", { exact: true }).fill("(none)");
  await page.getByLabel("Existing model code", { exact: true }).fill("U704");
  await page.getByRole("button", { name: "Propose mapping", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Placeholders remain quarantined");
  expect(posts).toBe(0);
  await page.getByLabel("Raw model spelling", { exact: true }).fill("test truck spelling");
  await page.getByLabel("Note (optional)", { exact: true }).fill("Verified against source");
  await page.getByRole("button", { name: "Propose mapping", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("t20-alias-validation");
  expect(posts).toBe(1);
});
for (const terminal of ["PENDING_REVIEW", "REJECTED_TEMPLATE"] as const)
  test.skip(`Admin replay polls to ${terminal} and never commits (T40 replaced per-sheet review)`, async ({
    page,
  }) => {
    await page.clock.install();
    let approved = false,
      terminalReady = false,
      reads = 0,
      commits = 0;
    await page.route(`**/workbooks/${fileHash}`, (r) => {
      reads++;
      const status = approved ? (terminalReady ? terminal : "RUNNING") : "REJECTED_TEMPLATE";
      return r.fulfill({
        json: {
          ...detailFixture,
          workbook: {
            ...workbookFixture,
            sheets: [
              {
                ...workbookFixture.sheets[0],
                committable: terminalReady && terminal === "PENDING_REVIEW",
                batch: {
                  ...workbookFixture.sheets[0].batch,
                  status,
                  job: { status: status === "RUNNING" ? "RUNNING" : "DONE" },
                },
              },
            ],
          },
        },
      });
    });
    await page.route("**/mappings/proposals?*", (r) =>
      r.fulfill({
        json: {
          items:
            terminalReady && terminal === "REJECTED_TEMPLATE"
              ? [diagnostic]
              : [{ ...mapping, status: approved ? "APPROVED" : "PROPOSED" }],
          page: { offset: 0, limit: 10, total: 1, returned: 1 },
        },
      }),
    );
    await page.route("**/batches/*/commit", (r) => {
      commits++;
      return r.fulfill({ json: {} });
    });
    await page.route("**/mappings/proposals/test-proposal/approve", (r) => {
      expect(r.request().postData()).toBeNull();
      approved = true;
      return r.fulfill({
        json: {
          proposal: { ...mapping, status: "APPROVED" },
          replay: {
            load_id: 123,
            status: "RUNNING",
            previous_status: "REJECTED_TEMPLATE",
            cleared: {},
            job_id: 1,
          },
          applied_to: "ref_column_alias",
          audit_action: "mapping.approve",
          note: "No measurement written",
        },
      });
    });
    await open(page);
    await page.getByRole("button", { name: "Approve & replay", exact: true }).click();
    const sheet = page.getByRole("dialog");
    await expect(sheet.getByText(/Review1.*RUNNING/).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeDisabled();
    terminalReady = true;
    await page.clock.runFor(10000);
    await expect(sheet.getByText(new RegExp(`Review1.*${terminal}`)).first()).toBeVisible();
    if (terminal === "PENDING_REVIEW")
      await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeEnabled();
    else {
      await expect(sheet.getByText("Header diagnostic", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeDisabled();
    }
    const stopped = reads;
    await page.clock.runFor(60000);
    expect(reads).toBe(stopped);
    expect(commits).toBe(0);
  });
test("Admin submits exact COLUMN keys and long diagnostics wrap on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/mappings/proposals?*", (r) =>
    r.fulfill({
      json: {
        items: [
          {
            ...diagnostic,
            payload: { ...diagnostic.payload, unrecognised_headers: ["long_header".repeat(20)] },
          },
        ],
        page: { limit: 10, offset: 0, total: 1, returned: 1 },
      },
    }),
  );
  let posts = 0;
  await page.route("**/mappings/proposals", (r) => {
    posts++;
    expect(r.request().postDataJSON()).toEqual({
      kind: "COLUMN",
      load_id: 123,
      payload: { raw_header: "panel", logical_field: "checkzone", note: "Checked workbook header" },
    });
    return r.fulfill({ status: 201, json: mapping });
  });
  await open(page);
  await expect(page.getByRole("button", { name: "Approve & replay", exact: true })).toHaveCount(0);
  await page.getByLabel("Raw header", { exact: true }).fill("panel");
  await page.getByLabel("Logical field", { exact: true }).selectOption("checkzone");
  await page.getByLabel("Note (optional)", { exact: true }).fill("Checked workbook header");
  await page.getByRole("button", { name: "Propose mapping", exact: true }).click();
  await expect(page.getByText("Proposal recorded.", { exact: false })).toBeVisible();
  expect(posts).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
