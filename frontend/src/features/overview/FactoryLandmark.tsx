import { useEffect, useRef, useState } from "react";
import { FACTORY_DESIGNS, type Vec3 } from "./factory-design";

export function FactorySmoke({ paused }: { paused: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const [hidden, setHidden] = useState(() => typeof document === "undefined" || document.hidden);
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    if (ref.current) observer.observe(ref.current);
    const sync = () => setHidden(document.hidden);
    sync();
    document.addEventListener("visibilitychange", sync);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", sync);
    };
  }, []);
  return (
    <span
      ref={ref}
      className="factory-smoke"
      data-running={!paused && visible && !hidden}
      aria-hidden="true"
    >
      <i />
      <i />
      <i />
    </span>
  );
}

const project = ([x, y, z]: Vec3) => [70 + (x - z) * 9, 49 + (x + z) * 4.2 - y * 14];
const polygon = (points: Vec3[]) => points.map((point) => project(point).join(",")).join(" ");

export function FactoryLandmark({ code, paused }: { code: string; paused: boolean }) {
  const design = FACTORY_DESIGNS[code] ?? FACTORY_DESIGNS.FTM;
  const smoke = project(design.vent);
  return (
    <span className="factory-landmark" data-factory={code} aria-hidden="true">
      <svg viewBox="0 0 140 90" className="factory-landmark__model">
        {design.parts
          .slice()
          .sort(
            (a, b) =>
              a.position[0] +
              a.position[2] +
              a.position[1] * 0.7 -
              (b.position[0] + b.position[2] + b.position[1] * 0.7),
          )
          .map((part, index) => {
            const [x, y, z] = part.position;
            const [w, h, d] = part.size.map((size) => size / 2);
            return (
              <g key={index} fill={`var(--factory-${part.material})`}>
                <polygon
                  points={polygon([
                    [x - w, y - h, z + d],
                    [x + w, y - h, z + d],
                    [x + w, y + h, z + d],
                    [x - w, y + h, z + d],
                  ])}
                />
                <polygon
                  points={polygon([
                    [x + w, y - h, z - d],
                    [x + w, y - h, z + d],
                    [x + w, y + h, z + d],
                    [x + w, y + h, z - d],
                  ])}
                  style={{ filter: "brightness(.78)" }}
                />
                <polygon
                  points={polygon([
                    [x - w, y + h, z - d],
                    [x + w, y + h, z - d],
                    [x + w, y + h, z + d],
                    [x - w, y + h, z + d],
                  ])}
                  style={{ filter: "brightness(1.12)" }}
                />
              </g>
            );
          })}
      </svg>
      <span
        className="factory-landmark__vent"
        style={{ left: `${smoke[0] / 1.4}%`, top: `${smoke[1] / 0.9}%` }}
      >
        <FactorySmoke paused={paused} />
      </span>
    </span>
  );
}
