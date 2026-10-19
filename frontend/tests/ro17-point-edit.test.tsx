/**
 * RO17: Point Check's editing screens.
 *
 * * D-RO17-1 -- the plant's word first, the code beside it only when it differs;
 * * D-RO17-11 -- a Film list without the rules is editable (rename, retire, add)
 *   but shows no Counted / H-V control, and only an Admin may switch the rules
 *   on, which refuses rather than guess a missing H / V;
 * * D-RO17-10 -- an offered model with no list can be picked;
 * * D-RO17-13 -- a shared spelling is marked and never offered for retire.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { components } from "../src/api/types";
import { FilmPointSettings } from "../src/features/filmthickness/FilmPointSettings";
import { PointAliases } from "../src/features/filmthickness/PointAliases";
import { WsPointSettings } from "../src/features/filmthickness/WsPointSettings";
import { pointName, switchOnRows } from "../src/features/filmthickness/point-edit";

type FilmPoint = components["schemas"]["FilmPointSettingItem"];
type Alias = components["schemas"]["PointAliasItem"];

const MODEL = "U704";

function render(node: ReactNode, seed: (client: QueryClient) => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  seed(client);
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>{node}</QueryClientProvider>,
  );
  client.clear();
  return html;
}

function filmPoint(no: number, code: string, overrides: Partial<FilmPoint> = {}): FilmPoint {
  return {
    point_no: no,
    point_code: code,
    label: code,
    counted: true,
    orientation: "V",
    is_complete_stop: false,
    is_extra: false,
    reason: null,
    changed_by: null,
    changed_at: null,
    ...overrides,
  };
}

function alias(overrides: Partial<Alias>): Alias {
  return {
    kind: "zone_map",
    alias_id: "1",
    not_a_point: false,
    spelling: "01 hood",
    code: "RRHOOD",
    code_label: "Hood rear",
    shared: false,
    retirable: true,
    live: true,
    note: null,
    created_at: null,
    retired_at: null,
    retired_reason: null,
    stored_facts: 12,
    ...overrides,
  };
}

const film = (admin: boolean, points: FilmPoint[], hasSetting = false) =>
  render(<FilmPointSettings code="SAP" admin={admin} />, (client) => {
    client.setQueryData(["filmthickness", "models", "SAP"], {
      plant_code: "SAP",
      items: [
        {
          model_code: MODEL,
          display_name: null,
          point_count: points.length,
          has_setting: hasSetting,
        },
      ],
      offered_without_list: ["J73"],
    });
    client.setQueryData(["filmthickness", "points", "SAP", MODEL], {
      plant_code: "SAP",
      model_code: MODEL,
      has_setting: hasSetting,
      items: points,
      retired_items: [],
      tail_labels: [],
    });
  });

test("RO17 a point shows the plant's word first, and its code only when it differs", () => {
  assert.deepEqual(pointName("Hood rear", "RRHOOD"), { word: "Hood rear", code: "RRHOOD" });
  assert.deepEqual(pointName("RRHOOD", "RRHOOD"), { word: "RRHOOD", code: null });
  assert.deepEqual(pointName("  ", "RRHOOD"), { word: "RRHOOD", code: null });
});

test("RO17 switch-on writes every live point counted at its own H / V", () => {
  const points = [
    filmPoint(1, "001HOOD", { orientation: "H", counted: false }),
    filmPoint(2, "002DOOR"),
  ];
  assert.deepEqual(switchOnRows(points), {
    rows: [
      { point_code: "001HOOD", counted: true, orientation: "H" },
      { point_code: "002DOOR", counted: true, orientation: "V" },
    ],
    missing: [],
  });
});

test("RO17 switch-on names the points with no H / V instead of guessing", () => {
  const points = [filmPoint(1, "001HOOD"), filmPoint(2, "002NEW", { orientation: null })];
  assert.deepEqual(switchOnRows(points).missing, ["002NEW"]);
});

test("RO17 a Film list without the rules is editable but has no Counted or H / V control", () => {
  const html = film(false, [filmPoint(1, "001HOOD", { label: "Bonnet 1" })]);
  assert.match(html, /Bonnet 1/);
  assert.match(html, /001HOOD/);
  assert.match(html, /data-testid="point-rename-film-001HOOD"/);
  assert.match(html, /data-testid="film-point-retire-001HOOD"/);
  assert.match(html, /data-testid="film-point-add-open"/);
  assert.match(html, /data-testid="film-points-read-only"/);
  assert.doesNotMatch(html, /film-point-counted-001HOOD/);
  assert.doesNotMatch(html, /film-point-orientation-001HOOD/);
  assert.doesNotMatch(html, /film-points-save/);
  // Engineers do not get the Admin switch-on, nor tail-label writes.
  assert.doesNotMatch(html, /film-rules-switch-on/);
  assert.doesNotMatch(html, /film-tail-add/);
});

test("RO17 only an Admin is offered the switch-on and tail-label add", () => {
  const html = film(true, [filmPoint(1, "001HOOD")]);
  assert.match(html, /data-testid="film-rules-switch-on"/);
  assert.match(html, /data-testid="film-tail-add"/);
});

test("RO17 a Film list with the rules keeps its Counted and H / V controls", () => {
  const html = film(true, [filmPoint(1, "001HOOD")], true);
  assert.match(html, /film-point-counted-001HOOD/);
  assert.match(html, /film-point-orientation-001HOOD/);
  assert.doesNotMatch(html, /film-rules-switch-on/);
});

test("RO17 an offered model with no list is in the pickers of both domains", () => {
  assert.match(film(false, [filmPoint(1, "001HOOD")]), /value="J73">J73 \(no list yet\)/);
  const ws = render(<WsPointSettings code="SAP" admin={false} />, (client) => {
    client.setQueryData(["ws-points", "SAP"], {
      plant_code: "SAP",
      items: [],
      offered_without_list: ["J73"],
    });
    client.setQueryData(["ws-points", "SAP", "J73"], {
      plant_code: "SAP",
      model_code: "J73",
      items: [],
      retired_items: [],
      zone_choices: [],
      horizontal_words: ["HOOD"],
    });
  });
  assert.match(ws, /value="J73" selected="">J73 \(no list yet\)/);
  assert.match(ws, /data-testid="ws-points-empty"/);
  assert.match(ws, /data-testid="ws-point-add-open"/);
});

const aliases = (admin: boolean) =>
  render(<PointAliases plant="AAT" domain="wavescan" model={MODEL} admin={admin} />, (client) => {
    client.setQueryData(["point-aliases", "AAT", "wavescan", MODEL], {
      plant_code: "AAT",
      domain: "wavescan",
      model_code: MODEL,
      items: [
        alias({}),
        alias({
          kind: "global_alias",
          alias_id: "HOOD RR",
          spelling: "HOOD RR",
          shared: true,
          retirable: false,
        }),
      ],
    });
  });

test("RO17 a shared spelling is marked and has no retire, even for an Admin", () => {
  const html = aliases(true);
  assert.match(html, /Shared by all plants/);
  assert.match(html, /Hood rear/);
  assert.match(html, /data-testid="point-alias-retire-zone_map-1"/);
  assert.doesNotMatch(html, /point-alias-retire-global_alias/);
});

test("RO17 an Engineer reads the spellings but is offered no retire", () => {
  const html = aliases(false);
  assert.match(html, /01 hood/);
  assert.doesNotMatch(html, /point-alias-retire-/);
});
