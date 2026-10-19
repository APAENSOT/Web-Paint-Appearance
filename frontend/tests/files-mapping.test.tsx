import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FilesMapping } from "../src/features/measurements/FilesMapping";
import { identity } from "./fixtures";

test("Files mapping shows diagnostic evidence but approves only applicable proposals", () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], {
    ...identity,
    principal: { ...identity.principal, roles: ["admin"] },
  });
  const proposalBase = {
    kind: "COLUMN",
    load_id: 123,
    status: "PROPOSED",
    similarity: "0.91",
    proposed_by: null,
    decided_by: null,
    created_at: "2026-09-16T00:00:00Z",
    decided_at: null,
  };
  client.setQueryData(["proposals", 123, 0], {
    items: [
      {
        ...proposalBase,
        id: "diagnostic",
        payload: {
          missing_required: ["checkzone"],
          unrecognised_headers: ["Panel Area"],
          after_replay: true,
        },
      },
      {
        ...proposalBase,
        id: "applicable",
        payload: { raw_header: "Panel Area", logical_field: "checkzone" },
      },
    ],
    page: { offset: 0, limit: 10, returned: 2, total: 12 },
  });

  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <FilesMapping id={123} status="REJECTED_TEMPLATE" plant="FTM" />
    </QueryClientProvider>,
  );

  assert.match(html, /Header diagnostic/);
  assert.match(html, /Missing required:.*checkzone/);
  assert.match(html, /Panel Area/);
  assert.match(html, /After replay/);
  assert.equal((html.match(/Approve &amp; replay/g) ?? []).length, 1);
  assert.match(html, /New mapping proposal/);
  assert.match(html, /Column header/);
  assert.match(html, /Model spelling/);
  assert.match(html, /1-2 of 12/);
  assert.match(html, /Next proposals/);
  assert.match(html, /Commit remains a separate action/);
  client.clear();
});

test("Files mapping hides mutation controls from non-Admin roles", () => {
  for (const role of ["engineer", "viewer"] as const) {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
    client.setQueryData(["identity"], {
      ...identity,
      principal: { ...identity.principal, roles: [role] },
    });
    client.setQueryData(["proposals", 123, 0], {
      items: [],
      page: { offset: 0, limit: 10, returned: 0, total: 0 },
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <FilesMapping id={123} status="PENDING_REVIEW" plant="FTM" />
      </QueryClientProvider>,
    );
    assert.doesNotMatch(html, /New mapping proposal|Approve &amp; replay/);
    client.clear();
  }
});

test("compact mapping starts on model spelling and hides column kind", () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], {
    ...identity,
    principal: { ...identity.principal, roles: ["admin"] },
  });
  client.setQueryData(["proposals", 123, 0], {
    items: [],
    page: { offset: 0, limit: 10, returned: 0, total: 0 },
  });
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <FilesMapping
        id={123}
        status="PENDING_REVIEW"
        plant="FTM"
        defaultKind="ALIAS_MODEL"
        compact
      />
    </QueryClientProvider>,
  );
  assert.match(html, /Map this spelling/);
  assert.match(html, /Raw model spelling/);
  assert.match(html, /Propose model mapping/);
  assert.doesNotMatch(html, /Column header/);
  assert.doesNotMatch(html, /Mapping kind/);
  client.clear();
});
