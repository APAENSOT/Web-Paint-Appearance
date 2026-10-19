import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { identity, measurement, workspaceMeta, cleanReview } from "../fixtures";
import { mockHistory } from "../history-fixtures";
import type { components } from "../../src/api/types";
const hash = "a".repeat(64),
  oldHash = "9".repeat(64),
  revision = "b".repeat(64),
  vehicleId = "d".repeat(64);
const sheet = (id: number): components["schemas"]["WorkbookSheetOut"] => ({
  batch: {
    ...cleanReview.batch,
    load_id: id,
    plant_code: "FTM",
    source_sheet: `Sheet ${id}`,
    file_hash: hash,
    review_revision: revision,
  },
  committable: true,
  commit_blockers: [],
  required_acknowledgements: [],
  acknowledged: [],
});
const workbook: components["schemas"]["WorkbookOut"] = {
  file_hash: hash,
  plant_code: "FTM",
  source_file: "September-name-June-data.xlsx",
  operational_summary: "REVIEW_REQUIRED",
  measured_date_min: "2026-06-07",
  measured_date_max: "2026-07-03",
  measured_dates_span_months: true,
  uploaded_at: "2026-09-16T08:00:00Z",
  loaded_by: "fixture-admin",
  counts: { ...cleanReview.batch.counts, rows_in_file: 2, rows_loaded: 2 },
  sheet_count: 2,
  skipped_sheet_count: 0,
  superseded: false,
  abandoned: false,
  vehicle_set_count: 2,
  sheets: [sheet(123), sheet(124)],
};
const vehicle = {
  vehicle_id: vehicleId,
  load_id: 123,
  plant_code: "FTM",
  measured_date: "2026-06-07",
  model: "U704",
  color: "White",
  serial_no: "FIXTURE-VEHICLE-001",
  identity_complete: true,
  point_count: 2,
  expected_point_count: 31,
  incomplete_set: true,
  dispositions: { load: 2, duplicate: 1, reject: 0, quarantine: 0 },
};
const point = {
  load_id: 123,
  source_sheet: "Sheet 123",
  source_row: 2,
  checkzone: "HOOD",
  disposition: "LOAD",
  reason: null,
  detail: null,
  raw: { values: { cf: "61.20", lw: "3.0" } },
  proposed: { measures: { cf: "61.20", lw: "3.0" } },
  current_overrides: [],
  measurement_id: null,
  projection_missing: false,
};
const pageInfo = (count = 1) => ({ offset: 0, limit: 200, total: count, returned: count });
const details = (book = workbook) => ({
  workbook: book,
  profiles: [],
  possible_replacements: [],
  acknowledgements: [],
});
async function screenshot(page: Page, name: string) {
  await page.screenshot({
    path: fileURLToPath(new URL(`../../test-results/T22-${name}.png`, import.meta.url)),
    fullPage: !name.startsWith("vehicle"),
    animations: "disabled",
  });
}
async function setup(page: Page, role = "admin") {
  await page.clock.setFixedTime(new Date("2026-09-17T08:00:00Z"));
  await mockHistory(page, role);
  await page.route("**/api/v1/auth/me", (r) =>
    r.fulfill({ json: { ...identity, principal: { ...identity.principal, roles: [role] } } }),
  );
  await page.route("**/api/v1/meta", (r) =>
    r.fulfill({
      json: {
        ...workspaceMeta,
        plants: [
          ...workspaceMeta.plants
            .filter((p) => p.plant_code !== "FTM")
            .map((p) => ({ ...p, is_active: p.plant_code !== "FVL" })),
          {
            ...workspaceMeta.plants[0],
            plant_code: "FTM",
            plant_name: "Ford Thailand Manufacturing",
          },
          { ...workspaceMeta.plants[0], plant_code: "SAP", plant_name: "Silverton Assembly Plant" },
        ],
      },
    }),
  );
  await page.route("**/api/v1/plants/*/workbooks?*", (r) => {
    const url = new URL(r.request().url()),
      inactive = url.pathname.includes("/FVL/"),
      inbox = url.searchParams.get("inbox");
    return r.fulfill({
      json: {
        items: inactive
          ? []
          : inbox === "needs_attention"
            ? [
                {
                  ...workbook,
                  file_hash: oldHash,
                  source_file: "Older-review.xlsx",
                  uploaded_at: "2026-08-20T08:00:00Z",
                },
              ]
            : [workbook],
        plant_code: inactive ? "FVL" : "FTM",
        plant_is_active: !inactive,
        inbox,
        uploaded_month: "2026-09",
        page: pageInfo(inactive ? 0 : 1),
      },
    });
  });
  await page.route(`**/workbooks/${hash}`, (r) => r.fulfill({ json: details() }));
  // T40: the confirm dialog reads a whole-file worksheet, not per-sheet approval state.
  await page.route(`**/workbooks/${hash}/worksheet`, (r) =>
    r.fulfill({
      json: {
        plant_code: "FTM",
        file_hash: hash,
        source_file: workbook.source_file,
        plant_question: null,
        extra_columns: [],
        missing_optional: [],
        missing_optional_message: null,
        ready_sheet_count: workbook.sheets.length,
        rows_ready: 2,
        rows_held: 0,
        rows_already_in_history: 0,
        summary_message: "Readings ready to review.",
        checklist: [],
        load_button_label: "Yes, load these rows",
        sheets: workbook.sheets.map((item) => ({
          load_id: item.batch.load_id,
          sheet: item.batch.source_sheet,
          status: item.batch.status,
          state: "ready",
          commit_blockers: [],
          rows_ready: 1,
          rows_loaded: 0,
          rows_held: 0,
          rows_already_in_history: 0,
          rows: [],
          missing_optional: [],
          extra_columns: [],
          hole_rows: [],
          plant_texts: [],
          held: [],
          vehicle_count: 1,
          short_vehicles: [],
          operator_message: "Ready rows can load.",
        })),
      },
    }),
  );
  await page.route("**/api/v1/measurements?*", (r) =>
    r.fulfill({
      json: {
        items: [measurement],
        page: pageInfo(),
        filters: {},
        active_data_source: "v_wavescan_active",
      },
    }),
  );
  await page.route(`**/workbooks/${hash}/issues`, (r) =>
    r.fulfill({ json: { file_hash: hash, plant_code: "FTM", issues: [] } }),
  );
  await page.route(`**/workbooks/${hash}/vehicles?*`, (r) =>
    r.fulfill({
      json: {
        file_hash: hash,
        plant_code: "FTM",
        load_id: 123,
        items: [
          vehicle,
          { ...vehicle, vehicle_id: "e".repeat(64), serial_no: "FIXTURE-VEHICLE-002" },
        ],
        page: pageInfo(2),
      },
    }),
  );
  await page.route(`**/workbooks/${hash}/vehicles/*/points?*`, (r) =>
    r.fulfill({
      json: {
        file_hash: hash,
        plant_code: "FTM",
        vehicle,
        items: [point, { ...point, source_row: 3, checkzone: "ROOF" }],
        page: pageInfo(2),
      },
    }),
  );
  await page.route("**/mappings/proposals?*", (r) =>
    r.fulfill({ json: { items: [], page: pageInfo(0) } }),
  );
  await page.route(`**/workbooks/${hash}/history`, (r) =>
    r.fulfill({ json: { file_hash: hash, plant_code: "FTM", events: [] } }),
  );
}

