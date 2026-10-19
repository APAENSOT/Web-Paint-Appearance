import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import * as roles from "../src/api/roles";
import { Overview } from "../src/features/overview/Overview";
import { Administration } from "../src/features/admin/Administration";
import { OperationalAdministration } from "../src/features/admin/OperationalAdministration";
import { Intake } from "../src/features/intake/Intake";
import { ReviewQueue } from "../src/features/intake/ReviewQueue";
import { HealthBanner } from "../src/features/overview/HealthBanner";
import { ApiError } from "../src/api/client";
import { identity, measurement, cleanReview, workspaceMeta, catalogueFixture } from "./fixtures";

function cache(role: "viewer" | "engineer" | "admin") {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  client.setQueryData(["identity"], {
    ...identity,
    principal: { ...identity.principal, roles: [role] },
  });
  client.setQueryData(["metadata"], workspaceMeta);
  client.setQueryData(["standards", "catalogue"], catalogueFixture);
  client.setQueryData(["readiness"], {
    status: "ready",
    checks: { database: { status: "ok" }, object_store: { status: "ok" } },
  });
  for (const [plant, total] of [
    ["AAT", 127],
    ["FVL", 0],
  ])
    client.setQueryData(["measurements", "count", plant], {
      items: [measurement],
      page: { total, returned: 1, limit: 1, offset: 0 },
    });
  client.setQueryData(["batches", "attention"], {
    items: [cleanReview.batch],
    page: { total: 80, returned: 1, limit: 50, offset: 0 },
  });
  client.setQueryData(["batches", 0], {
    items: [cleanReview.batch],
    page: { total: 1, returned: 1, limit: 10, offset: 0 },
  });
  client.setQueryData(["batch", 123], cleanReview);
  return client;
}

