import { useEffect, useRef } from "react";
import { Home, Minus, Plus, Scan } from "lucide-react";
import type { StudioScene, StudioView } from "./scene";

const FACES = [
  ["top", "Top", "top"],
  ["under", "Bottom", "bottom"],
  ["front", "Front", "left"],
  ["rear", "Rear", "right"],
  ["side", "Left", "front"],
  ["opposite", "Right", "back"],
] as const;

export function ViewCube({
  scene,
  ready,
  workshop,
  onView,
  onFit,
}: {
  scene: StudioScene | null;
  ready: boolean;
  workshop: boolean;
  onView: (view: StudioView) => void;
  onFit: () => void;
}) {
  const cube = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scene?.navigationCube(cube.current);
    return () => scene?.navigationCube(null);
  }, [scene, ready]);
  return (
    <div className="studio-cad-nav" aria-label="3D camera controls">
      <div className="studio-cube-perspective">
        <div ref={cube} className="studio-view-cube">
          {FACES.map(([view, label, face]) => (
            <button
              type="button"
              key={view}
              className={`studio-cube-face cube-${face}`}
              disabled={!ready}
              onClick={() => onView(view)}
              aria-label={`${label} view`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <label className="sr-only" htmlFor="studio-camera-view">
        Camera view
      </label>
      <select
        id="studio-camera-view"
        aria-label="Camera view"
        value=""
        disabled={!ready}
        onChange={(event) => onView(event.target.value as StudioView)}
      >
        <option value="" disabled>
          Set view
        </option>
        <option value="body">Isometric</option>
        {FACES.map(([view, label]) => (
          <option key={view} value={view}>
            {label}
          </option>
        ))}
      </select>
      <div className="studio-cad-buttons">
        <button
          type="button"
          aria-label={workshop ? "Workshop view" : "Isometric view"}
          disabled={!ready}
          onClick={() => onView(workshop ? "workshop" : "body")}
        >
          <Home size={16} aria-hidden="true" />
        </button>
        <button type="button" aria-label="Fit model or panel" disabled={!ready} onClick={onFit}>
          <Scan size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="Zoom in"
          disabled={!ready}
          onClick={(event) => scene?.zoom("in", event.detail !== 0)}
        >
          <Plus size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          disabled={!ready}
          onClick={(event) => scene?.zoom("out", event.detail !== 0)}
        >
          <Minus size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