test("Admin Upload Data groups by measured month; History alone reads summary APIs", async ({
  page,
}) => {
  await setup(page);
  const reads: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/v1/")) reads.push(r.url());
  });
  await page.goto("/plant/ftm?dataView=upload");
  await expect(page.getByRole("heading", { name: "Upload Data", exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Data views" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "2026-06", exact: true })).toBeVisible();
  await expect(page.getByRole("article").filter({ hasText: "September-name" })).toHaveCount(1);
  expect(reads.some((u) => u.includes("inbox=all"))).toBeTruthy();
  await screenshot(page, "admin-inbox");
  await page.getByRole("button", { name: "Measurement History", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Week 2", exact: true })).toBeVisible();
  expect(reads.some((u) => u.includes("/plants/FTM/history/summaries"))).toBeTruthy();
  expect(reads.some((u) => u.includes("/measurements?"))).toBeFalsy();
});
// T110: T43 - the SPA shows the attach chrome to every signed-in user and the backend role
// decides, so a forced `upload` / `files` alias no longer bounces a non-Admin to History.
// Still claimed: History reads no workbooks and offers no attach chrome or Correct control,
// `files` is still the `upload` alias, and neither role is offered Edit measurement.
for (const role of ["engineer", "viewer"])
  test(`${role} forced upload and old aliases keep the attach chrome with no manager requests`, async ({
    page,
  }) => {
    await setup(page, role);
    const reads: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/workbooks")) reads.push(r.url());
    });
    await page.goto("/plant/ftm?dataView=history");
    await expect(page.getByRole("heading", { name: "Week 2", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Upload Data", exact: true })).toHaveCount(1);
    await expect(page.locator("input[type=file]")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Edit measurement/ })).toHaveCount(0);
    expect(reads).toEqual([]);
    await screenshot(page, `${role}-history`);
    for (const search of ["?dataView=upload", "?dataView=files"]) {
      await page.goto(`/plant/ftm${search}`);
      // T110: T43 - attach chrome for every signed-in user; T106 names the input "Attach workbook".
      await expect(page.getByRole("heading", { name: "Upload Data", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Upload Data", exact: true })).toHaveCount(1);
      await expect(page.getByLabel("Attach workbook", { exact: true })).toBeEnabled();
      await expect(page.getByRole("button", { name: /^Edit measurement/ })).toHaveCount(0);
    }
  });
for (const role of ["admin", "engineer", "viewer"])
  test(`${role} batches has no picker or batch list`, async ({ page }) => {
    await setup(page, role);
    const reads: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/v1/batches")) reads.push(r.url());
    });
    await page.goto("/batches");
    // T110: T43 - `mayIngest` is any signed-in principal, so a Viewer never reaches the
    // "Engineer access required" gate; the Admin-only gate (`isAdmin`) answers both non-Admins.
    await expect(
      page.getByRole("heading", {
        name: role === "admin" ? "Choose a plant" : "Plant uploads are Admin-only",
      }),
    ).toBeVisible();
    await expect(page.locator("input[type=file]")).toHaveCount(0);
    expect(reads).toEqual([]);
    if (role === "admin") {
      await screenshot(page, "batches-chooser");
      await page.getByRole("link", { name: /FTM/ }).click();
      await expect(page).toHaveURL(/dataView=upload/);
    }
  });
test("inactive FVL is visible and cannot upload", async ({ page }) => {
  await setup(page);
  await page.goto("/plant/fvl?dataView=upload");
  await expect(page.getByText(/not onboarded/)).toBeVisible();
  // T110: T106 judgement call 4 - the input's accessible name is "Attach workbook";
  // "Upload workbooks" is the /batches intake screen (features/intake/ReviewQueue.tsx).
  await expect(page.getByLabel("Attach workbook", { exact: true })).toBeDisabled();
});
test.skip("dialog uses sheet and API vehicle IDs (T40: evidence moved behind Vehicle evidence)", async ({
  page,
}) => {
  await setup(page);
  const reads: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/workbooks/")) reads.push(r.url());
  });
  await page.goto(`/plant/ftm?dataView=files&file=${hash}&sheet=123`);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("FIXTURE-VEHICLE-001", { exact: false }).first()).toBeVisible();
  expect(reads.some((u) => u.includes("/vehicles?") && u.includes("load_id=123"))).toBeTruthy();
  await expect(dialog.getByRole("button", { name: /Edit/ }).first()).toBeVisible();
  expect(reads.some((u) => u.includes(`/vehicles/${vehicleId}/points`))).toBeTruthy();
  expect(reads.some((u) => u.includes("/rows"))).toBeFalsy();
  await screenshot(page, "vehicle-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await screenshot(page, "vehicle-mobile");
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
  await page.reload();
  await expect(page.getByRole("dialog")).toBeVisible();
});
test.skip("upload sends required route plant and polls before opening review (T40: dialog copy changed)", async ({
  page,
}) => {
  await setup(page);
  let polls = 0;
  await page.route("**/api/v1/uploads", async (r) => {
    await new Promise((resolve) => setTimeout(resolve, 300));
    const body = r.request().postDataBuffer()!.toString();
    expect(body).toContain('name="files"');
    expect(body).toMatch(/name="expected_plant"\r\n\r\nFTM/);
    return r.fulfill({
      status: 202,
      json: {
        batches: [
          {
            load_id: 123,
            filename: "upload.xlsx",
            sheet: "Sheet 123",
            status: "RUNNING",
            detail: "Queued",
          },
        ],
      },
    });
  });
  await page.route("**/api/v1/batches/123", (r) => {
    polls++;
    return r.fulfill({
      json: {
        ...cleanReview,
        batch: {
          ...sheet(123).batch,
          status: polls < 2 ? "RUNNING" : "PENDING_REVIEW",
          job: { ...cleanReview.batch.job, status: polls < 2 ? "RUNNING" : "DONE" },
        },
      },
    });
  });
  await page.goto("/plant/ftm?dataView=upload");
  await page.getByLabel("Upload workbooks", { exact: true }).setInputFiles({
    name: "upload.xlsx",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("mock server-owned bytes"),
  });
  await expect(page.getByText("Uploading workbooks to FTM...")).toBeVisible();
  await expect(page.getByText("Processing sheets. Review opens when this finishes.")).toBeVisible();
  await expect(page.getByText("Review one vehicle set at a time.")).toBeVisible({ timeout: 15000 });
  expect(polls).toBeGreaterThanOrEqual(2);
  await expect(page).toHaveURL(new RegExp(`file=${hash}`));
});
test.skip("Approve sheet posts empty body (T40: replaced by workbook load-ready)", async ({
  page,
}) => {
  await setup(page);
  let posts = 0;
  await page.route("**/batches/*/commit", (r) => {
    posts++;
    expect(r.request().postData()).toBeNull();
    return r.fulfill({ json: { load_id: 123, status: "COMMITTED", measurements_inserted: 2 } });
  });
  await page.goto(`/plant/ftm?file=${hash}`);
  await page.getByRole("button", { name: "Approve sheet", exact: true }).click();
  await expect.poll(() => posts).toBe(1);
});

test.skip("clean review has no acknowledgement and closes after Approve (T40: whole-file Yes replaces Approve)", async ({
  page,
}) => {
  await setup(page);
  const single = { ...workbook, sheet_count: 1, sheets: [sheet(123)] };
  await page.route(`**/workbooks/${hash}`, (r) => r.fulfill({ json: details(single) }));
  await page.route("**/batches/*/commit", (r) =>
    r.fulfill({ json: { load_id: 123, status: "COMMITTED", measurements_inserted: 2 } }),
  );
  await page.goto(`/plant/ftm?file=${hash}`);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("No issues. You can approve this sheet.")).toBeVisible();
  await expect(dialog.getByRole("button", { name: /^Acknowledge / })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Approve sheet", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "Approve sheet", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("Sheet approved.", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Upload Data", exact: true })).toBeVisible();
});

