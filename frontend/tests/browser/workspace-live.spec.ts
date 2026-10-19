import { expect, test } from "@playwright/test";
import type { components } from "../../src/api/types";

for (const [role, defaultPort, defaultApi] of [
  ["viewer", 5175, 8018],
  ["engineer", 5173, 8016],
  ["admin", 5174, 8017],
] as const)
  // parked until owner names this function
  test.skip(`live ${role} Overview, navigation and access boundaries`, async ({
    page,
    request,
  }) => {
    const base =
      process.env[`T10_${role.toUpperCase()}_FRONTEND`] ?? `http://localhost:${defaultPort}`;
    const api = process.env[`T10_${role.toUpperCase()}_API`] ?? `http://127.0.0.1:${defaultApi}`;
    const identity = await request.get(`${api}/api/v1/auth/me`);
    expect((await identity.json()).principal.roles).toEqual([role]);
    const urls: string[] = [];
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (req) => {
      if (/\/api\/v1\/|\/health\//.test(req.url())) {
        urls.push(req.url());
        expect(req.method()).toBe("GET");
        expect(req.headers().authorization).toBeUndefined();
      }
    });
    const countResponse = page.waitForResponse(
      (r) =>
        r.url().includes("/measurements?") &&
        new URL(r.url()).searchParams.get("plant") === "AAT" &&
        new URL(r.url()).searchParams.get("limit") === "1",
    );
    await page.goto(base);
    const data = (await (await countResponse).json()) as components["schemas"]["MeasurementPage"];
    await expect(
      page
        .getByRole("article", { name: "AAT plant" })
        .getByLabel(`${data.page.total} active measurements`),
    ).toBeVisible();
    await expect(
      page.getByRole("article", { name: "FVL plant" }).getByLabel("0 active measurements"),
    ).toBeVisible();
    await expect(page.getByText("Dev bypass", { exact: true })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Ingest" })).toHaveCount(
      role === "viewer" ? 0 : 1,
    );
    await expect(page.getByRole("navigation", { name: "Administration", exact: true })).toHaveCount(
      role === "admin" ? 1 : 0,
    );
    const health = page.getByRole("region", { name: "Service readiness" });
    await expect(health).not.toContainText("Checking service readiness");
    if (role !== "viewer")
      await expect(page.getByRole("region", { name: "Batch attention" })).not.toContainText(
        "Loading recent batches",
      );
    await page.screenshot({
      path: `test-results/screenshots/T10-overview-${role}.png`,
      fullPage: true,
    });
    await page.goto(`${base}/batches`);
    if (role === "viewer") {
      await expect(page.getByRole("heading", { name: "Engineer access required" })).toBeVisible();
      await expect(page.getByRole("article")).toHaveCount(0);
      await page.screenshot({ path: "test-results/screenshots/T10-viewer-denial.png" });
      expect(urls.some((url) => url.includes("/batches"))).toBe(false);
    } else await expect(page.getByLabel("Workbooks", { exact: true })).toBeVisible();
    await page.goto(`${base}/admin`);
    if (role === "admin") {
      const meta = (await (
        await request.get(`${api}/api/v1/meta`)
      ).json()) as components["schemas"]["MetaResponse"];
      await expect(
        page.getByRole("heading", { name: "Administration", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByText(String(meta.unmapped_color_count), { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Standards publishing · Reserved" }),
      ).toBeDisabled();
      await page.screenshot({ path: "test-results/screenshots/T10-admin-status.png" });
    } else await expect(page.getByRole("heading", { name: "Admin access required" })).toBeVisible();
    await page.goto(`${base}/analysis`);
    await expect(page.getByRole("heading", { name: "Grading unavailable" })).toBeVisible();
    expect(urls.some((url) => /dashboard\/preview|\/standards|\/health\/live/.test(url))).toBe(
      false,
    );
    expect(errors).toEqual([]);
    console.log(
      `T10 ${role}: AAT total=${data.page.total}; FVL=0; readiness and role navigation verified; no preview or standards request.`,
    );
  });
