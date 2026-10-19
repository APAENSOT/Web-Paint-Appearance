import { useEffect, useRef, useState } from "react";
import { ArrowLeft, RotateCcw, Minus, Plus } from "lucide-react";
import { createStudio, type StudioScene, type StudioState, type StudioView } from "../scene";
import { PREPARED_BODIES } from "../body-assets";
import { ViewCube } from "../ViewCube";
import "../../../../styles.css";
import "../model-studio.css";
import "./review.css";

// Visual asset metadata only. These identifiers are deliberately not Standard model codes.
const assets = [
  {
    id: "ranger",
    label: "Ranger double cab",
    detail: "Accepted studio body",
    note: "Existing accepted geometry and point coordinates are unchanged.",
    url: "/models/ranger/ranger-body.glb?v=20261012-b-pillars",
  },
  ...Object.values(PREPARED_BODIES).map((asset) => ({ ...asset, detail: "Repaired body shell" })),
];
export function Review() {
  const [selected, setSelected] = useState(0);
  const [state, setState] = useState<StudioState>({
    status: "Loading body…",
    ready: false,
    painting: false,
    error: false,
  });
  const [shade, setShade] = useState("#397da9");
  const [metallic, setMetallic] = useState(true);
  const [animate, setAnimate] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [workshop, setWorkshop] = useState(true);
  const stage = useRef<HTMLDivElement>(null);
  const scene = useRef<StudioScene | null>(null);
  const asset = assets[selected];
  useEffect(() => {
    if (!stage.current) return;
    setWorkshop(true);
    setState({ status: `Loading ${asset.label}…`, ready: false, painting: false, error: false });
    const studio = createStudio(stage.current, setState, {
      url: asset.url ?? `/models/prepared/${asset.id}-body.glb?v=20261013-repair-2`,
      label: asset.label,
    });
    scene.current = studio;
    return () => {
      studio.dispose();
      scene.current = null;
    };
  }, [asset, attempt]);
  const view = (name: StudioView) => {
    setWorkshop(name === "workshop");
    scene.current?.view(name);
  };
  return (
    <main className="asset-review">
      <header className="asset-review-header">
        <div>
          <a href="/plant/ftm">
            <ArrowLeft size={16} /> Back to Model Detail
          </a>
          <h1>Body model preparation</h1>
          <p>
            Compare the repaired shells. They are also available in Model Detail for their Standard
            models.
          </p>
        </div>
        <span className="asset-review-status">Geometry review · No profile writes</span>
      </header>
      <div className="asset-review-layout">
        <nav aria-label="Body models" className="asset-review-list">
          {assets.map((item, index) => (
            <button
              type="button"
              key={item.id}
              aria-pressed={selected === index}
              onClick={() => setSelected(index)}
            >
              <strong>{item.label}</strong>
              <span>{item.detail}</span>
            </button>
          ))}
        </nav>
        <section className="asset-review-main" aria-label={asset.label}>
          <div className="asset-review-heading">
            <h2>{asset.label}</h2>
            <p>{asset.note}</p>
          </div>
          <div className="asset-review-stage-wrap model-studio">
            <div ref={stage} className="studio-stage asset-review-stage" />
            <ViewCube
              scene={scene.current}
              ready={state.ready}
              workshop={workshop}
              onView={view}
              onFit={() => view("body")}
            />
            <span className="asset-review-orbit">Drag to orbit · Scroll to zoom</span>
          </div>
          <div className="asset-review-tools">
            <button type="button" onClick={() => view("workshop")} disabled={!state.ready}>
              Workshop
            </button>
            <button type="button" onClick={() => view("body")} disabled={!state.ready}>
              Body view
            </button>
            <button
              type="button"
              aria-label="Zoom in"
              onClick={() => scene.current?.zoom("in")}
              disabled={!state.ready}
            >
              <Plus size={18} />
            </button>
            <button
              type="button"
              aria-label="Zoom out"
              onClick={() => scene.current?.zoom("out")}
              disabled={!state.ready}
            >
              <Minus size={18} />
            </button>
            <label>
              Preview colour{" "}
              <input
                aria-label="Preview colour"
                type="color"
                value={shade}
                onChange={(event) => setShade(event.target.value)}
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={metallic}
                onChange={(event) => setMetallic(event.target.checked)}
              />{" "}
              Metallic
            </label>
            <label>
              <input
                type="checkbox"
                checked={animate}
                onChange={(event) => setAnimate(event.target.checked)}
              />{" "}
              Robot animation
            </label>
            <button
              type="button"
              disabled={!state.ready || state.painting}
              onClick={() =>
                scene.current?.paint(
                  shade,
                  "Preview colour",
                  metallic ? "metallic" : "solid",
                  animate,
                )
              }
            >
              Paint preview
            </button>
            <button
              type="button"
              disabled={!state.ready}
              onClick={() => scene.current?.preview("#d6dcdf", "Unpainted shell", "unpainted")}
            >
              <RotateCcw size={16} /> Unpainted
            </button>
          </div>
          <p role="status" className="asset-review-feedback">
            {state.status}
            {state.error && (
              <button type="button" onClick={() => setAttempt((value) => value + 1)}>
                Retry
              </button>
            )}
          </p>
          <p className="asset-review-footnote">
            Prepared models are exterior visualizations, with no verified inner structure. Save
            inspection profiles in Model Detail. This review page does not change Standard, saved
            appearances or point locations.
          </p>
        </section>
      </div>
    </main>
  );
}
