import { useEffect, useRef, useState } from "react";

/**
 * Small shared count-up hook.
 *
 * Concept: every percentage in the system animates from its previous value to
 * the new one instead of jumping — the "instrument settling" feel of a factory
 * console.
 *
 * Function note: pure presentation, no data logic. Respects
 * prefers-reduced-motion by snapping straight to the target.
 */
export function useCountUp(target: number, duration = 480) {
  const [value, setValue] = useState(target);
  const from = useRef(target);
  const raf = useRef<number>(0);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      from.current = target;
      setValue(target);
      return;
    }

    const start = performance.now();
    const a = from.current;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(a + (target - a) * eased);
      if (t < 1) raf.current = requestAnimationFrame(tick);
      else from.current = target;
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, duration]);

  return value;
}