async function markup(client: QueryClient, element: React.ReactNode) {
  const route = createRootRoute({
    component: () => <QueryClientProvider client={client}>{element}</QueryClientProvider>,
  });
  const router = createRouter({ routeTree: route, history: createMemoryHistory() });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

for (const role of ["viewer", "engineer", "admin"] as const) {
  test(`${role} role helper matrix`, () => {
    const principal = { ...identity.principal, roles: [role] };
    assert.equal(roles.isViewer(principal), role === "viewer");
    assert.equal(roles.isEngineer(principal), role === "engineer");
    assert.equal(roles.isAdmin(principal), role === "admin");
    // RO12 CHANGE (D-RO12-4): mayIngest true for every role -> Engineer or Admin.
    for (const helper of [roles.mayIngest, roles.mayCorrect, roles.maySeeIntakeNav])
      assert.equal(helper(principal), role !== "viewer");
    for (const helper of [
      roles.mayApproveMapping,
      roles.maySupersede,
      roles.mayManagePlantFiles,
      roles.maySeeAdminNav,
    ])
      assert.equal(helper(principal), role === "admin");
  });
  test(`${role} Overview shows catalogue plants without operational data`, async () => {
    const client = cache(role);
    const html = await markup(client, <Overview />);
    assert.match(html, /AAT/);
    assert.match(html, /FVL/);
    assert.match(html, /FTM/);
    assert.match(html, /IMG Plant Location/);
    assert.match(html, /Regional reports &amp; feeds/);
    assert.match(html, /Overview IMG/);
    assert.match(html, /IMG Color/);
    assert.doesNotMatch(html, /review.xlsx|Batch attention|Upload or review|Service readiness/);
    client.clear();
  });
  test(`${role} intake chooses plants or parks while admin stays parked or denied`, async () => {
    const client = cache(role);
    const intake = await markup(client, <Intake />);
    const admin = await markup(client, <Administration />);
    // RO12 CHANGE (D-RO12-4): a Viewer is denied (was: parked like an Engineer).
    assert.equal(intake.includes("Engineer access required"), role === "viewer");
    assert.equal(intake.includes('type="file"'), false);
    assert.equal(intake.includes(">Choose a plant</h1>"), role === "admin");
    assert.equal(intake.includes("Plant uploads are Admin-only"), role === "engineer");
    assert.equal(intake.includes("Not wired this phase"), false);
    assert.equal(admin.includes("Admin access required"), role !== "admin");
    assert.equal(admin.includes("Not wired this phase"), false);
    if (role === "admin") {
      assert.match(admin, /Color Family/);
      assert.match(admin, /Model/);
      assert.match(admin, /Ignite Orange/);
    }
    assert.doesNotMatch(admin, /type="file"|review.xlsx|Unmapped colours|Current session/);
    client.clear();
  });
  test(`${role} intake either operates or denies without rendering cached batches`, async () => {
    const client = cache(role);
    const html = await markup(client, <ReviewQueue />);
    // RO12 CHANGE (D-RO12-4): a Viewer is denied (was: operates like an Engineer).
    assert.equal(html.includes('type="file"'), role !== "viewer");
    assert.equal(html.includes('aria-label="Batch 123"'), role !== "viewer");
    assert.equal(html.includes("Engineer access required"), role === "viewer");
    assert.equal(html.includes("read batch history"), false);
    client.clear();
  });
  test(`${role} parked Administration remains read-only or denies`, async () => {
    const client = cache(role);
    const html = await markup(client, <OperationalAdministration />);
    assert.equal(html.includes("Admin access required"), role !== "admin");
    assert.equal(html.includes("Unmapped colours"), role === "admin");
    if (role === "admin") {
      assert.match(html, /21/);
      assert.match(html, /Grading unavailable/);
      assert.match(
        html,
        /<button[^>]*disabled=""[^>]*>Standards publishing \u00b7 Reserved<\/button>/,
      );
    }
    client.clear();
  });
}

test("absent roles fail closed; multiple roles retain Admin privileges", () => {
  for (const helper of [
    roles.isViewer,
    roles.isEngineer,
    roles.isAdmin,
    roles.mayIngest,
    roles.mayCorrect,
    roles.mayApproveMapping,
    roles.maySupersede,
    roles.mayManagePlantFiles,
    roles.maySeeIntakeNav,
    roles.maySeeAdminNav,
  ]) {
    assert.equal(helper(undefined), false);
    // RO12 CHANGE (D-RO12-4): mayIngest no longer passes a principal with no role.
    assert.equal(helper({ ...identity.principal, roles: [] }), false);
  }
  assert.equal(roles.mayCorrect({ ...identity.principal, roles: ["viewer", "admin"] }), true);
});

test("readiness body parsing ignores unrecognised keys and malformed nested values", async () => {
  for (const body of [
    null,
    [],
    "ready",
    {
      status: 7,
      checks: { database: null, object_store: { status: false }, private: "do-not-show" },
    },
  ]) {
    const client = cache("viewer");
    client.setQueryData(["readiness"], body);
    const html = await markup(client, <HealthBanner />);
    assert.match(html, /Readiness details unavailable/);
    assert.equal(html.includes("do-not-show"), false);
    client.clear();
  }
});

test("parked health 503 quotes its envelope; Overview ignores readiness", async () => {
  const client = cache("viewer");
  const query = client.getQueryCache().find({ queryKey: ["readiness"] })!;
  query.setState({
    status: "error",
    error: new ApiError(503, {
      statusCode: 503,
      error: "Unavailable",
      message: "Object store offline",
      correlationId: "t10-ready",
    }),
  });
  const html = await markup(client, <HealthBanner />);
  assert.match(html, /Object store offline/);
  assert.match(html, /t10-ready/);
  const overview = await markup(client, <Overview />);
  assert.doesNotMatch(overview, /Object store offline/);
  assert.match(overview, /AAT/);
  assert.match(overview, /IMG Plant Location/);
  client.clear();
});
