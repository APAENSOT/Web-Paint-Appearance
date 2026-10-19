import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import type { components } from "../../src/api/types";

const apiBase = process.env.T20_ADMIN_API_URL ?? "http://127.0.0.1:8017";
const workbook = (serial: string, sheets = 1, plant = "AAT") =>
  execFileSync(process.env.T20_PYTHON ?? path.resolve("../backend/.venv/Scripts/python.exe"), [
    path.resolve("tests/make-workbook.py"),
    serial,
    String(sheets),
    plant,
  ]);
const mimeType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

test.skip(
  process.env.T20_ADMIN_LIVE_RUN !== "1",
  "Requires the dedicated Admin API/UI and disposable live database; this test performs writes.",
);

test("live Admin uploads from plant Upload Data with route scope and commits sheets independently", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const me = (await (
    await request.get(`${apiBase}/api/v1/auth/me`)
  ).json()) as components["schemas"]["MeResponse"];
  expect(me.principal.roles).toContain("admin");
  const serial = `T22-${randomUUID().slice(0, 10)}`;
  const buffer = workbook(serial, 2);
  const filename = `${serial}.xlsx`;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/plant/AAT?dataView=upload");
  const acceptedResponse = page.waitForResponse(
    (response) => response.url().endsWith("/uploads") && response.request().method() === "POST",
  );
  // T111: T106 judgement call 4 - the plant Upload Data input is named
  // "Attach workbook"; "Upload workbooks" is the /batches intake screen.
  await page
    .getByLabel("Attach workbook", { exact: true })
    .setInputFiles({ name: filename, mimeType, buffer });
  const response = await acceptedResponse;
  expect(response.status()).toBe(202);
  const posted = response.request().postDataBuffer()?.toString();
  if (posted) expect(posted).toMatch(/name="expected_plant"\r\n\r\nAAT/);
  const accepted = (await response.json()) as components["schemas"]["UploadAccepted"];
  expect(accepted.batches).toHaveLength(2);

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 30000 });
  await expect(dialog.getByText("Review one vehicle set at a time.")).toBeVisible({
    timeout: 30000,
  });
  const commitRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/commit")) {
      expect(request.postData()).toBeNull();
      commitRequests.push(request.url());
    }
  });
  for (let index = 0; index < accepted.batches.length; index += 1) {
    const review = page.getByRole("dialog");
    await expect(review.getByRole("button", { name: "Approve sheet", exact: true })).toBeEnabled();
    await review.getByRole("button", { name: "Approve sheet", exact: true }).click();
  }
  expect(commitRequests).toHaveLength(2);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("Sheet approved.", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Measurement History", exact: true }).click();
  await expect(page.getByRole("heading", { name: /^Week / }).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("live Admin sees door-check errors and inactive plants cannot upload", async ({ page }) => {
  test.setTimeout(60000);
  for (const buffer of [
    Buffer.from("not a workbook"),
    workbook(`T20-${randomUUID().slice(0, 10)}`, 1, "FVL"),
  ]) {
    await page.goto("/plant/AAT?dataView=upload");
    const response = page.waitForResponse((result) => result.url().endsWith("/uploads"));
    // T111: T106 judgement call 4 - "Attach workbook" is this screen's input,
    // here and on the inactive-FVL check below.
    await page
      .getByLabel("Attach workbook", { exact: true })
      .setInputFiles({ name: "check.xlsx", mimeType, buffer });
    const result = await response;
    expect(result.status()).toBe(400);
    const body = (await result.json()) as components["schemas"]["ErrorResponse"];
    await expect(page.getByRole("alert")).toContainText(body.message);
    await expect(page.getByRole("alert")).toContainText("HTTP 400");
  }
  await page.goto("/plant/FVL?dataView=upload");
  await expect(page.getByText(/not onboarded/i)).toBeVisible();
  await expect(page.getByLabel("Attach workbook", { exact: true })).toBeDisabled();
});
