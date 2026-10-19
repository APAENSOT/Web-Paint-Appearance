import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import type { components } from "../../src/api/types";

const engineerApi = process.env.T08_API_URL ?? "http://127.0.0.1:8016";
const adminUi = process.env.T08_ADMIN_FRONTEND ?? "http://localhost:5174";

test.skip(
  process.env.T20_MAPPING_LIVE_RUN !== "1",
  "Requires dedicated Engineer/Admin services and a disposable live database; this test performs writes.",
);

test("live Engineer proposes by API, Admin approves in Upload Data Details, and commit remains separate", async ({
  browser,
  request,
}) => {
  test.setTimeout(90000);
  const serial = `T20MAP-${randomUUID().slice(0, 12)}`;
  const header = `review-panel-${randomUUID().slice(0, 12)}`;
  const buffer = execFileSync(
    process.env.T08_PYTHON ?? path.resolve("../backend/.venv/Scripts/python.exe"),
    ["-B", path.resolve("tests/make-workbook.py"), serial, "1", "AAT", header],
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
  const id = accepted.batches[0].load_id;

  let batch: components["schemas"]["BatchReviewOut"];
  for (;;) {
    const response = await request.get(`${engineerApi}/api/v1/batches/${id}`);
    expect(response.status()).toBe(200);
    batch = (await response.json()) as components["schemas"]["BatchReviewOut"];
    if (batch.batch.status !== "RUNNING") break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  expect(batch.batch.status).toBe("REJECTED_TEMPLATE");
  const fileHash = batch.batch.file_hash;

  const proposalResponse = await request.post(`${engineerApi}/api/v1/mappings/proposals`, {
    data: {
      kind: "COLUMN",
      load_id: id,
      payload: {
        raw_header: header,
        logical_field: "checkzone",
        note: "Generated test header contains checkzone values.",
      },
    },
  });
  expect(proposalResponse.status()).toBe(201);
  const proposal = (await proposalResponse.json()) as components["schemas"]["ProposalOut"];
  expect(
    (
      await request.post(`${engineerApi}/api/v1/mappings/proposals/${proposal.id}/approve`)
    ).status(),
  ).toBe(403);

  const admin = await browser.newPage();
  await admin.goto(`${adminUi}/plant/AAT?dataView=upload&file=${fileHash}`);
  await admin.getByText("Details", { exact: true }).click();
  await admin.getByText("Mapping review", { exact: true }).click();
  const mapping = admin.getByRole("region", { name: `Mappings for sheet ${id}` });
  await expect(mapping.getByText(header, { exact: true })).toBeVisible();
  const approval = admin.waitForResponse((response) =>
    response.url().endsWith(`/${proposal.id}/approve`),
  );
  await mapping.getByRole("button", { name: "Approve & replay", exact: true }).click();
  expect((await approval).status()).toBe(200);
  await expect(mapping.getByText(/Commit remains a separate action/)).toBeVisible();

  for (;;) {
    const response = await request.get(`${engineerApi}/api/v1/batches/${id}`);
    batch = (await response.json()) as components["schemas"]["BatchReviewOut"];
    if (batch.batch.status !== "RUNNING") break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  expect(batch.batch.status).toBe("PENDING_REVIEW");
  expect((await request.post(`${engineerApi}/api/v1/batches/${id}/commit`)).status()).toBe(200);
  await admin.close();
});
