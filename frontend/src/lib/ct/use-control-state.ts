import { useCallback, useMemo, useState } from "react";
import { computeState } from "@/lib/ct/engine";

/**
 * Control state for the tracking home. `active` is the list of plant ids whose
 * data-feed switch is on (drives map highlight + inline detail). KPI state is
 * held at baseline — the demo engine no longer follows the switches; real feed
 * logic lands later.
 */
export function useControlState() {
  const [active, setActive] = useState<string[]>([]);

  const state = useMemo(() => computeState([]), []);

  const togglePlant = useCallback((plantId: string) => {
    setActive((previous) =>
      previous.includes(plantId) ? previous.filter((id) => id !== plantId) : [...previous, plantId],
    );
  }, []);

  const reset = useCallback(() => setActive([]), []);

  return {
    state,
    active,
    togglePlant,
    reset,
  };
}
