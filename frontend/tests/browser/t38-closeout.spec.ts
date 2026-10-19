import { expect, test } from "@playwright/test";
import { catalogueFixture, cleanReview, identity, workspaceMeta } from "../fixtures";
import { workbookFixture } from "../workbook-fixtures";
import { mockHistory } from "../history-fixtures";
import { overviewPayload } from "../overview-fixtures";

const hash = "a".repeat(64);
const pageInfo = (total: number, offset = 0, returned = total) => ({
  offset,
  limit: 200,
  total,
  returned,
});

test("FTM publish updates its Standard and Overview while AAT stays unchanged", async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date("2026-09-28T08:00:00Z"));
  await mockHistory(page, "admin");
  let ftmFord = 70;
  const reads: string[] = [];
  const returned: { plant: string; ford: string | null; status: string | null }[] = [];
  await page.route("**/api/v1/standards/catalogue", (route) =>
    route.fulfill({
      json: {
        ...catalogueFixture,
        families: catalogueFixture.families.map((family) => ({
          ...family,
          plants: family.plants.map((plant) =>
            plant.plant_code === "FTM" ? { ...plant, ford_h: ftmFord } : plant,
          ),
        })),
      },
    }),
  );
  await page.route("**/api/v1/standards", (route) => {
    const body = route.request().postDataJSON();
    expect(body.plant_code).toBe("FTM");
    ftmFord = body.ford_h;
    return route.fulfill({ status: 201, json: { ...body } });
  });
  await page.route("**/api/v1/plants/*/wavescan/overview**", (route) => {
    const url = new URL(route.request().url());
    const plant = url.pathname.split("/")[4];
    reads.push(plant);
    const payload = overviewPayload(plant, url.searchParams.get("month"));
    payload.boxes = payload.boxes.map((box) =>
      box.family_code === "LS" && box.orient === "Horizontal"
        ? {
            ...box,
            ford: String(plant === "FTM" ? ftmFord : 65),
            status: plant === "FTM" && ftmFord > 75 ? "FAIL" : box.status,
          }
        : box,
    );
    returned.push({
      plant,
      ford: payload.boxes[0]?.ford ?? null,
      status: payload.boxes[0]?.status ?? null,
    });
    return route.fulfill({ json: payload });
  });
  const standardLine = () =>
    page
      .getByRole("region", { name: "P703 DBL RAPTOR" })
      .getByRole("region", { name: "P703 DBL RAPTOR Horizontal" })
      .locator('line[stroke="var(--nominal)"][stroke-dasharray="5 4"]')
      .first();
  await page.goto("/plant/AAT");
  await expect(standardLine()).toHaveAttribute("y1", /.+/);
  const aatBefore = await standardLine().getAttribute("y1");
  await page.goto("/plant/FTM");
  await expect(standardLine()).toHaveAttribute("y1", /.+/);
  const ftmBefore = await standardLine().getAttribute("y1");
  await page.getByRole("button", { name: "Standard", exact: true }).click();
  const card = page.locator('[data-family="MS"]');
  await expect(card).toContainText("70");
  await card.getByRole("button", { name: "Adjust standards" }).click();
  await card.getByLabel("Standard Horizontal").fill("77");
  await card.getByRole("button", { name: "Save standards" }).click();
  await expect(card).toContainText("77");
  await page.getByRole("button", { name: "Monthly Overview", exact: true }).click();
  await expect(page.locator("main")).toContainText("Arctic WhiteFail");
  await expect.poll(() => standardLine().getAttribute("y1")).not.toBe(ftmBefore);
  expect(
    returned.some(
      (entry) => entry.plant === "FTM" && entry.ford === "77" && entry.status === "FAIL",
    ),
  ).toBe(true);
  expect(reads).toContain("FTM");
  await page.goto("/plant/AAT");
  await expect(standardLine()).toHaveAttribute("y1", aatBefore!);
  await expect
    .poll(() =>
      returned.some(
        (entry) => entry.plant === "AAT" && entry.ford === "65" && entry.status === "WARNING",
      ),
    )
    .toBe(true);
  expect(reads).toContain("AAT");
});