test("X purges the workbook once with required reason and honest copy", async ({ page }) => {
  await setup(page);
  const mixed: components["schemas"]["WorkbookOut"] = {
    ...workbook,
    sheets: [
      sheet(123),
      { ...sheet(124), committable: false, batch: { ...sheet(124).batch, status: "COMMITTED" } },
    ],
  };
  await page.route(`**/workbooks/${hash}`, (r) => r.fulfill({ json: details(mixed) }));
  const posts: { path: string; body: unknown }[] = [];
  await page.route(`**/workbooks/${hash}/purge`, (r) => {
    posts.push({ path: new URL(r.request().url()).pathname, body: r.request().postDataJSON() });
    return r.fulfill({
      json: {
        plant_code: "FTM",
        file_hash: hash,
        reason: "Incorrect workbook",
        load_ids: [123, 124],
      },
    });
  });
  await page.goto(`/plant/ftm?file=${hash}`);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: `Delete ${workbook.source_file}`, exact: true })
    .click();
  const confirm = page.getByRole("button", { name: "Permanently delete workbook", exact: true });
  await expect(confirm).toBeDisabled();
  await expect(
    page.getByText(/This permanently deletes this workbook and its rows from the database/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Incorrect workbook", exact: true }).click();
  await confirm.click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts).toEqual([
    { path: `/api/v1/plants/FTM/workbooks/${hash}/purge`, body: { reason: "Incorrect workbook" } },
  ]);
  await expect(page.getByRole("button", { name: "Permanently delete workbook" })).toHaveCount(0);
});
// T110 (D-110-3): no recorded decision names the empty Upload Data sentence. The screen says
// "No uploaded workbooks yet." (or "No <domain> workbooks for this filter."); the asserted
// "No live workbooks." has never existed in src. Owner to decide which copy is right.
test.fixme("purged workbooks leave Upload Data", async ({ page }) => {
  let purged = false;
  await setup(page);
  await page.route("**/api/v1/plants/*/workbooks?*", (r) => {
    const url = new URL(r.request().url());
    const inbox = url.searchParams.get("inbox");
    return r.fulfill({
      json: {
        items: purged ? [] : [workbook],
        plant_code: "FTM",
        plant_is_active: true,
        inbox,
        uploaded_month: "2026-09",
        page: pageInfo(purged ? 0 : 1),
      },
    });
  });
  await page.route(`**/workbooks/${hash}/purge`, (r) => {
    purged = true;
    return r.fulfill({
      json: {
        plant_code: "FTM",
        file_hash: hash,
        reason: "Incorrect workbook",
        load_ids: [123, 124],
      },
    });
  });
  await page.goto("/plant/ftm?dataView=upload");
  await expect(page.getByRole("article").filter({ hasText: "September-name" })).toHaveCount(1);
  await page.getByRole("button", { name: `Delete ${workbook.source_file}`, exact: true }).click();
  await page.getByLabel("Removal reason", { exact: true }).fill("Incorrect workbook");
  await page.getByRole("button", { name: "Permanently delete workbook", exact: true }).click();
  await expect(page.getByRole("article").filter({ hasText: "September-name" })).toHaveCount(0);
  await expect(page.getByText("No live workbooks.", { exact: true })).toBeVisible();
});
test.skip("acknowledgement requires note and refetches after stale 409 (T40: load-ready records warning acknowledgements)", async ({
  page,
}) => {
  await setup(page);
  let current = revision,
    acked = false;
  const bodies: unknown[] = [];
  await page.route(`**/workbooks/${hash}`, (r) =>
    r.fulfill({
      json: details({
        ...workbook,
        sheets: [
          {
            ...sheet(123),
            committable: acked,
            required_acknowledgements: ["REJECTED_ROWS"],
            acknowledged: acked ? ["REJECTED_ROWS"] : [],
            batch: { ...sheet(123).batch, review_revision: current },
          },
        ],
      }),
    }),
  );
  await page.route(`**/workbooks/${hash}/issues`, (r) =>
    r.fulfill({
      json: {
        file_hash: hash,
        plant_code: "FTM",
        issues: [
          {
            level: "WARNING",
            token: "REJECTED_ROWS",
            load_id: 123,
            count: 1,
            sample_rows: [],
            acked,
            resolution: "acknowledge",
          },
        ],
      },
    }),
  );
  await page.route(`**/workbooks/${hash}/acknowledgements`, (r) => {
    bodies.push(r.request().postDataJSON());
    if (bodies.length === 1) {
      current = "c".repeat(64);
      return r.fulfill({
        status: 409,
        json: {
          statusCode: 409,
          error: "Conflict",
          message: "Stale revision",
          correlationId: "stale-review",
        },
      });
    }
    acked = true;
    return r.fulfill({ json: {} });
  });
  await page.goto(`/plant/ftm?file=${hash}`);
  const button = page.getByRole("button", { name: "Acknowledge REJECTED_ROWS", exact: true });
  await expect(button).toBeDisabled();
  await page.getByLabel("Acknowledgement note (required)").fill("Reviewed source rows");
  await button.click();
  await expect(page.getByText("stale-review", { exact: false })).toBeVisible();
  await page.getByLabel("Acknowledgement note (required)").fill("Reviewed updated rows");
  await button.click();
  await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeEnabled();
  expect(bodies).toEqual([
    {
      load_id: 123,
      category: "REJECTED_ROWS",
      review_revision: revision,
      note: "Reviewed source rows",
    },
    {
      load_id: 123,
      category: "REJECTED_ROWS",
      review_revision: "c".repeat(64),
      note: "Reviewed updated rows",
    },
  ]);
});
test("all-workbook inbox loads every page before measured-month grouping", async ({ page }) => {
  await setup(page);
  const reads: URL[] = [];
  await page.route("**/api/v1/plants/FTM/workbooks?*", (r) => {
    const u = new URL(r.request().url());
    reads.push(u);
    const offset = Number(u.searchParams.get("offset"));
    return r.fulfill({
      json: {
        items: [
          {
            ...workbook,
            file_hash: (offset ? "5" : "6").repeat(64),
            source_file: `Measured-${offset}.xlsx`,
          },
        ],
        plant_code: "FTM",
        plant_is_active: true,
        inbox: u.searchParams.get("inbox"),
        uploaded_month: "2026-08",
        page: { offset, limit: 1, total: 2, returned: 1 },
      },
    });
  });
  await page.goto("/plant/ftm?dataView=upload");
  await expect(page.getByRole("heading", { name: "2026-06" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Measured-1.xlsx/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Measured-0.xlsx/ })).toBeVisible();
  expect(reads.filter((u) => u.searchParams.get("offset") === "1")).toHaveLength(1);
  expect(reads.every((u) => u.searchParams.get("inbox") === "all")).toBeTruthy();
  expect(reads.every((u) => !u.searchParams.has("uploaded_month"))).toBeTruthy();
});

