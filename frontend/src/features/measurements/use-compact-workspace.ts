import { useEffect, useState } from "react";

/** Match the layout breakpoint, rather than the device or input type. */
export function useCompactWorkspace() {
  const [compact, setCompact] = useState(() => window.matchMedia("(max-width: 1023px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1023px)");
    const update = () => setCompact(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return compact;
}
