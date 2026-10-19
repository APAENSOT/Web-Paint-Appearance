import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HeldIdentityList } from "../src/features/measurements/HeldIdentityList";
import { canTeach, heldAliasProposal } from "../src/features/measurements/held-alias";
import { isApplicable, proposalKindLabel } from "../src/api/mapping-state";
import type { components } from "../src/api/types";
import { cleanReview, identity } from "./fixtures";

type Held = components["schemas"]["HeldLabelGroup"];

// T61 / backend T78 part D: a Film sheet whose model did not settle.
const filmHeld: Held = {
  reason: "FILM_MODEL_UNRESOLVED",
  column: "model",
  raw_value: "BLUE_XX_123",
  count: 94,
  teachable_kind: "FILM_MODEL",
  candidates: [],
  display_group: "film_model",
  operator_message: "This Film sheet's model is not settled.",
  film_model: {
    load_id: 501,
    source_sheet: "Quick Summary",
    plant_code: "FTM",
    detail: "neither the file nor the tab carries an approved FTM spelling",
    resolution_source: "none",
    candidates: [],
    choices: ["P703 DBL RANGER", "P703 DBL RAPTOR", "P703 RAPCAP", "P703 SGL"],
    teachable_tokens: ["XX", "BLUE"],
  },
};

const ambiguous: Held = {
  ...filmHeld,
  film_model: {
    ...filmHeld.film_model!,
    resolution_source: "ambiguous",
    detail: "the file and tab name say ['DBL', 'RB'], which mean two models",
    candidates: ["P703 DBL RANGER", "P703 DBL RAPTOR"],
    teachable_tokens: [],
  },
};

function render(status: string, roles: string[], labels: Held[]) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["identity"], { ...identity, principal: { ...identity.principal, roles } });
  client.setQueryData(["batch", 501], { ...cleanReview, held_labels: labels });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <HeldIdentityList loadId={501} plant="FTM" status={status} />
    </QueryClientProvider>,
  );
}

test("a held Film model offers only the plant's Film models and server-derived spellings", () => {
  const html = render("PENDING_REVIEW", ["engineer"], [filmHeld]);
  assert.match(html, />Film model</);
  assert.match(html, /neither the file nor the tab/);
  assert.match(html, /FilmThickness model for Quick Summary/);
  for (const model of filmHeld.film_model!.choices!)
    assert.match(html, new RegExp(`<option value="${model}"`));
  assert.match(html, /<option value=""[^>]*>This sheet only<\/option>/);
  assert.match(html, /<option value="XX">XX<\/option>/);
  assert.doesNotMatch(html, /<input/); // never free text
});

test("an ambiguous hold marks named models and teaches nothing", () => {
  const html = render("PENDING_REVIEW", ["engineer"], [ambiguous]);
  assert.match(html, /P703 DBL RANGER \(named in the file\)/);
  assert.match(html, /applies to this sheet only/);
  assert.doesNotMatch(html, /Also teach this spelling/);
});

test("viewers and committed sheets cannot choose a Film model", () => {
  assert.doesNotMatch(render("PENDING_REVIEW", ["viewer"], [filmHeld]), /Pick model/);
  assert.equal(canTeach(filmHeld, true, "COMMITTED"), false);
  assert.equal(canTeach({ ...filmHeld, film_model: null }, true, "PENDING_REVIEW"), false);
  assert.equal(canTeach(filmHeld, true, "PENDING_REVIEW"), true);
});

test("the FILM_MODEL proposal carries the server's sheet identity and an optional token", () => {
  assert.deepEqual(
    heldAliasProposal(
      { item: filmHeld, name: "P703 SGL", token: "XX" },
      "FTM",
      501,
      "PENDING_REVIEW",
    ),
    {
      kind: "FILM_MODEL",
      load_id: 501,
      payload: {
        plant: "FTM",
        load_id: 501,
        source_sheet: "Quick Summary",
        model_code: "P703 SGL",
        raw_token: "XX",
      },
    },
  );
  const sheetOnly = heldAliasProposal(
    { item: ambiguous, name: "P703 DBL RAPTOR", token: null },
    "FTM",
    501,
    "PENDING_REVIEW",
  );
  assert.equal("raw_token" in sheetOnly.payload, false);
  assert.throws(() =>
    heldAliasProposal({ item: filmHeld, name: "J73 DBL" }, "FTM", 501, "PENDING_REVIEW"),
  );
  assert.throws(() =>
    heldAliasProposal(
      { item: filmHeld, name: "P703 SGL", token: "free text" },
      "FTM",
      501,
      "PENDING_REVIEW",
    ),
  );
});

test("an Admin sees a FILM_MODEL proposal as approvable, labelled plainly", () => {
  const proposal = {
    id: "p1",
    kind: "FILM_MODEL",
    load_id: 501,
    status: "PROPOSED",
    payload: { plant: "FTM", load_id: 501, source_sheet: "Quick Summary", model_code: "P703 SGL" },
  } as unknown as components["schemas"]["ProposalOut"];
  assert.equal(isApplicable(proposal), true);
  assert.equal(proposalKindLabel("FILM_MODEL"), "Film model choice");
  assert.equal(isApplicable({ ...proposal, status: "APPROVED" }), false);
});