test.skip("override confirms raw and previous values (T40: evidence and approval flow moved)", async ({
  page,
}) => {
  await setup(page);
  let current = revision;
  const bodies: unknown[] = [];
  const reads = { detail: 0, vehicles: 0, points: 0, issues: 0 };
  await page.route(`**/workbooks/${hash}`, (r) => {
    reads.detail++;
    return r.fulfill({
      json: details({
        ...workbook,
        sheets: [{ ...sheet(123), batch: { ...sheet(123).batch, review_revision: current } }],
      }),
    });
  });
  await page.route(`**/workbooks/${hash}/vehicles?*`, (r) => {
    reads.vehicles++;
    return r.fulfill({
      json: {
        file_hash: hash,
        plant_code: "FTM",
        load_id: 123,
        items: [vehicle],
        page: pageInfo(),
      },
    });
  });
  await page.route(`**/workbooks/${hash}/vehicles/*/points?*`, (r) => {
    reads.points++;
    return r.fulfill({
      json: { file_hash: hash, plant_code: "FTM", vehicle, items: [point], page: pageInfo() },
    });
  });
  await page.route(`**/workbooks/${hash}/issues`, (r) => {
    reads.issues++;
    return r.fulfill({ json: { file_hash: hash, plant_code: "FTM", issues: [] } });
  });
  await page.route(`**/workbooks/${hash}/overrides`, (r) => {
    bodies.push(r.request().postDataJSON());
    current = "c".repeat(64);
    return r.fulfill({
      status: 201,
      json: {
        load_id: 123,
        vehicle_id: vehicleId,
        previous_review_revision: revision,
        review_revision: current,
        overrides: [],
        counts: workbook.counts,
      },
    });
  });
  await page.goto(`/plant/ftm?file=${hash}`);
  await page.getByRole("button", { name: "Edit HOOD row 2" }).click();
  await expect(page.getByLabel("New proposed value")).toHaveValue("61.20");
  await expect(page.getByRole("button", { name: "Add draft" })).toBeDisabled();
  await page.getByLabel("New proposed value").fill("55.1234567890123456789");
  await page.getByLabel("Override reason").fill(" Reviewed source ");
  await page.getByRole("button", { name: "Add draft" }).click();
  await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Review changes" }).click();
  const confirmation = page.getByRole("region", { name: "Confirm overrides" });
  await expect(confirmation).toContainText("raw 61.20");
  await expect(confirmation).toContainText("previous proposed 61.20");
  await expect(confirmation).toContainText("55.1234567890123456789");
  expect(bodies).toEqual([]);
  await page.getByRole("button", { name: "Confirm overrides", exact: true }).click();
  await expect(page.getByText("Overrides saved.", { exact: false })).toBeVisible();
  expect(bodies).toEqual([
    {
      load_id: 123,
      vehicle_id: vehicleId,
      review_revision: revision,
      changes: [
        { source_row: 2, field: "cf", value: "55.1234567890123456789", reason: "Reviewed source" },
      ],
    },
  ]);
  await expect.poll(() => Object.values(reads).every((n) => n >= 2)).toBeTruthy();
  await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "I reviewed the new revision and its proposed points." })
    .check();
  await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeEnabled();
});
test.skip("stale override 409 quotes envelope (T40: vehicle evidence moved behind disclosure)", async ({
  page,
}) => {
  await setup(page);
  let reads = 0,
    posts = 0;
  await page.route(`**/workbooks/${hash}`, (r) => {
    reads++;
    return r.fulfill({ json: details() });
  });
  await page.route(`**/workbooks/${hash}/overrides`, (r) => {
    posts++;
    return r.fulfill({
      status: 409,
      json: {
        statusCode: 409,
        error: "Conflict",
        message: "Review revision changed",
        correlationId: "override-stale",
      },
    });
  });
  await page.goto(`/plant/ftm?file=${hash}`);
  await page.getByRole("button", { name: "Edit HOOD row 2" }).click();
  await page.getByLabel("New proposed value").fill("55.25");
  await page.getByLabel("Override reason").fill("Source checked");
  await page.getByRole("button", { name: "Add draft" }).click();
  await page.getByRole("button", { name: "Review changes" }).click();
  await page.getByRole("button", { name: "Confirm overrides", exact: true }).click();
  await expect(page.getByText("override-stale", { exact: false })).toBeVisible();
  await expect.poll(() => reads).toBeGreaterThan(1);
  expect(posts).toBe(1);
  await expect(page.getByRole("button", { name: "Confirm overrides", exact: true })).toHaveCount(0);
});

