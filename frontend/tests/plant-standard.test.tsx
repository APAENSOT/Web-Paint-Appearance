import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  PlantStandard,
  coloursNotOffered,
  modelPointsLine,
  reloadedSheetsCopy,
  removeModelCopy,
  type StandardView,
} from "../src/features/measurements/PlantStandard";
import { StandardChildrenNav } from "../src/features/measurements/StandardChildrenNav";
import { catalogueFixture, identity } from "./fixtures";

const ranger = {
  model_code: "P703 DBL RANGER",
  display_name: null,
  series_code: "P703",
  body_style: "Pickup",
  wavescan_ok: true,
  wavescan_offered: true,
  wavescan_points: 32,
  film_points: 98,
};

// T112-FIX (D-112F-7): a Film-only card is drawn exactly like the others.
const rapcap = {
  ...ranger,
  model_code: "P703 RAPCAP",
  display_name: "RAPCAP",
  wavescan_ok: false,
  wavescan_offered: false,
  wavescan_points: null,
  film_points: 93,
};

function html(plant: string, view: StandardView = "family") {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  // RO12 CHANGE (D-RO12-4): the write controls are Admin-only, so the claims
  // below render as Admin; ro12-role-gates.test.tsx renders every role.
  client.setQueryData(["identity"], {
    ...identity,
    principal: { ...identity.principal, roles: ["admin"] },
  });
  client.setQueryData(["standards", "catalogue"], catalogueFixture);
  // T112: the Model cards are the plant's model-points read.
  client.setQueryData(["standards", "model-points", plant], {
    plant_code: plant,
    models: [ranger, rapcap],
    attachable_models: ["P703 DBL SUPER DUTY", "P703 SGL"],
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <PlantStandard code={plant} view={view} />
    </QueryClientProvider>,
  );
}

test("FTM color family lists this plant only with readable thresholds", () => {
  const markup = html("FTM", "family");
  assert.match(markup, /aria-label="FTM standard"/);
  assert.match(markup, /Color Family/);
  assert.match(markup, /Ignite Orange/);
  assert.match(markup, /Medium Solids/);
  assert.match(markup, /class="family-standard-card/);
  assert.match(markup, /data-family="MS"/);
  assert.match(markup, /Standard Horizontal/);
  assert.match(markup, /Minimum Horizontal/);
  assert.match(markup, /Standard Vertical/);
  assert.match(markup, /Minimum Vertical/);
  assert.match(markup, /Adjust standards/);
  assert.match(markup, /Select a historical colour/);
  assert.match(markup, /role="combobox"/);
  assert.match(markup, /bg-popover text-popover-foreground/);
  assert.doesNotMatch(markup, /Publish new version/);
  assert.doesNotMatch(markup, /Ford H/);
  assert.doesNotMatch(markup, /Min H/);
  assert.doesNotMatch(markup, /P703 DBL RANGER/);
  assert.doesNotMatch(markup, /content ships later/);
  assert.doesNotMatch(markup, /AAT offered/);
  assert.doesNotMatch(markup, /FVL offered/);
  assert.doesNotMatch(markup, /SAP offered/);
});

test("FTM add colour offers catalogue colours that are not already on this plant", () => {
  const colors = [
    ...catalogueFixture.colors,
    {
      color_name: "Frozen White",
      color_group: null,
      plants: [
        { plant_code: "SAP", is_offered: true, family_code: "LS", family_name: "Light Solids" },
      ],
    },
  ];
  const choices = coloursNotOffered(colors, "FTM");
  assert.equal(choices.includes("Frozen White"), true);
  assert.equal(choices.includes("Ignite Orange"), false);
});

test("FTM model is a separate pane from color family", () => {
  const markup = html("FTM", "model");
  assert.match(markup, />Model</);
  assert.match(markup, /P703 DBL RANGER/);
  assert.match(markup, /Wave Scan 32 points · Film 98 points/);
  assert.doesNotMatch(markup, /zones/);
  assert.doesNotMatch(markup, /Ignite Orange/);
  assert.doesNotMatch(markup, /Standard Horizontal/);
});

test("T112 points line omits a domain with no list", () => {
  assert.equal(modelPointsLine(ranger), "Wave Scan 32 points · Film 98 points");
  // T112-FIX (D-112F-6): a Film-only model says so on its one line.
  assert.equal(modelPointsLine(rapcap), "Film Thickness only · Film 93 points");
  assert.equal(
    modelPointsLine({ ...rapcap, film_points: null }),
    "Film Thickness only · no Film points yet",
  );
  assert.equal(modelPointsLine({ ...ranger, film_points: null }), "Wave Scan 32 points");
});

test("T112-FIX one card design: model_code heading, one line, Remove on every card", () => {
  // T112-FIX (D-112F-7)
  const markup = html("FTM", "model");
  assert.match(markup, /<span class="block text-sm font-medium">P703 RAPCAP<\/span>/);
  assert.match(markup, /Film Thickness only · Film 93 points/);
  assert.doesNotMatch(markup, />RAPCAP</);
  assert.equal(markup.match(/Remove from FTM/g)?.length, 2);
});

test("T112-FIX Remove confirm copy", () => {
  // T112-FIX (D-112F-8)
  assert.equal(
    removeModelCopy("P703 RAPCAP", "FTM"),
    "New Wave Scan and Film files of P703 RAPCAP at FTM will be refused. Readings already loaded stay. Attach brings it back.",
  );
});

test("T115 Attach says how many held sheets it reloaded, only when it reloaded any", () => {
  // T115 (D-115-4)
  assert.equal(reloadedSheetsCopy(0), null);
  assert.equal(
    reloadedSheetsCopy(1),
    "Reloaded 1 held sheet from the stored file. It is back in review on Upload Data.",
  );
  assert.equal(
    reloadedSheetsCopy(2),
    "Reloaded 2 held sheets from the stored files. They are back in review on Upload Data.",
  );
});

test("SAP color family does not use the FTM family heading for Ignite Orange", () => {
  const markup = html("SAP", "family");
  assert.match(markup, /aria-label="SAP standard"/);
  assert.doesNotMatch(markup, /Ignite Orange/);
});

test("SAP model still lists Ranger without Ignite Orange", () => {
  const markup = html("SAP", "model");
  assert.match(markup, /P703 DBL RANGER/);
  assert.doesNotMatch(markup, /Ignite Orange/);
});

test("Standard children keep Color Family; model settings have their own workspace", () => {
  // T100-FIX2: the nav reads identity now (D-100-9), so it needs a client.
  // None is seeded, so no principal is known and the entry rule falls back to
  // the `canEditFilm` prop -- which this claim does not pass and does not use.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const markup = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <StandardChildrenNav view="family" onSelect={() => undefined} />
    </QueryClientProvider>,
  );
  assert.match(markup, /aria-label="Standard views"/);
  assert.match(markup, /Color Family/);
  assert.doesNotMatch(markup, />Model</);
  assert.match(markup, /aria-pressed="true"/);
});
