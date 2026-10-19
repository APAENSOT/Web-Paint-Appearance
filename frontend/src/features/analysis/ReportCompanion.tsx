import { useEffect, useId, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import type { ReportCharacterScene } from "./report-character-scene";
import "./report-companion.css";

/** A local, decorative report guide. It never reads or changes measurement data. */
export type GuideActivity = "ready" | "composing" | "checking";

export function ReportCompanion({ activity = "ready" }: { activity?: GuideActivity }) {
  const root = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLSpanElement>(null);
  const rig = useRef<ReportCharacterScene | null>(null);
  const pauseRef = useRef(false);
  const syncMotion = useRef<() => void>(() => {});
  const [ready, setReady] = useState(false);
  const [greeting, setGreeting] = useState(false);
  const [paused, setPaused] = useState(false);
  const messageId = useId();
  const previousActivity = useRef(activity);
  useEffect(() => {
    if (activity === "composing") rig.current?.look(0, 0.3);
    if (activity === "checking") rig.current?.look(0, 0);
    if (activity === "ready" && previousActivity.current === "checking") rig.current?.nod();
    previousActivity.current = activity;
  }, [activity]);
  useEffect(() => {
    pauseRef.current = paused;
    syncMotion.current();
  }, [paused]);
  useEffect(() => {
    let disposed = false,
      intersecting = true;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const fine = matchMedia("(hover: hover) and (pointer: fine)");
    const allowed = () =>
      !pauseRef.current && intersecting && !document.hidden && !reduced.matches && fine.matches;
    const sync = () => rig.current?.motion(allowed());
    syncMotion.current = sync;
    const follow = (event: PointerEvent) => {
      if (event.pointerType === "touch" || !allowed()) return;
      const bounds = root.current?.getBoundingClientRect();
      if (!bounds) return;
      rig.current?.motion(true);
      rig.current?.look(
        (event.clientX - bounds.x - bounds.width / 2) / 320,
        (event.clientY - bounds.y - bounds.height / 2) / 240,
      );
    };
    const reset = () => rig.current?.motion(false);
    const leave = (event: PointerEvent) => {
      if (!event.relatedTarget) rig.current?.look(0, 0);
    };
    const observer = new IntersectionObserver(([entry]) => {
      intersecting = entry.isIntersecting;
      sync();
    });
    if (root.current) observer.observe(root.current);
    window.addEventListener("pointermove", follow, { passive: true });
    window.addEventListener("pointerout", leave);
    window.addEventListener("blur", reset);
    window.addEventListener("focus", sync);
    document.addEventListener("visibilitychange", sync);
    reduced.addEventListener("change", sync);
    fine.addEventListener("change", sync);
    void import("./report-character-scene")
      .then(({ createReportCharacter }) => {
        if (disposed || !stage.current) return;
        try {
          rig.current = createReportCharacter(
            stage.current,
            () => setReady(false),
            () => setReady(true),
          );
          sync();
        } catch {
          setReady(false);
        }
      })
      .catch(() => {
        if (!disposed) setReady(false);
      });
    return () => {
      disposed = true;
      observer.disconnect();
      window.removeEventListener("pointermove", follow);
      window.removeEventListener("pointerout", leave);
      window.removeEventListener("blur", reset);
      window.removeEventListener("focus", sync);
      document.removeEventListener("visibilitychange", sync);
      reduced.removeEventListener("change", sync);
      fine.removeEventListener("change", sync);
      rig.current?.dispose();
      rig.current = null;
      syncMotion.current = () => {};
    };
  }, []);
  return (
    <div
      ref={root}
      className="report-companion"
      data-activity={activity}
      data-renderer={ready ? "3d" : "fallback"}
    >
      <button
        type="button"
        className="report-companion__button"
        aria-label="Greet the report guide"
        aria-expanded={greeting}
        aria-controls={messageId}
        onClick={(event) => {
          if (event.detail !== 0 && !greeting) rig.current?.nod();
          setGreeting((open) => !open);
        }}
        onBlur={() => setGreeting(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setGreeting(false);
        }}
      >
        <svg
          className="report-companion__circuit"
          viewBox="0 0 116 132"
          fill="none"
          aria-hidden="true"
        >
          <path className="report-companion__bezel" d="M18 1H98L115 18V114L98 131H18L1 114V18Z" />
          <path className="report-companion__edge" d="M20 6H96L110 20V112L96 126H20L6 112V20Z" />
          <circle className="report-companion__ring" cx="58" cy="56" r="47" />
          <path
            className="report-companion__accent"
            d="M25 22A47 47 0 0 1 91 22M104 64A47 47 0 0 1 91 89"
          />
          <path
            className="report-companion__tracks"
            d="M17 12H31M85 12H99M12 100V109L21 118H31M104 100V109L95 118H85"
          />
          <path className="report-companion__ticks" d="M58 8V12M10 56H14M102 56H106M58 100V104" />
          <circle className="report-companion__rivet" cx="14" cy="27" r="1.4" />
          <circle className="report-companion__rivet" cx="102" cy="27" r="1.4" />
          <text className="report-companion__nameplate" x="58" y="119" textAnchor="middle">
            REPORT GUIDE
          </text>
        </svg>
        <span className="report-companion__window">
          <span className="report-companion__body" aria-hidden="true">
            <img
              src="/characters/report-chibi-3d-atlas.webp"
              alt=""
              width="1774"
              height="887"
              draggable={false}
            />
          </span>
          <span className="report-companion__portrait">
            <span className="report-companion__nod">
              <span className="report-companion__idle">
                <img
                  className="report-companion__base"
                  src="/characters/report-chibi-3d-atlas.webp"
                  alt=""
                  width="1774"
                  height="887"
                  draggable={false}
                />
              </span>
            </span>
          </span>
          <span ref={stage} className="report-companion__scene" aria-hidden="true" />
        </span>
      </button>
      <button
        type="button"
        className="report-companion__pause"
        aria-label={paused ? "Play character animation" : "Pause character animation"}
        title={paused ? "Play character animation" : "Pause character animation"}
        onClick={() => setPaused((value) => !value)}
      >
        <span>
          {paused ? <Play size={12} aria-hidden="true" /> : <Pause size={12} aria-hidden="true" />}
        </span>
      </button>
      <div
        id={messageId}
        role="status"
        aria-live="polite"
        className="report-companion__message"
        hidden={!greeting}
      >
        Ready when you are. Choose a month to explore your report.
      </div>
    </div>
  );
}