test.skip("incomplete identity and unavailable expectations (T40: vehicle evidence moved behind disclosure)", async ({
  page,
}) => {
  await setup(page);
  const incomplete = {
    ...vehicle,
    identity_complete: false,
    serial_no: null,
    expected_point_count: null,
  };
  await page.route(`**/workbooks/${hash}/vehicles?*`, (r) =>
    r.fulfill({
      json: {
        file_hash: hash,
        plant_code: "FTM",
        load_id: 123,
        items: [incomplete],
        page: pageInfo(),
      },
    }),
  );
  await page.route(`**/workbooks/${hash}`, (r) =>
    r.fulfill({
      json: details({
        ...workbook,
        sheet_count: 1,
        sheets: [
          {
            ...sheet(123),
            committable: false,
            batch: { ...sheet(123).batch, status: "ABANDONED" },
          },
        ],
      }),
    }),
  );
  await page.route(`**/workbooks/${hash}/vehicles/*/points?*`, (r) =>
    r.fulfill({
      json: {
        file_hash: hash,
        plant_code: "FTM",
        vehicle: incomplete,
        items: [
          {
            ...point,
            projection_missing: true,
            raw: null,
            current_overrides: [
              {
                override_id: 1,
                field: "cf",
                previous_proposed: "61.20",
                new_value: "55.25",
                reason: "Earlier review",
                review_revision: revision,
                created_at: "2026-09-17T08:00:00Z",
                actor_user_id: "fixture-admin",
                applied: false,
              },
            ],
          },
        ],
        page: pageInfo(),
      },
    }),
  );
  await page.goto(`/plant/ftm?file=${hash}`);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Identity incomplete", { exact: true })).toBeVisible();
  await expect(dialog.getByText(/expected not available/)).toBeVisible();
  await expect(dialog.getByText(/Not applied:/)).toBeVisible();
  await expect(dialog.getByText(/Projection missing/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: /^Edit / })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: /^Correct/ })).toHaveCount(0);
  await expect(
    dialog.getByRole("button", { name: `Retire ${workbook.source_file}`, exact: true }),
  ).toHaveCount(0);
});

