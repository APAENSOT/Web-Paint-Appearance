import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { comparisonPointsOptions, comparisonVehiclesOptions } from "@/api/queries";
import {
  comparisonReducer,
  initialComparison,
  visibleVehicles,
  type ComparisonAction,
} from "./comparison-state";

// Owned by PlantMeasurements so Display changes do not discard either workspace.
export function useComparisonVehicles(plant: string, comparisonActive: boolean) {
  const [session, setSession] = useState(() => ({ plant, state: initialComparison() }));
  const state = session.plant === plant ? session.state : initialComparison();
  useEffect(() => {
    if (session.plant !== plant) setSession({ plant, state: initialComparison() });
  }, [plant, session.plant]);
  const dispatch = useCallback(
    (a: ComparisonAction) =>
      setSession((previous) => ({
        plant,
        state: comparisonReducer(
          previous.plant === plant ? previous.state : initialComparison(),
          a,
        ),
      })),
    [plant],
  );
  const enabled = comparisonActive && state.mode === "vehicles";
  const options = useQuery({
    ...comparisonVehiclesOptions(plant, {
      domain: state.domain,
      month: state.months ?? undefined,
      limit: 50,
      offset: 0,
    }),
    enabled,
  });
  useEffect(() => {
    if (options.data && state.months === null)
      dispatch({ type: "defaults", months: options.data.selected_months });
  }, [options.data, state.months, dispatch]);
  const modelValid = !!state.model && !!options.data?.model_options.includes(state.model);
  const candidates = useQuery({
    ...comparisonVehiclesOptions(plant, {
      domain: state.domain,
      model: state.model,
      month: state.months ?? undefined,
      color: state.colors,
      period: state.periods,
      q: state.search,
      limit: 50,
      offset: state.offset,
    }),
    enabled: enabled && modelValid,
  });
  const visible = visibleVehicles(state);
  const points = useQuery({
    ...comparisonPointsOptions(plant, {
      domain: state.domain,
      model: state.model ?? "",
      metric: state.metric,
      vehicle_id: visible.map((v) => v.vehicle_id),
    }),
    enabled: enabled && !!state.model && visible.length > 0,
  });
  return { state, dispatch, options, candidates, points, modelValid, visible };
}
export type ComparisonSession = ReturnType<typeof useComparisonVehicles>;
