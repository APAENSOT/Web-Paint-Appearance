import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FilmPointSettings } from "../src/features/filmthickness/FilmPointSettings";
import { WsPointSettings } from "../src/features/filmthickness/WsPointSettings";
import {
  moveWalkPoint,
  placeWalkPointAfter,
  rebaseWalkDraft,
} from "../src/features/filmthickness/point-walk";

const plant = "ZRO19UI";
const model = "Synthetic model";
const codes = ["012HOOD", "007HOOD", "001HOOD"];

function render(domain: "FILMTHICKNESS" | "WAVESCAN", admin: boolean) {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  client.setQueryData(["point-walk", plant, domain, model], {
    plant_code: plant,
    model_code: model,
    domain,
    version_id: 42,
    set_by: null,
    set_at: null,
    reason: "Synthetic measuring order",
    items: codes.map((point_code, i) => ({
      point_code,
      point_no: Number(point_code.slice(0, 3)),
      label: point_code,
      walk_rank: i + 1,
    })),
  });
  if (domain === "FILMTHICKNESS") {
    client.setQueryData(["filmthickness", "models", plant], {
      plant_code: plant,
      offered_without_list: [],
      items: [{ model_code: model, display_name: null, point_count: 3, has_setting: false }],
    });
    client.setQueryData(["filmthickness", "points", plant, model], {
      plant_code: plant,
      model_code: model,
      has_setting: false,
      retired_items: [],
      tail_labels: [],
      items: codes.map((point_code) => ({
        point_code,
        point_no: Number(point_code.slice(0, 3)),
        label: point_code,
        counted: true,
        orientation: "H",
        is_complete_stop: false,
        is_extra: false,
        reason: null,
        changed_by: null,
        changed_at: null,
      })),
    });
  } else {
    client.setQueryData(["ws-points", plant], {
      plant_code: plant,
      offered_without_list: [],
      items: [{ model_code: model, display_name: null, point_count: 3, counted_count: 3 }],
    });
    client.setQueryData(["ws-points", plant, model], {
      plant_code: plant,
      model_code: model,
      retired_items: [],
      zone_choices: [],
      horizontal_words: [],
      items: codes.map((zone_code) => ({
        zone_code,
        point_no: Number(zone_code.slice(0, 3)),
        label: zone_code,
        counted: true,
        tolerance_group: "Horizontal",
        is_extra: false,
        reason: null,
        note: null,
        changed_by: null,
        changed_at: null,
      })),
    });
  }
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      {domain === "FILMTHICKNESS" ? (
        <FilmPointSettings code={plant} admin={admin} />
      ) : (
        <WsPointSettings code={plant} admin={admin} />
      )}
    </QueryClientProvider>,
  );
  client.clear();
  return html;
}

test("RO19 Engineer can edit Film measuring order even with point rules off", () => {
  const html = render("FILMTHICKNESS", false);
  assert.match(html, /Measuring order/);
  assert.match(html, /Move up 007HOOD/);
  assert.match(html, /Move down 007HOOD/);
  assert.match(html, /Place after 007HOOD/);
  assert.match(html, /Why does the measuring order change/);
  assert.match(html, /Save measuring order/);
  assert.doesNotMatch(html, /Preview stored sheets/);
});

test("RO19 Admin has measuring order controls and an actual stored-sheet preview action", () => {
  const html = render("FILMTHICKNESS", true);
  assert.match(html, /Measuring order/);
  assert.match(html, /Preview stored sheets/);
  assert.match(html, /data-walk-rank="1"/);
  assert.ok(html.indexOf('data-walk-code="012HOOD"') < html.indexOf('data-walk-code="007HOOD"'));
});

test("RO19 Wave Scan uses the same measuring-order controls", () => {
  const html = render("WAVESCAN", false);
  assert.match(html, /Measuring order/);
  assert.match(html, /Move up 007HOOD/);
  assert.match(html, /Place after 007HOOD/);
});

test("RO19 draft moves preserve codes and never mutate the saved order", () => {
  assert.deepEqual(moveWalkPoint(codes, "001HOOD", -1), ["012HOOD", "001HOOD", "007HOOD"]);
  assert.deepEqual(moveWalkPoint(codes, "012HOOD", -1), codes);
  assert.deepEqual(placeWalkPointAfter(codes, "001HOOD", "012HOOD"), [
    "012HOOD",
    "001HOOD",
    "007HOOD",
  ]);
  assert.deepEqual(placeWalkPointAfter(codes, "001HOOD", "001HOOD"), codes);
  assert.deepEqual(codes, ["012HOOD", "007HOOD", "001HOOD"]);
});

test("RO19 an explicit rebase keeps the draft and accepts only the same live membership", () => {
  const draft = { point_codes: [...codes].reverse(), expected_version_id: 42 };
  const latest = {
    plant_code: plant,
    model_code: model,
    domain: "FILMTHICKNESS" as const,
    version_id: 43,
    set_by: null,
    set_at: null,
    reason: null,
    items: codes.map((point_code, i) => ({
      point_code,
      point_no: Number(point_code.slice(0, 3)),
      label: point_code,
      walk_rank: i + 1,
    })),
  };
  assert.deepEqual(rebaseWalkDraft(draft, latest), {
    point_codes: [...codes].reverse(),
    expected_version_id: 43,
  });
  assert.equal(draft.expected_version_id, 42);
  assert.equal(rebaseWalkDraft(draft, { ...latest, items: latest.items.slice(1) }), null);
  assert.equal(
    rebaseWalkDraft({ ...draft, point_codes: [codes[0], codes[0], codes[2]] }, latest),
    null,
  );
});
