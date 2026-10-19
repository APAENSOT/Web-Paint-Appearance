import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

/** Inlined in <head> before paint so a saved theme never flashes. Dark is the default. */
export const THEME_BOOTSTRAP = `(function(){try{var t=localStorage.getItem("ct-theme");if(t!=="dark"&&t!=="light"){t="dark";}document.documentElement.classList.toggle("dark",t==="dark");document.documentElement.style.colorScheme=t;}catch(e){}})();`;

export function ThemeToggle({ variant = "compact" }: { variant?: "compact" | "pill" }) {
  // Server renders the dark default; the bootstrap script has already set the
  // real class, so we read it back after hydration rather than guessing.
  const [theme, setTheme] = useState<Theme>("dark");
  const [animate, setAnimate] = useState(true);

  useEffect(() => {
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
  }, []);

  const apply = (next: Theme) => {
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
    document.documentElement.style.colorScheme = next;
    try {
      localStorage.setItem("ct-theme", next);
    } catch {
      /* storage unavailable (private mode) — theme still applies for this session */
    }
  };

  const dark = theme === "dark";

  if (variant === "pill") {
    return (
      <button
        type="button"
        role="switch"
        aria-label="Dark theme"
        aria-checked={dark}
        title={dark ? "Switch to light theme" : "Switch to dark theme"}
        onClick={(event) => {
          setAnimate(event.detail !== 0);
          apply(dark ? "light" : "dark");
        }}
        className="theme-toggle"
        data-theme={theme}
        data-motion={animate ? "animated" : "instant"}
      >
        <span className="theme-toggle__night" aria-hidden="true" />
        <svg className="theme-toggle__sky" viewBox="0 0 84 44" aria-hidden="true">
          <g className="theme-toggle__day-motes" fill="currentColor">
            <circle cx="61" cy="13" r="3.2" />
            <circle cx="52" cy="25" r="1.6" />
          </g>
          <g className="theme-toggle__stars" fill="currentColor">
            <path d="m17 11 1.3 3.1 3.2 1.3-3.2 1.3-1.3 3.1-1.3-3.1-3.2-1.3 3.2-1.3Z" />
            <path d="m30 25 1 2.4 2.4 1-2.4 1-1 2.4-1-2.4-2.4-1 2.4-1Z" />
            <circle cx="34" cy="12" r="1.2" />
            <circle cx="11" cy="29" r="1" />
          </g>
        </svg>
        <span className="theme-toggle__thumb" aria-hidden="true">
          <svg viewBox="0 0 32 32" className="theme-toggle__orb">
            <circle className="theme-toggle__sun" cx="16" cy="16" r="13" fill="currentColor" />
            <path
              className="theme-toggle__moon"
              d="M15 3a13 13 0 1 1-9 22A12 12 0 0 0 15 3Z"
              fill="currentColor"
            />
          </svg>
        </span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => apply(dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      className="grid size-11 shrink-0 place-items-center rounded-[var(--radius-sm)] border border-border text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
    >
      {dark ? (
        <svg
          viewBox="0 0 24 24"
          className="size-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
        >
          <circle cx="12" cy="12" r="4" />
          <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" />
        </svg>
      ) : (
        <svg
          viewBox="0 0 24 24"
          className="size-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
        >
          <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5Z" />
        </svg>
      )}
    </button>
  );
}
