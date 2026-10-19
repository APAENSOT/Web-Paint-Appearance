import test from "node:test";
import assert from "node:assert/strict";
import { hashKey } from "@tanstack/react-query";
import {
  comparisonMonthlyPreviewOptions,
  comparisonVehicleVisualsOptions,
  comparisonPointsOptions,
  comparisonVehiclesOptions,
} from "../src/api/queries";

test("T84 monthly preview cache separates plant/domain/model/metric and ordered months", () => {
  const body = {
    domain: "FILMTHICKNESS" as const,
    model: "P703",
    metric: "clear" as const,
    months: ["2026-06", "2026-07"],
  };
  const key = (plant = "AAT", input = body) =>
    hashKey(comparisonMonthlyPreviewOptions(plant, input).queryKey);
  const original = key();
  assert.notEqual(original, key("FTM"));
  assert.notEqual(original, key("AAT", { ...body, model: "U704" }));
  assert.notEqual(original, key("AAT", { ...body, months: [...body.months].reverse() }));
  assert.notEqual(
    original,
    hashKey(comparisonMonthlyPreviewOptions("AAT", { ...body, metric: "primer" }).queryKey),
  );
  assert.notEqual(
    original,
    hashKey(
      comparisonMonthlyPreviewOptions("AAT", { ...body, domain: "WAVESCAN", metric: "cf" })
        .queryKey,
    ),
  );
});

test("T84 vehicle caches separate current ordered page IDs and picker filters", () => {
  const query = { model: "P703", vehicle_id: ["a", "b"] };
  const visuals = (plant = "AAT", input = query) =>
    hashKey(comparisonVehicleVisualsOptions(plant, input).queryKey);
  assert.notEqual(visuals(), visuals("FTM"));
  assert.notEqual(visuals(), visuals("AAT", { ...query, model: "U704" }));
  assert.notEqual(visuals(), visuals("AAT", { ...query, vehicle_id: ["b", "a"] }));
  assert.notEqual(visuals(), visuals("AAT", { ...query, vehicle_id: ["i"] }));
  const pointQuery = { ...query, domain: "WAVESCAN" as const, metric: "cf" as const };
  const points = hashKey(comparisonPointsOptions("AAT", pointQuery).queryKey);
  assert.notEqual(
    points,
    hashKey(comparisonPointsOptions("AAT", { ...pointQuery, metric: "du" }).queryKey),
  );
  assert.notEqual(
    points,
    hashKey(
      comparisonPointsOptions("AAT", { ...pointQuery, domain: "FILMTHICKNESS", metric: "clear" })
        .queryKey,
    ),
  );
  const picker = { domain: "WAVESCAN" as const, month: ["2026-06"], model: "P703" };
  assert.notEqual(
    hashKey(comparisonVehiclesOptions("AAT", picker).queryKey),
    hashKey(
      comparisonVehiclesOptions("AAT", {
        ...picker,
        period: ["2026-06-W4"],
        color: ["Arctic White"],
        q: "VIN",
        offset: 50,
      }).queryKey,
    ),
  );
});
