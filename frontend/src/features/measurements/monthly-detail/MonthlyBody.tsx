import { useEffect, useRef, useState } from "react";
import { RotateCcw } from "lucide-react";
import type { components } from "@/api/types";
import { PREPARED_BODIES } from "../model-studio/body-assets";
import { RANGER_MODEL } from "../model-studio/catalogue";
import { RANGER_ASSET_VERSION } from "../model-studio/point-placement";
import {
  profileLocations,
  profilePoints,
  storageKey,
  type PointProfile,
} from "../model-studio/point-storage";
import { NEUTRAL_BODY } from "../model-studio/color-values";
import { ViewCube } from "../model-studio/ViewCube";
import { finishForFamily } from "../model-studio/paint-finish";
import type { StudioScene, StudioState } from "../model-studio/scene";
import "../model-studio/model-studio.css";
const RANGER_PREVIEW = {
  url: `/models/ranger/ranger-body.glb?v=${RANGER_ASSET_VERSION}`,
  label: "Ranger",
  assetVersion: RANGER_ASSET_VERSION,
};
const NO_SUMMARIES: components["schemas"]["MonthlyPointStatus"][] = [];

export function MonthlyBody({
  model,
  hex,
  family,
  profile,
  selected,
  onSelect,
  summaries = NO_SUMMARIES,
}: {
  model: string;
  hex: string | null;
  family: string | null;
  profile: PointProfile;
  selected: string | null;
  onSelect: (key: string) => void;
  summaries?: components["schemas"]["MonthlyPointStatus"][];
}) {
  const stage = useRef<HTMLDivElement>(null),
    scene = useRef<StudioScene | null>(null);
  const [state, setState] = useState<StudioState>({
    ready: false,
    error: false,
    painting: false,
    status: "Loading inspection body…",
  });
  const [attempt, setAttempt] = useState(0);
  const asset = PREPARED_BODIES[model] ?? RANGER_PREVIEW;
  const supported = model === RANGER_MODEL || Boolean(PREPARED_BODIES[model]);
  const version = asset?.assetVersion ?? RANGER_ASSET_VERSION;
  useEffect(() => {
    if (!supported) return;
    let cancelled = false;
    setState({ ready: false, error: false, painting: false, status: "Loading inspection body…" });
    void import("../model-studio/scene").then(({ createStudio }) => {
      if (cancelled || !stage.current) return;
      try {
        scene.current = createStudio(stage.current, setState, asset);
        scene.current.view("body");
      } catch {
        setState({
          ready: false,
          error: true,
          painting: false,
          status: "Could not open the 3D body. Use the point list or retry.",
        });
      }
    });
    return () => {
      cancelled = true;
      scene.current?.dispose();
      scene.current = null;
    };
  }, [asset, supported, attempt]);
  useEffect(() => {
    if (!state.ready) return;
    scene.current?.preview(
      hex ?? NEUTRAL_BODY,
      hex ? "Saved colour appearance" : "Neutral · colour appearance not saved",
      hex ? finishForFamily(family) : "unpainted",
    );
    scene.current?.view("body");
  }, [state.ready, hex, family]);
  useEffect(() => {
    if (!state.ready) return;
    const visuals = Object.fromEntries(
      summaries.map((item) => [
        storageKey(profile.domain, item.point_key),
        { status: item.status, mean: item.mean, unit: profile.domain === "film" ? "µm" : "index" },
      ]),
    );
    scene.current?.points({
      readOnly: true,
      points: profilePoints(profile),
      draft: profileLocations(profile, version),
      selected: selected ? storageKey(profile.domain, selected) : null,
      armed: false,
      zone: null,
      visuals,
      onZone: () => {},
      onSelect: (key) => {
        const point = profilePoints(profile).find((p) => p.key === key);
        if (point?.pointKey) onSelect(point.pointKey);
      },
      onPlace: () => {},
      onMove: () => {},
      onDragCancel: () => {},
    });
  }, [profile, selected, version, state.ready, onSelect, summaries]);
  if (!supported)
    return (
      <div className="monthly-body-unavailable">
        <h3>3D body not registered</h3>
        <p>You can inspect every Standard point using the list below.</p>
      </div>
    );
  return (
    <div className="monthly-body model-studio studio-stage">
      <div ref={stage} className="studio-canvas" />
      <ViewCube
        scene={scene.current}
        ready={state.ready}
        workshop={false}
        onView={(v) => scene.current?.orient(v)}
        onFit={() => scene.current?.view("body")}
      />
      {!state.ready && (
        <div className="monthly-body-message" role="status">
          <p>{state.status}</p>
          {state.error && (
            <button onClick={() => setAttempt((a) => a + 1)}>
              <RotateCcw size={15} /> Retry body
            </button>
          )}
        </div>
      )}
      <div className="monthly-body-caption">
        Drag to orbit · Scroll to zoom · Click a saved point
      </div>
    </div>
  );
}
