import { expect, test } from "@playwright/test";
import type { components } from "../../src/api/types";

test.skip(
  process.env.T07_VIEWER_RUN !== "1",
  "Restart the API with AUTH_DEV_BYPASS_ROLES=viewer and set T07_VIEWER_RUN=1.",
);

test("live Viewer reads History, has no Upload Data manager, and upload is 403", async ({
  page,
  request,
}) => {
  const base = process.env.T07_API_URL ?? "http://127.0.0.1:8012";
  const me = (await (
    await request.get(`${base}/api/v1/auth/me`)
  ).json()) as components["schemas"]["MeResponse"];
  expect(me.principal.roles).toEqual(["viewer"]);
  await page.goto("/plant/AAT?dataView=history");
  await expect(page.getByRole("region", { name: "Measurement History" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Ingest" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Upload Data", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Edit measurement/ })).toHaveCount(0);
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await page.screenshot({ path: "test-results/screenshots/T07-viewer.png" });
  const direct = await request.post(`${base}/api/v1/uploads`, {
    headers: { "X-Correlation-ID": "t07-viewer-direct" },
    multipart: {
      expected_plant: "AAT",
      files: {
        name: "denied.xlsx",
        mimeType: "application/octet-stream",
        buffer: Buffer.from("denied"),
      },
    },
  });
  expect(direct.status()).toBe(403);
  const body = (await direct.json()) as components["schemas"]["ErrorResponse"];
  expect(body.statusCode).toBe(403);
  expect(body.correlationId).toBe("t07-viewer-direct");
  await page.goto("/batches");
  await expect(page.getByRole("heading", { name: "Engineer access required" })).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Commit|Upload|Supersede/ })).toHaveCount(0);
});