test("Upload Data groups measured months, opens blocked mapping, closes progress, and X purges", async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date("2026-09-28T08:00:00Z"));
  await mockHistory(page, "admin");
  await page.route("**/api/v1/meta", (route) =>
    route.fulfill({
      json: {
        ...workspaceMeta,
        plants: [
          ...workspaceMeta.plants,
          {
            plant_code: "FTM",
            plant_name: "Ford Thailand Manufacturing",
            country: "Thailand",
            is_active: true,
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: { ...identity, principal: { ...identity.principal, roles: ["admin"] } },
    }),
  );
  const blockedSheet = {
    ...workbookFixture.sheets[0],
    batch: {
      ...cleanReview.batch,
      plant_code: "FTM",
      file_hash: hash,
      status: "REJECTED_TEMPLATE" as const,
      sheet_class: "WAVESCAN" as const,
    },
    committable: false,
    commit_blockers: ["UNKNOWN_TEMPLATE", "UNREVIEWED_HEADER"],
  };
  const may = {
    ...workbookFixture,
    file_hash: "c".repeat(64),
    plant_code: "FTM",
    source_file: "May CF.xlsx",
    measured_date_min: "2026-05-08",
    measured_date_max: "2026-05-12",
  };
  const remainder = { ...may, file_hash: "b".repeat(64), source_file: "May CF-remainder.xlsx" };
  const blocked = {
    ...workbookFixture,
    plant_code: "FTM",
    source_file: "Unknown layout.xlsx",
    measured_date_min: null,
    measured_date_max: null,
    sheets: [blockedSheet],
  };
  let purged = false;
  let purgeAttempts = 0;
  const reads: URL[] = [];
  await page.route("**/api/v1/plants/*/workbooks?*", (route) => {
    const url = new URL(route.request().url());
    reads.push(url);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const items = purged ? [may, remainder] : [blocked, may, remainder];
    return route.fulfill({
      json: {
        items: offset ? [] : items,
        page: pageInfo(items.length, offset, offset ? 0 : items.length),
        plant_code: "FTM",
        plant_is_active: true,
        inbox: "all",
        uploaded_month: null,
      },
    });
  });
  await page.route(`**/workbooks/${hash}`, (route) =>
    route.fulfill({
      json: { workbook: blocked, profiles: [], possible_replacements: [], acknowledgements: [] },
    }),
  );
  await page.route(`**/workbooks/${hash}/worksheet`, (route) =>
    route.fulfill({
      json: {
        plant_code: "FTM",
        file_hash: hash,
        source_file: blocked.source_file,
        plant_question: null,
        extra_columns: [],
        missing_optional: [],
        missing_optional_message: null,
        ready_sheet_count: 0,
        rows_ready: 0,
        rows_held: 0,
        rows_already_in_history: 0,
        summary_message: "Readings ready to review.",
        checklist: [],
        load_button_label: "Yes, load these rows",
        sheets: [
          {
            load_id: 123,
            sheet: "Review1",
            status: "REJECTED_TEMPLATE",
            state: "blocked",
            commit_blockers: ["UNKNOWN_TEMPLATE"],
            rows_ready: 0,
            rows_loaded: 0,
            rows_held: 0,
            rows_already_in_history: 0,
            rows: [],
            missing_optional: [],
            extra_columns: [],
            hole_rows: [],
            plant_texts: [],
            held: [],
            vehicle_count: 0,
            short_vehicles: [],
            operator_message: "This layout needs an Admin publish.",
          },
        ],
      },
    }),
  );
  await page.route(`**/workbooks/${hash}/issues`, (route) =>
    route.fulfill({ json: { file_hash: hash, plant_code: "FTM", issues: [] } }),
  );
  await page.route(`**/workbooks/${hash}/vehicles?*`, (route) =>
    route.fulfill({
      json: { file_hash: hash, plant_code: "FTM", load_id: 123, items: [], page: pageInfo(0) },
    }),
  );
  await page.route("**/mappings/proposals?*", (route) =>
    route.fulfill({ json: { items: [], page: pageInfo(0) } }),
  );
  await page.route("**/api/v1/uploads", (route) =>
    route.fulfill({
      status: 202,
      json: {
        batches: [
          {
            load_id: 123,
            filename: "Unknown layout.xlsx",
            sheet: "Review1",
            status: "REJECTED_TEMPLATE",
            detail: "Template not approved",
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/batches/123", (route) =>
    route.fulfill({ json: { ...cleanReview, batch: blockedSheet.batch, committable: false } }),
  );
  await page.route(`**/workbooks/${hash}/purge`, (route) => {
    expect(route.request().postDataJSON().reason).toBeTruthy();
    purgeAttempts++;
    if (purgeAttempts === 1)
      return route.fulfill({
        status: 409,
        json: {
          statusCode: 409,
          error: "Conflict",
          message: "Another file depends on this hash",
          correlationId: "dependency-check",
        },
      });
    purged = true;
    return route.fulfill({
      json: {
        plant_code: "FTM",
        file_hash: hash,
        reason: route.request().postDataJSON().reason,
        load_ids: [123],
      },
    });
  });
  await page.goto("/plant/FTM?dataView=upload");
  await expect(page.getByRole("heading", { name: "2026-05" })).toBeVisible();
  await expect(page.getByRole("article").filter({ hasText: "May CF.xlsx" })).toHaveCount(1);
  // T44: a separately stored remainder workbook keeps its own card (distinct file_hash).
  await expect(page.getByRole("article").filter({ hasText: "May CF-remainder.xlsx" })).toHaveCount(
    1,
  );
  expect(reads.some((url) => url.searchParams.get("inbox") === "all")).toBe(true);
  await page.getByLabel("Attach workbook", { exact: true }).setInputFiles({
    name: "Unknown layout.xlsx",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("fixture"),
  });
  // T40/T53 confirm-worksheet copy: a blocked layout is explained on its tab and in a
  // "Layout not approved" group (the old T38 sentence and heading were replaced).
  await expect(
    page
      .getByRole("dialog")
      .getByRole("region", { name: "Workbook tabs" })
      .getByText("This layout needs an Admin publish.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("dialog").getByRole("group", { name: "Layout not approved" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog").getByText("Uploading workbooks to FTM...")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Delete Unknown layout.xlsx" }).click();
  await expect(
    page
      .getByRole("dialog")
      .getByText("This permanently deletes this workbook and its rows from the database", {
        exact: false,
      }),
  ).toBeVisible();
  await page.getByLabel("Removal reason").fill("Wrong layout; remap on re-upload");
  await page.getByRole("button", { name: "Permanently delete workbook" }).click();
  await expect(
    page.getByText("Another file depends on this hash", { exact: true }).last(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Permanently delete workbook" }).click();
  await expect.poll(() => purged).toBe(true);
  await expect(page.getByRole("article").filter({ hasText: "Unknown layout.xlsx" })).toHaveCount(0);
});
