import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { Minus, Plus } from "lucide-react";
import { PLANTS, FEED_LEVEL_LABEL, type Plant } from "@/lib/ct/data";
import { sinceText, type PlantFeed } from "./plant-feed";
import { FactoryLandmark } from "./FactoryLandmark";
import { LAND_PATHS, COUNTRY_BORDERS, GRATICULE, PLANT_COUNTRIES } from "@/lib/ct/geo";
import { MonthCountdown } from "@/components/ct/MonthCountdown";
import { project as geoProject } from "@/lib/ct/geo";

type View = { k: number; x: number; y: number };
const INITIAL: View = { k: 1, x: 0, y: 0 };
const W = 1000;
const H = 620;
const COUNTRIES = ["Thailand", "Vietnam", "South Africa"];

function constrain(v: View): View {
  const k = Math.max(0.65, Math.min(9, v.k));
  return {
    k,
    x: Math.max(-W * k + 120, Math.min(W - 120, v.x)),
    y: Math.max(-H * k + 90, Math.min(H - 90, v.y)),
  };
}

export function PlantExplorerMap({
  feeds,
  country,
  selectedPlant,
  onCountry,
  onPlant,
  reduced,
  highlighted,
  paused,
  onHighlight,
}: {
  feeds: Record<string, PlantFeed>;
  country: string | null;
  selectedPlant: string | null;
  onCountry: (country: string | null) => void;
  onPlant: (plant: Plant) => void;
  reduced: boolean;
  highlighted: string[];
  paused: boolean;
  onHighlight: (id: string | null) => void;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const [tabIndicator, setTabIndicator] = useState({ x: 0, width: 0 });
  const [tooltip, setTooltip] = useState<string | null>(null);
  const viewRef = useRef<View>(INITIAL);
  const animation = useRef(0);
  const [view, setView] = useState<View>(INITIAL);
  const [frame, setFrame] = useState({ width: W, height: H });
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const update = () => {
      const button = nav.querySelector<HTMLButtonElement>('button[aria-pressed="true"]');
      if (button) setTabIndicator({ x: button.offsetLeft, width: button.offsetWidth });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(nav);
    return () => observer.disconnect();
  }, [country]);
  const drag = useRef<{
    x: number;
    y: number;
    startX: number;
    startY: number;
    moved: boolean;
    country: string | null;
  } | null>(null);
  const apply = useCallback((next: View) => {
    viewRef.current = next;
    setView(next);
  }, []);
  const stop = useCallback(() => cancelAnimationFrame(animation.current), []);
  const flyTo = useCallback(
    (target: View) => {
      stop();
      if (reduced) {
        apply(target);
        return;
      }
      const start = viewRef.current;
      const began = performance.now();
      const tick = (now: number) => {
        const progress = Math.min(1, (now - began) / 520);
        const eased = 1 - Math.pow(1 - progress, 4);
        apply({
          k: start.k + (target.k - start.k) * eased,
          x: start.x + (target.x - start.x) * eased,
          y: start.y + (target.y - start.y) * eased,
        });
        if (progress < 1) animation.current = requestAnimationFrame(tick);
      };
      animation.current = requestAnimationFrame(tick);
    },
    [apply, reduced, stop],
  );

  useEffect(() => {
    const selected = PLANT_COUNTRIES.find((c) => c.name === country);
    if (!selected) {
      flyTo(INITIAL);
      return stop;
    }
    const [[x0, y0], [x1, y1]] = selected.bounds;
    const k = Math.min(7, Math.min(W / (x1 - x0 + 60), H / (y1 - y0 + 70)) * 0.82);
    flyTo({ k, x: W / 2 - ((x0 + x1) / 2) * k, y: H / 2 - ((y0 + y1) / 2) * k });
    return stop;
  }, [country, flyTo, stop]);

  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) =>
      setFrame({ width: entry.contentRect.width, height: entry.contentRect.height }),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const zoom = useCallback(
    (factor: number, x = W / 2, y = H / 2) => {
      stop();
      const old = viewRef.current;
      const k = Math.max(0.65, Math.min(9, old.k * factor));
      apply(constrain({ k, x: x - ((x - old.x) / old.k) * k, y: y - ((y - old.y) / old.k) * k }));
    },
    [apply, stop],
  );

  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const wheel = (event: WheelEvent) => {
      // Ordinary scrolling belongs to the page; modified scrolling zooms the map.
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      const scale = Math.min(rect.width / W, rect.height / H);
      const x = (event.clientX - rect.left - (rect.width - W * scale) / 2) / scale;
      const y = (event.clientY - rect.top - (rect.height - H * scale) / 2) / scale;
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 100 : 1);
      zoom(Math.exp(-delta * 0.0018), x, y);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [zoom]);

  const scale = Math.min(frame.width / W, frame.height / H);
  const project = (x: number, y: number) => ({
    x: (frame.width - W * scale) / 2 + (x * view.k + view.x) * scale,
    y: (frame.height - H * scale) / 2 + (y * view.k + view.y) * scale,
  });

  return (
    <section className="panel plant-map" aria-label="Plant location explorer">
      <header className="plant-map__header">
        <div>
          <h2>IMG Plant Location</h2>
          <p>Explore the manufacturing network</p>
        </div>
        <MonthCountdown />
      </header>
      <nav ref={navRef} className="plant-map__countries" aria-label="Explore countries">
        <span
          aria-hidden="true"
          className="plant-map__tab-indicator"
          style={{ width: tabIndicator.width, transform: `translateX(${tabIndicator.x}px)` }}
        />
        <button type="button" onClick={() => onCountry(null)} aria-pressed={!country}>
          All plants
          <span>4</span>
        </button>
        {COUNTRIES.map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={country === name}
            onClick={() => onCountry(name)}
          >
            {name}
            <span>{PLANTS.filter((p) => p.country === name).length}</span>
          </button>
        ))}
      </nav>
      <div
        ref={frameRef}
        className="plant-map__viewport"
        data-country={country ?? "all"}
        data-zoom={view.k.toFixed(3)}
      >
        <svg
          viewBox="0 0 1000 620"
          className="plant-map__geography"
          aria-label="Map of plant countries"
          style={{ cursor: dragging ? "grabbing" : "grab" }}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            stop();
            const target = (event.target as Element).closest("[data-country-name]");
            drag.current = {
              x: event.clientX,
              y: event.clientY,
              startX: event.clientX,
              startY: event.clientY,
              moved: false,
              country: target?.getAttribute("data-country-name") ?? null,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
            setDragging(true);
          }}
          onPointerMove={(event) => {
            const current = drag.current;
            if (!current) return;
            if (Math.hypot(event.clientX - current.startX, event.clientY - current.startY) > 5)
              current.moved = true;
            if (current.moved) {
              const old = viewRef.current;
              apply(
                constrain({
                  ...old,
                  x: old.x + (event.clientX - current.x) / scale,
                  y: old.y + (event.clientY - current.y) / scale,
                }),
              );
            }
            current.x = event.clientX;
            current.y = event.clientY;
          }}
          onPointerUp={(event) => {
            const current = drag.current;
            drag.current = null;
            setDragging(false);
            event.currentTarget.releasePointerCapture(event.pointerId);
            if (current && !current.moved && current.country) onCountry(current.country);
          }}
          onPointerCancel={() => {
            drag.current = null;
            setDragging(false);
          }}
        >
          <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            <g fill="none" stroke="var(--hairline)" strokeWidth="0.6">
              {GRATICULE.map((path, index) => (
                <path key={index} d={path} vectorEffect="non-scaling-stroke" />
              ))}
            </g>
            <g fill="var(--map-land-a)" stroke="var(--hairline)" strokeWidth="0.8">
              {LAND_PATHS.map((path, index) => (
                <path key={index} d={path} vectorEffect="non-scaling-stroke" />
              ))}
            </g>
            <path
              d={COUNTRY_BORDERS}
              fill="none"
              stroke="var(--hairline)"
              vectorEffect="non-scaling-stroke"
            />
            {PLANT_COUNTRIES.map((item) => (
              <path
                key={item.id}
                d={item.path}
                data-country-name={item.name}
                data-selected={country === item.name}
                className="plant-map__country"
                vectorEffect="non-scaling-stroke"
              >
                <title>{item.name} — select to explore plants</title>
              </path>
            ))}
          </g>
        </svg>
        <div className="plant-map__place-labels" aria-hidden="true">
          {[["Indian Ocean", 72, -17]].map(([name, lon, lat]) => {
            if (country && country !== name) return null;
            // Country tabs carry names on compact overview; keep clustered factories clear.
            if (frame.width < 520 && !country) return null;
            const location = geoProject(Number(lon), Number(lat));
            const point = project(location.x, location.y);
            if (
              point.x < 65 ||
              point.x > frame.width - 65 ||
              point.y < 25 ||
              point.y > frame.height - 60
            )
              return null;
            return (
              <span
                key={name}
                data-ocean={name === "Indian Ocean"}
                style={{
                  left: point.x,
                  top: point.y,
                }}
              >
                {name}
              </span>
            );
          })}
        </div>
        {PLANTS.filter((plant) => !country || plant.country === country).map((plant) => {
          const point = project(plant.x, plant.y);
          const status = feeds[plant.code]?.status;
          const feed = feeds[plant.code];
          const last = feeds[plant.code]?.latest[0];
          // Rayong plants are only ~9km apart. Screen-space callouts preserve both hit targets.
          const compactOverview = frame.width < 520 && !country;
          const offset = compactOverview
            ? ({ "ryg-a": { x: -52, y: -12 }, "ryg-b": { x: 20, y: 45 }, had: { x: 0, y: -42 } }[
                plant.id
              ] ?? { x: 0, y: 0 })
            : plant.id === "ryg-a"
              ? { x: -34, y: -26 }
              : plant.id === "ryg-b"
                ? { x: 34, y: 26 }
                : { x: 0, y: 0 };
          const x = point.x + offset.x;
          const y = point.y + offset.y;
          if (x < 20 || x > frame.width - 20 || y < 25 || y > frame.height - 30) return null;
          return (
            <div key={plant.id}>
              <svg className="plant-map__leaders" aria-hidden="true">
                <line
                  x1={point.x}
                  y1={point.y}
                  x2={x}
                  y2={y}
                  stroke="var(--signal)"
                  strokeOpacity="0.6"
                />
                <circle cx={point.x} cy={point.y} r="2.5" fill="var(--signal)" />
              </svg>
              <button
                type="button"
                className="plant-map__pin"
                style={
                  {
                    transform: `translate(${x}px, ${y}px)`,
                    "--plant-status": status ? `var(--${status.level})` : "var(--muted-foreground)",
                  } as CSSProperties
                }
                onClick={() => onPlant(plant)}
                onMouseEnter={() => {
                  setTooltip(plant.id);
                  onHighlight(plant.id);
                }}
                onMouseLeave={() => {
                  setTooltip(null);
                  onHighlight(null);
                }}
                onFocus={() => {
                  setTooltip(plant.id);
                  onHighlight(plant.id);
                }}
                onBlur={() => {
                  setTooltip(null);
                  onHighlight(null);
                }}
                aria-describedby={tooltip === plant.id ? `map-tooltip-${plant.id}` : undefined}
                aria-label={`Preview ${plant.code}, ${plant.country}`}
                aria-pressed={selectedPlant === plant.id}
                data-highlighted={highlighted.includes(plant.id)}
              >
                <FactoryLandmark code={plant.code} paused={paused || reduced} />
                <span className="plant-map__label">{plant.code}</span>
              </button>
              {country && (
                <span className="plant-map__city" style={{ left: x, top: y + 53 }}>
                  {plant.code === "FVL"
                    ? "Hai Duong"
                    : plant.code === "SAP"
                      ? "Silverton · Pretoria"
                      : "Rayong"}
                </span>
              )}
              {tooltip === plant.id && (
                <div
                  role="tooltip"
                  id={`map-tooltip-${plant.id}`}
                  className="plant-map__tooltip"
                  style={{
                    left: Math.max(12, Math.min(frame.width - 232, x - 110)),
                    top: y > 155 ? y - 147 : y + 80,
                  }}
                >
                  <strong>
                    {plant.code} · {plant.name}
                  </strong>
                  <span>
                    Data feed:{" "}
                    {status
                      ? FEED_LEVEL_LABEL[status.level]
                      : feed?.pending
                        ? "Checking…"
                        : feed?.error
                          ? "Unavailable"
                          : "No control plan"}
                  </span>
                  <span>
                    Last upload:{" "}
                    {last
                      ? `${sinceText(last.started_at)} ago`
                      : feed?.pending
                        ? "Checking…"
                        : feed?.error
                          ? "Unavailable"
                          : "None yet"}
                  </span>
                  <small>Select to preview</small>
                </div>
              )}
            </div>
          );
        })}
        <div className="plant-map__zoom">
          {country && (
            <button type="button" className="plant-map__reset" onClick={() => onCountry(null)}>
              Show all plants
            </button>
          )}
          {!country && (view.k !== INITIAL.k || view.x !== INITIAL.x || view.y !== INITIAL.y) && (
            <button type="button" className="plant-map__reset" onClick={() => flyTo(INITIAL)}>
              Reset map
            </button>
          )}
          <button type="button" aria-label="Zoom in" onClick={() => zoom(1.4)}>
            <Plus size={16} />
          </button>
          <button type="button" aria-label="Zoom out" onClick={() => zoom(1 / 1.4)}>
            <Minus size={16} />
          </button>
        </div>
        <div className="plant-map__hint">
          {country ? `Select a plant in ${country}` : "Select a country or a plant"}
        </div>
      </div>
      <footer className="plant-map__footer">
        <span>
          {country
            ? `${country} · ${PLANTS.filter((p) => p.country === country).length} plants`
            : "3 countries · 4 plants"}
        </span>
        <span>Drag to pan · + / − or Ctrl / ⌘ + scroll to zoom</span>
      </footer>
    </section>
  );
}