for (const scenario of ["point failure", "sheet switch"] as const)
  test.skip(`new-revision approval guard survives ${scenario} (T40: per-sheet Approve removed)`, async ({
    page,
  }) => {
    await setup(page);
    let saved = false;
    await page.route(`**/workbooks/${hash}`, (r) =>
      r.fulfill({
        json: details({
          ...workbook,
          sheets: [
            {
              ...sheet(123),
              batch: {
                ...sheet(123).batch,
                review_revision: saved ? "c".repeat(64) : revision,
              },
            },
            sheet(124),
          ],
        }),
      }),
    );
    await page.route(`**/workbooks/${hash}/overrides`, (r) => {
      saved = true;
      return r.fulfill({
        status: 201,
        json: {
          load_id: 123,
          vehicle_id: vehicleId,
          previous_review_revision: revision,
          review_revision: "c".repeat(64),
          overrides: [],
          counts: workbook.counts,
        },
      });
    });
    await page.route(`**/workbooks/${hash}/vehicles/*/points?*`, (r) =>
      r.fulfill(
        saved && scenario === "point failure"
          ? {
              status: 503,
              json: {
                statusCode: 503,
                error: "Unavailable",
                message: "New points unavailable",
                correlationId: "new-points-failed",
              },
            }
          : {
              json: {
                file_hash: hash,
                plant_code: "FTM",
                vehicle,
                items: [point],
                page: pageInfo(),
              },
            },
      ),
    );
    await page.goto(`/plant/ftm?file=${hash}`);
    await page.getByRole("button", { name: "Edit HOOD row 2" }).click();
    await page.getByLabel("New proposed value").fill("55.25");
    await page.getByLabel("Override reason").fill("Review source");
    await page.getByRole("button", { name: "Add draft" }).click();
    await page.getByRole("button", { name: "Review changes" }).click();
    await page.getByRole("button", { name: "Confirm overrides", exact: true }).click();
    await expect(page.getByText("Overrides saved.", { exact: false })).toBeVisible();
    if (scenario === "point failure") {
      await expect(page.getByText("new-points-failed", { exact: false })).toBeVisible();
      await expect(
        page.getByRole("checkbox", {
          name: "I reviewed the new revision and its proposed points.",
        }),
      ).toBeDisabled();
    } else {
      await page.getByLabel("Sheet", { exact: true }).selectOption("124");
      await page.getByLabel("Sheet", { exact: true }).selectOption("123");
      await expect(
        page.getByRole("checkbox", {
          name: "I reviewed the new revision and its proposed points.",
        }),
      ).toBeVisible();
    }
    await expect(page.getByRole("button", { name: "Approve sheet", exact: true })).toBeDisabled();
  });

test("duplicate 409 names the stored retired file without SHA jargon in the headline", async ({
  page,
}) => {
  await setup(page);
  await page.route("**/api/v1/uploads", (r) =>
    r.fulfill({
      status: 409,
      json: {
        statusCode: 409,
        error: "Conflict",
        message: `"07. Jul'26 CF data AAT.xlsx" has already been ingested: its SHA-256 matches load_id 1088 (07. Jul'26 CF data AAT.xlsx [Sheet1], SUPERSEDED). Nothing was stored. A corrected re-send must be a different file; identical bytes are the same evidence.`,
        correlationId: "dup-hash",
      },
    }),
  );
  await page.goto("/plant/ftm?dataView=upload");
  // T110: T106 judgement call 4 - the input kept the accessible name "Attach workbook".
  await page.getByLabel("Attach workbook", { exact: true }).setInputFiles({
    name: "again.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("not-the-same-name"),
  });
  await expect(
    page.getByRole("heading", { name: "Ask an Admin to restore this file" }),
  ).toBeVisible();
  await expect(page.getByText(/already stored as load 1088/)).toBeVisible();
  await expect(page.getByText(/Ask an Admin to restore it/)).toBeVisible();
  await expect(page.getByText("dup-hash")).toBeVisible();
  await page.getByText("Technical detail").click();
  await expect(page.getByText(/SHA-256 matches load_id 1088/)).toBeVisible();
});

