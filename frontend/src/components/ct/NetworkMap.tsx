import { useEffect, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { PLANTS, FEED_LEVEL_LABEL, type Plant, type Risk } from "@/lib/ct/data";
import { LAND_PATHS, COUNTRY_BORDERS, GRATICULE } from "@/lib/ct/geo";
import { MonthCountdown } from "@/components/ct/MonthCountdown";

/* Leader-line label offsets — the two Rayong plants sit ~9km apart, so their
   callouts are pushed to opposite sides to never overlap. */
const PLANT_LABEL: Record<string, [number, number]> = {
  "ryg-a": [-46, -18],
  "ryg-b": [46, 26],
  had: [40, -18],
  svt: [-52, 22],
};

const W = 1000;
const H = 620;

const LEVEL_VAR: Record<string, string> = {
  nominal: "var(--nominal)",
  caution: "var(--caution)",
  critical: "var(--critical)",
};

const syncLabel = (min: number) =>
  min < 60 ? `${min} min ago` : `${Math.floor(min / 60)}h ${min % 60}m ago`;

export function NetworkMap({
  highlighted = [],
  feedMode = false,
}: {
  highlighted?: string[];
  /** true while any feed switch is on — legend switches to update-latency words */
  feedMode?: boolean;
}) {
  const [hover, setHover] = useState<{ p: Plant; x: number; y: number } | null>(null);
  const anyHighlighted = highlighted.length > 0;
  const navigate = useNavigate();
  /* plant dashboard drill-in — every status dot opens its plant page; the
     live dashboard content ships for FTM first, the others render blank */
  const openPlant = (p: Plant) => {
    void navigate({ to: "/plant/$code", params: { code: p.code.toLowerCase() } });
  };

  /* ---- pan / zoom (viewport transform in SVG user space) ---- */
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  const drag = useRef<{ px: number; py: number; moved: boolean } | null>(null);
  const [dragging, setDragging] = useState(false);

  const K_MIN = 0.45;
  const K_MAX = 8;

  const clamp = (v: { k: number; x: number; y: number }) => {
    const k = Math.min(K_MAX, Math.max(K_MIN, v.k));
    // pan range: at k>1 the map is larger than the frame (bounds are negative);
    // at k<=1 it is smaller, so it may slide anywhere inside the frame.
    const bx = W * (1 - k);
    const by = H * (1 - k);
    // a little slack at k === 1 so dragging still feels responsive
    const pad = k <= 1 ? 0.18 * W : 0;
    return {
      k,
      x: Math.max(Math.min(0, bx) - pad, Math.min(Math.max(0, bx) + pad, v.x)),
      y: Math.max(Math.min(0, by) - pad, Math.min(Math.max(0, by) + pad, v.y)),
    };
  };

  /** zoom about a point given in SVG user space */
  const zoomAt = (factor: number, sx: number, sy: number) => {
    setView((v) => {
      const k = Math.min(K_MAX, Math.max(K_MIN, v.k * factor));
      const wx = (sx - v.x) / v.k;
      const wy = (sy - v.y) / v.k;
      return clamp({ k, x: sx - wx * k, y: sy - wy * k });
    });
  };

  /** SVG uses preserveAspectRatio="slice", so map client px -> viewBox units by the larger scale. */
  const viewScale = (r: DOMRect) => Math.max(r.width / W, r.height / H);
  const toView = (r: DOMRect, cx: number, cy: number) => {
    const s = viewScale(r);
    return {
      x: (cx - r.left - (r.width - W * s) / 2) / s,
      y: (cy - r.top - (r.height - H * s) / 2) / s,
    };
  };

  // frame size drives the HTML overlay math (SVG is "slice"-scaled)
  const [frame, setFrame] = useState({ w: W, h: H });
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) =>
      setFrame({ w: e.contentRect.width, h: e.contentRect.height }),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // wheel zoom needs a non-passive native listener to stop page scroll
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const dy = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 100 : 1);
      const r = el.getBoundingClientRect();
      const p = toView(r, e.clientX, e.clientY);
      zoomAt(Math.exp(-dy * 0.0018), p.x, p.y);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // Vault map: toView/zoomAt close over view state; rebinding on every pan would drop the listener.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="panel relative flex flex-col overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold tracking-tight">IMG Plant Location</h2>
          <span className="text-xs text-muted-foreground" />

          <MonthCountdown />
        </div>
        <div className="flex items-center gap-3">
          {(["nominal", "caution", "critical"] as const).map((l) => (
            <span key={l} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <i
                className="inline-block size-2 rounded-full"
                style={{ backgroundColor: LEVEL_VAR[l] }}
              />
              {/* word swap on feed-mode toggle — remount replays the rise
                  animation so the label changes feel like the count-up */}
              <span key={feedMode ? "feed" : "base"} className="inline-block animate-rise">
                {feedMode ? FEED_LEVEL_LABEL[l as Risk] : <span className="capitalize">{l}</span>}
              </span>
            </span>
          ))}
        </div>
      </header>

      <div
        ref={frameRef}
        /* fixed viewBox aspect — slice-cropping a taller frame would cut the
           outer plants (Silverton, Hai Duong) out of view */
        className="relative w-full touch-none overflow-hidden [aspect-ratio:1000/620]"
      >
        <svg
          viewBox="0 0 1000 620"
          preserveAspectRatio="xMidYMid slice"
          className="absolute inset-0 size-full"
          style={{ cursor: dragging ? "grabbing" : "grab" }}
          onMouseLeave={() => {
            setHover(null);
            drag.current = null;
            setDragging(false);
          }}
          onPointerDown={(e) => {
            if (e.button !== 0) return;
            drag.current = { px: e.clientX, py: e.clientY, moved: false };
            setDragging(true);
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (!d) return;
            const r = frameRef.current?.getBoundingClientRect();
            if (!r) return;
            const sc = viewScale(r);
            const dx = (e.clientX - d.px) / sc;
            const dy = (e.clientY - d.py) / sc;

            if (Math.abs(dx) + Math.abs(dy) > 1) {
              d.moved = true;
              setHover(null);
            }
            d.px = e.clientX;
            d.py = e.clientY;
            setView((v) => clamp({ ...v, x: v.x + dx, y: v.y + dy }));
          }}
          onPointerUp={() => {
            drag.current = null;
            setDragging(false);
          }}
          onDoubleClick={(e) => {
            const r = frameRef.current?.getBoundingClientRect();
            if (!r) return;
            const p = toView(r, e.clientX, e.clientY);
            zoomAt(1.8, p.x, p.y);
          }}
        >
          <defs>
            <linearGradient id="ct-land" x1="0" y1="0" x2="0.4" y2="1">
              <stop offset="0%" stopColor="var(--map-land-a)" stopOpacity="0.95" />
              <stop offset="100%" stopColor="var(--map-land-b)" stopOpacity="0.8" />
            </linearGradient>

            <pattern id="ct-grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M40 0 H0 V40" fill="none" stroke="var(--hairline)" strokeWidth="0.7" />
            </pattern>
            <filter id="ct-soft" x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation="5" />
            </filter>
          </defs>

          <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            <rect width="1000" height="620" fill="url(#ct-grid)" opacity="0.4" />

            {/* graticule */}
            <g fill="none" stroke="var(--hairline)" strokeWidth="0.7">
              {GRATICULE.map((d, i) => (
                <path key={i} d={d} />
              ))}
            </g>

            {/* static range rings, centred on the Indian Ocean midpoint */}
            <g transform="translate(500 310)" opacity="0.5">
              <circle r="640" fill="none" stroke="var(--hairline)" strokeWidth="0.8" />
              <circle r="420" fill="none" stroke="var(--hairline)" strokeWidth="0.8" />
              <circle r="220" fill="none" stroke="var(--hairline)" strokeWidth="0.8" />
            </g>

            {/* real coastlines — Natural Earth 110m, Mercator (Indian-Ocean-centred) */}
            <g>
              {LAND_PATHS.map((d, i) => (
                <path
                  key={i}
                  d={d}
                  fill="url(#ct-land)"
                  stroke="var(--signal)"
                  strokeOpacity="0.5"
                  strokeWidth="0.8"
                />
              ))}
              <path
                d={COUNTRY_BORDERS}
                fill="none"
                stroke="var(--signal)"
                strokeOpacity="0.22"
                strokeWidth="0.7"
              />
            </g>

            {/* plant nodes — one status dot per factory, no connecting lanes */}
            <g>
              {PLANTS.map((p, i) => {
                const c = LEVEL_VAR[p.level];
                const hot = p.level !== "nominal";
                const active = hover?.p.id === p.id;
                /* switch-driven selection: chosen plants pop, the rest fade */
                const selected = highlighted.includes(p.id);
                const dimmed = anyHighlighted && !selected;
                const [lx, ly] = PLANT_LABEL[p.id] ?? [40, -18];
                /* demo display offset separates the two Rayong dots (their
                   real coords are ~9 km apart and overlap at this zoom) */
                const ox = p.offset?.[0] ?? 0;
                const oy = p.offset?.[1] ?? 0;
                const pingDelay = `${(i * 0.6) % 2.4}s`;
                return (
                  <g
                    key={p.id}
                    transform={`translate(${p.x + ox} ${p.y + oy})`}
                    opacity={dimmed ? 0.3 : 1}
                    style={{ transition: "opacity .5s ease" }}
                  >
                    {/* selection halo — appears while the plant's switch is on */}
                    {selected && (
                      <circle
                        r="17"
                        fill="none"
                        stroke={c}
                        strokeWidth="1.4"
                        strokeDasharray="4 3"
                        opacity="0.9"
                      />
                    )}
                    {/* live beacon — perpetual ping ring, staggered per plant */}
                    <circle
                      r="6"
                      fill="none"
                      stroke={c}
                      strokeWidth="2"
                      className="animate-ping-live"
                      style={{ animationDelay: pingDelay }}
                    />

                    <circle
                      r={active ? 12.5 : 11}
                      fill="none"
                      stroke={c}
                      strokeOpacity={hot ? 0.45 : 0.18}
                      strokeWidth="1"
                      style={{ transition: "stroke .6s ease, stroke-opacity .6s ease, r .3s ease" }}
                    />
                    <circle
                      r="8.5"
                      fill="var(--panel)"
                      stroke={c}
                      strokeWidth="2"
                      style={{ transition: "stroke .6s ease" }}
                    />
                    <circle
                      r={active ? 4.6 : 4}
                      fill={c}
                      className="animate-dot-blink"
                      style={{
                        transition: "fill .6s ease, r .3s ease",
                        animationDelay: `${(i * 0.6 + 1.2) % 2.4}s`,
                      }}
                    />

                    <line
                      x1="0"
                      y1="0"
                      x2={lx}
                      y2={ly}
                      stroke={c}
                      strokeOpacity="0.5"
                      strokeWidth="0.7"
                      style={{ transition: "stroke .6s ease" }}
                    />
                    <g transform={`translate(${lx} ${ly})`}>
                      <text
                        textAnchor={lx < 0 ? "end" : "start"}
                        className="num"
                        fontSize="11"
                        fontWeight="600"
                        fill="var(--foreground)"
                        letterSpacing="0.08em"
                      >
                        {p.code}
                      </text>
                      <text
                        y="12"
                        textAnchor={lx < 0 ? "end" : "start"}
                        className="num"
                        fontSize="9"
                        fill={c}
                        style={{ transition: "fill .6s ease" }}
                      >
                        {syncLabel(p.lastSyncMin)}
                      </text>
                    </g>

                    {/* hover target — clicking a dot drills into its plant page.
                        Navigate on pointerdown (stopPropagation): the svg parent
                        captures the pointer for panning, which would steal the click. */}
                    <circle
                      r="14"
                      fill="transparent"
                      className="cursor-pointer"
                      onPointerDown={(e) => {
                        e.stopPropagation();
                        openPlant(p);
                      }}
                      onMouseEnter={() => setHover({ p, x: p.x + ox, y: p.y + oy })}
                      onMouseLeave={() => setHover((h) => (h?.p.id === p.id ? null : h))}
                    />
                  </g>
                );
              })}
            </g>
          </g>
        </svg>

        {/* zoom controls */}
        <div
          className="absolute bottom-3 right-3 z-10 flex flex-col overflow-hidden rounded-[var(--radius-sm)] border border-border backdrop-blur-sm"
          style={{ backgroundColor: "var(--header-bg)" }}
        >
          {[
            { k: "+", fn: () => zoomAt(1.5, W / 2, H / 2) },
            { k: "−", fn: () => zoomAt(1 / 1.5, W / 2, H / 2) },
          ].map((b) => (
            <button
              key={b.k}
              onClick={b.fn}
              aria-label={b.k === "+" ? "Zoom in" : "Zoom out"}
              className="num size-7 border-b border-border text-xs text-muted-foreground transition-colors last:border-0 hover:text-foreground"
            >
              {b.k}
            </button>
          ))}
          <button
            onClick={() => setView({ k: 1, x: 0, y: 0 })}
            disabled={view.k === 1 && view.x === 0 && view.y === 0}
            className="border-t border-border px-1.5 py-1 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
          >
            Fit
          </button>
        </div>

        {/* hover card (HTML overlay, positioned in normalized SVG space) */}
        {hover &&
          (() => {
            const sc = Math.max(frame.w / W, frame.h / H);
            const vx = hover.x * view.k + view.x;
            const vy = hover.y * view.k + view.y;
            const px = (frame.w - W * sc) / 2 + vx * sc;
            const py = (frame.h - H * sc) / 2 + vy * sc;
            return (
              <div
                className="pointer-events-none absolute z-20 w-[268px] animate-rise"
                style={{
                  left: `${px}px`,
                  top: `${py}px`,
                  /* `translate` property, not `transform`: the ct-rise animation
                     fills `both` and would keep overriding a transform flip. */
                  translate: `${px > frame.w - 300 ? "calc(-100% - 14px)" : "14px"} ${py > frame.h - 260 ? "calc(-100% - 10px)" : "-10px"}`,
                }}
              >
                <div className="panel" style={{ backgroundColor: "var(--popover)" }}>
                  <div className="flex items-center justify-between border-b border-border px-3 py-2">
                    <span className="num text-[11px] font-semibold text-foreground">
                      {hover.p.code}
                    </span>
                    <span
                      className="rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[11px] font-medium"
                      style={{
                        color: LEVEL_VAR[hover.p.level],
                        backgroundColor: "var(--surface-2)",
                      }}
                    >
                      {feedMode ? (
                        FEED_LEVEL_LABEL[hover.p.level]
                      ) : (
                        <span className="capitalize">{hover.p.level}</span>
                      )}
                    </span>
                  </div>

                  <dl className="space-y-1.5 px-3 py-2.5 text-xs">
                    <Row k="Plant" v={hover.p.name} />
                    <Row k="Country" v={hover.p.country} />
                    <Row k="Line" v={hover.p.line} />
                    <Row k="Data feed" v={FEED_LEVEL_LABEL[hover.p.level]} />
                    <Row
                      k="Last sync"
                      v={<span className="num">{syncLabel(hover.p.lastSyncMin)}</span>}
                    />
                  </dl>
                  <div className="border-t border-border px-3 py-2">
                    <p className="eyebrow mb-1">status detail</p>
                    <p
                      className="text-[11px] leading-snug"
                      style={{ color: LEVEL_VAR[hover.p.level] }}
                    >
                      {hover.p.driver}
                    </p>
                  </div>
                </div>
              </div>
            );
          })()}

        {/* corner telemetry */}
        <div className="pointer-events-none absolute bottom-2 left-3 text-[11px] text-muted-foreground">
          <span className="num">2.00°S / 66.00°E</span> · scale 1:
          <span className="num">{Math.round(64 / view.k)}</span>M · mercator ·{" "}
          <span className="num">{view.k.toFixed(1)}×</span> · scroll to zoom, drag to pan
        </div>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="eyebrow shrink-0 pt-px">{k}</dt>
      <dd className="text-right text-[11px] leading-snug text-foreground">{v}</dd>
    </div>
  );
}
