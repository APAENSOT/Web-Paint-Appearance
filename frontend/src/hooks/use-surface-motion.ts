import { useCallback, useEffect, useLayoutEffect, useRef } from "react";

/** Animate a changed surface once, without remounting its charts or WebGL canvas. */
export function useSurfaceMotion(key: string, direction = 1) {
  const ref = useRef<HTMLDivElement>(null);
  const previous = useRef(key);
  const pointer = useRef(false);
  const running = useRef<Animation | null>(null);
  const cancel = useCallback(() => {
    running.current?.cancel();
    running.current = null;
  }, []);
  useEffect(() => {
    const preference = matchMedia("(prefers-reduced-motion: reduce)");
    const changed = () => {
      if (preference.matches) cancel();
    };
    preference.addEventListener("change", changed);
    return () => {
      preference.removeEventListener("change", changed);
      cancel();
    };
  }, [cancel]);
  useLayoutEffect(() => {
    if (previous.current === key) return;
    previous.current = key;
    cancel();
    const surface = ref.current;
    if (
      !surface ||
      !pointer.current ||
      matchMedia("(prefers-reduced-motion: reduce)").matches ||
      !surface.animate
    )
      return;
    const tokens = getComputedStyle(surface);
    running.current = surface.animate(
      [
        { opacity: 0.65, transform: `translateX(${direction * 8}px)` },
        { opacity: 1, transform: "translateX(0)" },
      ],
      {
        duration: Number.parseFloat(tokens.getPropertyValue("--dur-base")) || 240,
        easing: tokens.getPropertyValue("--ease-ct").trim() || "ease-out",
      },
    );
  }, [key, direction, cancel]);
  return {
    ref,
    onPointerDownCapture: () => {
      pointer.current = true;
    },
    onClickCapture: (event: React.MouseEvent) => {
      pointer.current = event.detail !== 0;
    },
    onKeyDownCapture: () => {
      pointer.current = false;
      cancel();
    },
  };
}
