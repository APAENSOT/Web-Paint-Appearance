import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Box, RotateCcw } from "lucide-react";
import { api, colorAppearancesOptions, meOptions, modelPointsOptions } from "@/api/queries";
import { mayEditColorAppearance } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { RANGER_MODEL } from "./catalogue";
import { PREPARED_BODIES, type BodyAsset } from "./body-assets";
import type { StudioScene, StudioState } from "./scene";
import { ColorEditor } from "./ColorEditor";
import { PointEditor } from "./PointEditor";
import { BODY_ZONES, type BodyZoneId } from "./body-zones";
import { ViewCube } from "./ViewCube";
import type { StudioMode } from "./ModelStudioNav";
import { NEUTRAL_BODY } from "./color-values";
import { RANGER_ASSET_VERSION } from "./point-placement";
import { finishForFamily, type PaintFinish } from "./paint-finish";
import "./model-studio.css";
import "./model-studio-polish.css";

const INITIAL: StudioState = {
  status: "Loading body…",
  ready: false,
  painting: false,
  error: false,
};

export function ModelStudio({
  code,
  mode,
  onModeLockChange,
  registerLeaveGuard,
}: {
  code: string;
  mode: StudioMode;
  onModeLockChange: (locked: boolean) => void;
  registerLeaveGuard?: (guard: (() => boolean) | null) => void;
}) {
  const plant = code.toUpperCase();
  const models = useQuery(modelPointsOptions(plant));
  const appearances = useQuery(colorAppearancesOptions(plant));
  const identity = useQuery(meOptions);
  const [editing, setEditing] = useState(false);
  const [selectedModel, setSelectedModel] = useState(RANGER_MODEL);
  const options = models.data?.models ?? [];
  const model = options.find((item) => item.model_code === selectedModel) ?? options[0];
  if (models.isPending || appearances.isPending || identity.isPending)
    return (
      <section className="panel p-6">
        <LoadingState>Loading Model Detail from Standard…</LoadingState>
      </section>
    );
  if (models.isError || appearances.isError || identity.isError)
    return (
      <section className="panel p-6">
        <ApiErrorState
          error={
            models.error ??
            appearances.error ??
            identity.error ??
            new Error("Could not load Model Detail.")
          }
          retry={() => {
            void models.refetch();
            void appearances.refetch();
            void identity.refetch();
          }}
        />
      </section>
    );
  const colors = appearances.data.items;
  return (
    <section className="model-studio panel" aria-label={`${plant} Model Detail`}>
      <header className="model-studio-header">
        <div>
          <h2>Model Detail</h2>
          <p>
            {mode === "colours"
              ? "Colour workshop · Configure the model’s finish."
              : "Inspection studio · Select a point, click to place, drag to adjust."}
          </p>
        </div>
        <label className="studio-model-select">
          Model at {plant}
          <select
            value={model?.model_code ?? ""}
            onChange={(e) => setSelectedModel(e.target.value)}
            disabled={!model || editing}
          >
            {!model && <option value="">No models offered</option>}
            {options.map((item) => (
              <option value={item.model_code} key={item.model_code}>
                {item.display_name ? `${item.display_name} · ${item.model_code}` : item.model_code}
              </option>
            ))}
          </select>
        </label>
      </header>
      {model && (model.model_code === RANGER_MODEL || PREPARED_BODIES[model.model_code]) ? (
        <RangerStudio
          asset={PREPARED_BODIES[model.model_code]}
          model={model.model_code}
          mode={mode}
          onModeLockChange={onModeLockChange}
          registerLeaveGuard={registerLeaveGuard}
          key={`${plant}:${model.model_code}`}
          colors={colors}
          appearances={appearances.data}
          plant={plant}
          canSave={mayEditColorAppearance(identity.data.principal)}
          onEditingChange={setEditing}
        />
      ) : (
        <div className="studio-unavailable">
          <Box size={40} aria-hidden="true" />
          <h3>
            {model
              ? `Body model needed for ${model.model_code}`
              : "No models offered at this plant"}
          </h3>
          <p>
            {model
              ? "This model is listed in Standard. Add its matching 3D body asset before painting or placing inspection points."
              : "Attach a model in Standard to start its studio."}
          </p>
          {options.some((item) => item.model_code === RANGER_MODEL) && (
            <button type="button" onClick={() => setSelectedModel(RANGER_MODEL)}>
              Open Ranger workshop
            </button>
          )}
        </div>
      )}
      <footer className="model-studio-footer">
        <div>
          <strong>Inspection profiles</strong>
          <p>
            Save each inspection point to this plant’s model profile. Wave Scan and Film Thickness
            have separate layouts, shared across the model’s colours and months.
          </p>
          {/* CC BY 4.0 requires this credit and a note of changes wherever the model is shown. */}
          <p data-testid="model-credit">
            Ranger-based bodies are modified from{" "}
            <a
              href="https://sketchfab.com/3d-models/ford-ranger-next-gen-2023-sport-e93ac097ee9a46a4a9decca9aceed03c"
              target="_blank"
              rel="noreferrer"
            >
              Ford Ranger Next-Gen 2023 Sport
            </a>{" "}
            by Asadawut.Kaewma,{" "}
            <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">
              CC BY 4.0
            </a>
            ; exterior panels extracted and reshaped for this app.
          </p>
        </div>
      </footer>
    </section>
  );
}

