import { useEffect, useState } from "react";

export function useWaveMotion() {
  const [paused, setPaused] = useState(() => {
    try {
      return localStorage.getItem("landing-waves-paused") === "true";
    } catch {
      return false;
    }
  });
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  const toggle = () => {
    setPaused((previous) => {
      const next = !previous;
      try {
        localStorage.setItem("landing-waves-paused", String(next));
      } catch {
        // The current session can still pause when storage is unavailable.
      }
      return next;
    });
  };
  return { paused, reduced, toggle };
}