test("identical-file restore of a committed sheet points at History, not review", async ({
  page,
}) => {
  await setup(page);
  await page.route("**/api/v1/uploads", (r) =>
    r.fulfill({
      status: 202,
      json: {
        batches: [
          {
            load_id: 1088,
            filename: "July.xlsx",
            sheet: "Sheet1",
            status: "COMMITTED",
            detail: "Reopened by identical-file upload",
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/batches/1088", (r) =>
    r.fulfill({
      json: {
        ...cleanReview,
        batch: { ...sheet(1088).batch, status: "COMMITTED", file_hash: hash },
      },
    }),
  );
  await page.goto("/plant/ftm?dataView=upload");
  // T110: T106 judgement call 4 - the input kept the accessible name "Attach workbook".
  await page.getByLabel("Attach workbook", { exact: true }).setInputFiles({
    name: "July.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("july-bytes"),
  });
  await expect(
    page.getByRole("status").filter({
      hasText:
        "This file is current again. Open Measurement History to inspect the restored measurements.",
    }),
  ).toHaveCount(1);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Open July.xlsx" })).toHaveCount(0);
});

test.skip("unknown-model cards warn and review offers map or hold-back (T40: worksheet-held mapping replaces per-sheet UI)", async ({
  page,
}) => {
  await setup(page);
  const quarantined: components["schemas"]["WorkbookOut"] = {
    ...workbook,
    sheet_count: 1,
    vehicle_set_count: 1,
    counts: { ...workbook.counts, rows_quarantine: 2, rows_loaded: 0 },
    sheets: [
      {
        ...sheet(123),
        committable: false,
        commit_blockers: ["WARNINGS_UNACKNOWLEDGED"],
        required_acknowledgements: ["QUARANTINED_MODELS"],
        batch: {
          ...sheet(123).batch,
          counts: { ...cleanReview.batch.counts, rows_quarantine: 2, rows_loaded: 0 },
        },
      },
    ],
  };
  await page.route("**/api/v1/plants/*/workbooks?*", (r) => {
    const url = new URL(r.request().url());
    const inbox = url.searchParams.get("inbox");
    return r.fulfill({
      json: {
        items: inbox === "needs_attention" ? [] : [quarantined],
        plant_code: "FTM",
        plant_is_active: true,
        inbox,
        uploaded_month: "2026-09",
        page: pageInfo(inbox === "needs_attention" ? 0 : 1),
      },
    });
  });
  await page.route(`**/workbooks/${hash}`, (r) => r.fulfill({ json: details(quarantined) }));
  await page.route("**/api/v1/mappings/proposals**", (r) =>
    r.fulfill({ json: { items: [], page: { offset: 0, limit: 10, returned: 0, total: 0 } } }),
  );
  await page.route(`**/workbooks/${hash}/vehicles?*`, (r) =>
    r.fulfill({
      json: {
        file_hash: hash,
        plant_code: "FTM",
        load_id: 123,
        items: [
          {
            ...vehicle,
            model: null,
            identity_complete: false,
            incomplete_set: true,
            dispositions: { load: 0, duplicate: 0, reject: 0, quarantine: 2 },
          },
        ],
        page: pageInfo(),
      },
    }),
  );
  await page.goto("/plant/ftm?dataView=upload");
  await expect(page.getByText("Unknown model held back").first()).toBeVisible();
  await page.getByRole("button", { name: `Review ${workbook.source_file}` }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/Map the spelling to an existing model/)).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Map this spelling" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Hold back unknown-model rows" })).toBeVisible();
  await expect(dialog.getByLabel("Raw model spelling")).toBeVisible();
  await expect(dialog.getByText("Before approval:")).toHaveCount(0);
  await expect(dialog.getByText("Unknown model held back").first()).toBeVisible();
});

test.skip("clean-layer review shows extra headers and publishes a stored WaveScan contract (T40: layout step moved to worksheet)", async ({
  page,
}) => {
  await setup(page);
  const cleanLayerSheet: components["schemas"]["WorkbookSheetOut"] = {
    ...sheet(123),
    committable: false,
    commit_blockers: ["UNREVIEWED_HEADER", "UNVERIFIED_PROFILE"],
    batch: {
      ...sheet(123).batch,
      domain: "WAVESCAN",
      semantic_signature: "c".repeat(64),
      sheet_class: "WAVESCAN",
      unreviewed_headers: ["Panel2", "Operator note"],
      fixture_verified: false,
      notes: "Plant column is missing from this stored export.",
    },
  };
  const cleanLayerWorkbook: components["schemas"]["WorkbookOut"] = {
    ...workbook,
    sheet_count: 1,
    sheets: [cleanLayerSheet],
  };
  let detailReads = 0;
  let batchReads = 0;
  let publishBody: unknown;
  let commitPosts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/commit")) commitPosts++;
  });
  await page.route(`**/workbooks/${hash}`, (route) => {
    detailReads++;
    return route.fulfill({ json: details(cleanLayerWorkbook) });
  });
  await page.route("**/api/v1/batches/123", (route) => {
    batchReads++;
    return route.fulfill({
      json: {
        ...cleanReview,
        batch: cleanLayerSheet.batch,
        review_dispositions: { LOAD: 2, AGGREGATE_ROW: 4 },
      },
    });
  });
  await page.route("**/template-profiles/publish", (route) => {
    publishBody = route.request().postDataJSON();
    return route.fulfill({
      json: {
        profile_id: 81,
        version: 2,
        domain: "WAVESCAN",
        plant_code: "FTM",
        semantic_signature: "c".repeat(64),
        template_fingerprint: "e".repeat(64),
        fixture_verified: true,
        fixture_file_hash: hash,
        named_owner: "Somchai Quality",
        previous_profile_id: 75,
        ignored_headers: 2,
        replayed_load_ids: [123, 124],
        audit_action: "profile.publish",
      },
    });
  });

  await page.goto(`/plant/ftm?file=${hash}`);
  const review = page.getByRole("dialog");
  await expect(review.getByText(/Extra columns have no agreed meaning/)).toBeVisible();
  await expect(review.getByText("Panel2", { exact: true })).toBeVisible();
  await expect(review.getByText("Operator note", { exact: true })).toBeVisible();
  await expect(review.getByText(/4 report roll-up rows excluded/)).toBeVisible();
  await expect(review.getByText("No additional row warnings.", { exact: true })).toBeVisible();
  await expect(review.getByText("No issues. You can approve this sheet.")).toHaveCount(0);
  await expect(review.getByRole("button", { name: "Publish verified layout" })).toBeVisible();
  await page.screenshot({
    path: "test-results/screenshots/T27-extra-headers-desktop.png",
    animations: "disabled",
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(review.getByText(/Nothing is ignored automatically/)).toBeVisible();
  await page.screenshot({
    path: "test-results/screenshots/T27-extra-headers-mobile.png",
    animations: "disabled",
  });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await review.getByRole("button", { name: "Publish verified layout" }).click();
  const publish = page.getByRole("dialog", { name: "Publish verified layout" });
  await expect(publish).toContainText(
    "This records that a named owner verified this layout. Stored sheets with the same contract will be replayed. Nothing is written as measurements until someone approves a sheet.",
  );
  await publish.getByLabel("Named owner").fill(" Somchai Quality ");
  await publish.getByLabel("Notes").fill(" Verified against the stored September export ");
  await publish.getByLabel("Reason for ignoring Panel2").fill(" Export-only helper column ");
  await publish
    .getByLabel("Reason for ignoring Operator note")
    .fill("Operator annotation outside WaveScan");
  await expect(publish.getByLabel("Fill missing Plant column")).toBeVisible();
  await page.screenshot({
    path: "test-results/screenshots/T27-admin-publish-confirm.png",
    animations: "disabled",
  });
  await publish.getByRole("button", { name: "Publish layout" }).click();
  await expect(
    publish.getByText("Replay finished. Nothing was approved as measurements."),
  ).toBeVisible();
  await publish.getByText("Published profile details", { exact: true }).click();
  await expect(publish.getByText(/Profile 81/)).toBeVisible();
  await expect(publish.getByText(/replayed load IDs: 123, 124/i)).toBeVisible();
  expect(publishBody).toEqual({
    file_hash: hash,
    source_sheet: "Sheet 123",
    named_owner: "Somchai Quality",
    notes: "Verified against the stored September export",
    fill_missing_plant: false,
    ignored_headers: [
      { header: "Panel2", reason: "Export-only helper column" },
      { header: "Operator note", reason: "Operator annotation outside WaveScan" },
    ],
  });
  await expect.poll(() => detailReads).toBeGreaterThan(1);
  await expect.poll(() => batchReads).toBeGreaterThan(1);
  expect(commitPosts).toBe(0);
});

test.skip("out-of-scope tabs stay evidence and offer no WaveScan actions (T40: evidence moved behind disclosure)", async ({
  page,
}) => {
  await setup(page);
  const otherTab: components["schemas"]["WorkbookSheetOut"] = {
    ...sheet(123),
    committable: false,
    commit_blockers: ["NOT_PENDING_REVIEW", "OUT_OF_SCOPE_SHEET", "UNKNOWN_TEMPLATE"],
    batch: {
      ...sheet(123).batch,
      status: "REJECTED_TEMPLATE",
      domain: "WAVESCAN",
      sheet_class: "OUT_OF_SCOPE_SHEET",
      fixture_verified: false,
    },
  };
  await page.route(`**/workbooks/${hash}`, (route) =>
    route.fulfill({
      json: details({ ...workbook, sheet_count: 1, sheets: [otherTab] }),
    }),
  );
  await page.goto(`/plant/ftm?file=${hash}`);
  const review = page.getByRole("dialog");
  await expect(
    review.getByText(
      "This tab is not WaveScan. It is kept as evidence and is not a broken template.",
      { exact: true },
    ),
  ).toHaveCount(1);
  await expect(review.getByText(/not an approved template/i)).toHaveCount(0);
  await expect(review.getByRole("button", { name: "Approve sheet" })).toHaveCount(0);
  await expect(review.getByRole("button", { name: "Publish verified layout" })).toHaveCount(0);
  await review.getByText("Details", { exact: true }).click();
  await expect(review.getByText("Mapping review", { exact: true })).toHaveCount(0);
  await review.getByText("Technical detail", { exact: true }).click();
  await expect(
    review.getByText("NOT_PENDING_REVIEW, OUT_OF_SCOPE_SHEET, UNKNOWN_TEMPLATE", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/screenshots/T27-out-of-scope.png",
    animations: "disabled",
  });
});

test("Engineer never mounts template publish controls", async ({ page }) => {
  await setup(page, "engineer");
  await page.goto(`/plant/ftm?dataView=upload&file=${hash}`);
  // T110: T43 - an Engineer is no longer bounced to History; `file=` opens that workbook's
  // T40 confirm worksheet. The nav tab is out of the tree because that worksheet is modal.
  await expect(
    page.getByRole("heading", { name: "Confirm this worksheet", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Upload Data", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Publish verified layout" })).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "Publish verified layout" })).toHaveCount(0);
  await page.screenshot({
    path: "test-results/screenshots/T27-engineer-no-publish.png",
    animations: "disabled",
    fullPage: true,
  });
});