function RangerStudio({
  asset,
  model,
  colors,
  appearances,
  plant,
  canSave,
  onEditingChange,
  mode,
  onModeLockChange,
  registerLeaveGuard,
}: {
  asset?: BodyAsset;
  model: string;
  colors: components["schemas"]["ColorAppearanceItem"][];
  appearances: components["schemas"]["ColorAppearancesOut"];
  plant: string;
  canSave: boolean;
  onEditingChange: (editing: boolean) => void;
  mode: StudioMode;
  onModeLockChange: (locked: boolean) => void;
  registerLeaveGuard?: (guard: (() => boolean) | null) => void;
}) {
  const queryClient = useQueryClient();
  const stage = useRef<HTMLDivElement>(null);
  const controller = useRef<StudioScene | null>(null);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [pointDirty, setPointDirty] = useState(false);
  const [focusedZone, setFocusedZone] = useState<BodyZoneId | null>(null);
  const [appliedPreview, setAppliedPreview] = useState<{ name: string; hex: string } | null>(null);
  const [state, setState] = useState(INITIAL);
  const [attempt, setAttempt] = useState(0);
  const [selectedColor, setSelectedColor] = useState<string | null>(null);
  const [motion, setMotion] = useState(
    () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const current = colors.find((c) => c.color_name === selectedColor);
  const profileByName = new Map(appearances.items.map((item) => [item.color_name, item]));
  const savedShade = (name: string | null) =>
    (name && profileByName.get(name)?.appearance?.hex) || null;
  const paintFinish = (name: string | null): PaintFinish =>
    name ? finishForFamily(profileByName.get(name)?.family_name ?? null) : "unpainted";
  const paintShade = (name: string | null) =>
    name && appliedPreview?.name === name ? appliedPreview.hex : savedShade(name);
  const save = useMutation({
    mutationFn: ({
      name,
      hex,
      expected_revision,
    }: {
      name: string;
      hex: string;
      expected_revision: number | null;
    }) => api().saveColorAppearance(plant, name, { hex, expected_revision }),
    onSuccess: (saved) => {
      queryClient.setQueryData<components["schemas"]["ColorAppearancesOut"]>(
        colorAppearancesOptions(plant).queryKey,
        (previous) =>
          previous && {
            ...previous,
            items: previous.items.map((item) =>
              item.color_name === saved.color_name
                ? {
                    ...item,
                    appearance: {
                      hex: saved.hex,
                      revision: saved.revision,
                      saved_at: saved.saved_at,
                      saved_by: saved.saved_by,
                      inherited_from: null,
                    },
                  }
                : item,
            ),
          },
      );
      void queryClient.invalidateQueries({ queryKey: colorAppearancesOptions(plant).queryKey });
    },
  });
  useEffect(() => {
    let cancelled = false;
    setState(INITIAL);
    setSelectedColor(null);
    void import("./scene")
      .then(({ createStudio }) => {
        if (cancelled || !stage.current) return;
        try {
          controller.current = createStudio(stage.current, setState, asset);
        } catch {
          setState({
            status: "3D could not start. Check browser graphics support and retry.",
            ready: false,
            painting: false,
            error: true,
          });
        }
      })
      .catch(() => {
        if (!cancelled)
          setState({
            status: "Could not load the workshop. Check your connection and retry.",
            ready: false,
            painting: false,
            error: true,
          });
      });
    return () => {
      cancelled = true;
      controller.current?.dispose();
      controller.current = null;
    };
  }, [attempt, asset]);
  useEffect(() => {
    controller.current?.motion(motion);
  }, [motion, state.ready]);
  useEffect(() => {
    onEditingChange(editingName !== null || pointDirty);
  }, [editingName, pointDirty, onEditingChange]);
  useEffect(() => {
    if (!state.ready) return;
    controller.current?.finish();
    if (mode === "points") {
      if (asset) controller.current?.view("body");
      else controller.current?.focusZone(focusedZone);
    } else controller.current?.view("workshop");
  }, [focusedZone, mode, state.ready, asset]);
  useEffect(() => {
    onModeLockChange(editingName !== null);
    return () => onModeLockChange(false);
  }, [editingName, onModeLockChange]);
  const chooseColor = (name: string | null, keyboard = false) => {
    setAppliedPreview(null);
    setSelectedColor(name);
    controller.current?.paint(
      savedShade(name) || NEUTRAL_BODY,
      name
        ? `${name} · ${savedShade(name) ? "Saved appearance" : "Not configured"}`
        : "Unpainted metal",
      paintFinish(name),
      !keyboard && !!savedShade(name),
    );
  };
  const endEditing = () => {
    setEditingName(null);
  };
  const restorePreview = () => {
    controller.current?.preview(
      paintShade(selectedColor) || NEUTRAL_BODY,
      selectedColor
        ? `${selectedColor} · ${appliedPreview?.name === selectedColor ? "Unsaved preview" : savedShade(selectedColor) ? "Saved appearance" : "Not configured"}`
        : "Unpainted metal",
      paintFinish(selectedColor),
    );
  };
  const ready = state.ready && !state.error;
  const unavailable = !ready || state.painting || editingName !== null;
  return (
    <div className="studio-workspace">
      <div className="studio-visual">
        <div className="studio-stage" ref={stage} data-testid="model-studio-stage">
          <div
            className={`studio-status${state.error ? " is-error" : ""}`}
            role={state.error ? "alert" : "status"}
            aria-live="polite"
          >
            {state.status}
            {state.error && (
              <button type="button" onClick={() => setAttempt((n) => n + 1)}>
                Retry model
              </button>
            )}
          </div>
          {!state.ready && !state.error && (
            <div className="studio-loading">
              <span aria-hidden="true" />
              <p>Preparing your workshop</p>
            </div>
          )}
          <span className="studio-orbit-hint">
            {mode === "points" && !asset
              ? focusedZone
                ? `${BODY_ZONES.find((item) => item.id === focusedZone)?.label} only · Drag to orbit · Scroll to zoom`
                : "Select a point, then click the body · Drag empty space to orbit"
              : "Drag to orbit · Scroll or pinch to zoom"}
          </span>
          <ViewCube
            scene={controller.current}
            ready={ready}
            workshop={mode === "colours"}
            onView={(next) => {
              controller.current?.orient(next);
            }}
            onFit={() =>
              mode === "points" && !asset
                ? controller.current?.focusZone(focusedZone)
                : controller.current?.view("workshop")
            }
          />
          {pointDirty && <span className="studio-draft-badge">Point draft · Unsaved</span>}
        </div>
        <div className="studio-viewbar">
          {mode === "points" && focusedZone && (
            <div className="studio-panel-toolbar">
              <button type="button" onClick={() => setFocusedZone(null)}>
                Whole body
              </button>
              <button type="button" onClick={() => controller.current?.focusZone(focusedZone)}>
                Reset panel view
              </button>
            </div>
          )}
          {mode === "points" && !asset && (
            <p className="studio-interaction-guide">
              Drag a dot to adjust its location. Drag the surface to rotate. Scroll to zoom.
            </p>
          )}
        </div>
        <div className="studio-motionbar" hidden={mode === "points"}>
          <label>
            <input
              type="checkbox"
              disabled={editingName !== null}
              checked={motion}
              onChange={(e) => setMotion(e.target.checked)}
            />
            Painting animation
          </label>
          {state.painting ? (
            <button type="button" onClick={() => controller.current?.finish()}>
              Finish paint now
            </button>
          ) : (
            <span>Four fixed robots · Dürr-inspired arms</span>
          )}
        </div>
      </div>
      <aside className="studio-colors" aria-label="Standard colours" hidden={mode !== "colours"}>
        <h3>Choose a colour</h3>
        <p>From {plant} Standard</p>
        <button
          type="button"
          className="studio-unpainted"
          aria-pressed={selectedColor === null}
          disabled={unavailable}
          onClick={(e) => chooseColor(null, e.detail === 0)}
        >
          <RotateCcw size={16} aria-hidden="true" /> Unpainted metal
        </button>
        {colors.length ? (
          <div className="studio-swatches">
            {colors.map((color) => {
              const profile = profileByName.get(color.color_name)?.appearance ?? null;
              const shade = profile?.hex ?? null;
              const selected = color.color_name === selectedColor;
              return (
                <div
                  className={`studio-color-row${selected ? " is-selected" : ""}`}
                  key={color.color_name}
                >
                  <ColorEditor
                    name={color.color_name}
                    shade={shade}
                    expectedRevision={profile?.inherited_from ? null : (profile?.revision ?? null)}
                    inheritedFrom={profile?.inherited_from ?? null}
                    canSave={canSave}
                    disabled={!ready || (editingName !== null && editingName !== color.color_name)}
                    onBegin={() => {
                      controller.current?.finish();
                      setEditingName(color.color_name);
                      onEditingChange(true);
                    }}
                    onPreview={(hex) =>
                      controller.current?.preview(
                        hex,
                        `${color.color_name} · Unsaved preview`,
                        finishForFamily(color.family_name),
                      )
                    }
                    onCancel={() => {
                      restorePreview();
                      endEditing();
                    }}
                    onApply={(hex) => {
                      restorePreview();
                      setAppliedPreview({ name: color.color_name, hex });
                      setSelectedColor(color.color_name);
                      endEditing();
                      controller.current?.paint(
                        hex,
                        `${color.color_name} · Unsaved preview`,
                        finishForFamily(color.family_name),
                      );
                    }}
                    onSave={async (hex, expected_revision) => {
                      const saved = await save.mutateAsync({
                        name: color.color_name,
                        hex,
                        expected_revision,
                      });
                      setAppliedPreview(null);
                      setSelectedColor(color.color_name);
                      endEditing();
                      controller.current?.paint(
                        saved.hex,
                        `${color.color_name} · Saved appearance`,
                        finishForFamily(color.family_name),
                      );
                    }}
                    onReload={async () => {
                      const fresh = await api().colorAppearances(plant);
                      queryClient.setQueryData(colorAppearancesOptions(plant).queryKey, fresh);
                      const latest = fresh.items.find(
                        (item) => item.color_name === color.color_name,
                      );
                      if (!latest)
                        throw new Error("This colour is no longer offered at this plant.");
                      return {
                        hex: latest.appearance?.hex ?? null,
                        revision: latest.appearance?.inherited_from
                          ? null
                          : (latest.appearance?.revision ?? null),
                      };
                    }}
                  />
                  <button
                    type="button"
                    className="studio-color-select"
                    aria-pressed={selected}
                    disabled={unavailable}
                    onClick={(e) => chooseColor(color.color_name, e.detail === 0)}
                  >
                    <span>{color.color_name}</span>
                    <small>{shade ? "Saved appearance" : "Set colour"}</small>
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <p>No colours offered at this plant. Manage availability in Standard.</p>
        )}
        <div className="studio-color-info">
          <strong>{current?.color_name ?? "Unpainted metal"}</strong>
          {current && (
            <span>
              {current.family_name ?? "No colour family assigned"} ·{" "}
              {finishForFamily(current.family_name) === "metallic"
                ? "Metallic flake preview"
                : "Plain finish preview"}
            </span>
          )}
          <p>
            {current && !savedShade(current.color_name)
              ? "No appearance configured. Select the colour circle to set a shade."
              : "Screen colours are appearance settings, not calibrated paint matches."}
          </p>
        </div>
      </aside>
      <PointEditor
        registerLeaveGuard={registerLeaveGuard}
        model={model}
        assetVersion={asset?.assetVersion ?? RANGER_ASSET_VERSION}
        canSave={canSave}
        panels={!asset}
        zone={focusedZone}
        onZone={setFocusedZone}
        plant={plant}
        active={mode === "points"}
        scene={controller.current}
        stage={stage.current}
        ready={ready}
        onDirtyChange={setPointDirty}
      />
    </div>
  );
}
