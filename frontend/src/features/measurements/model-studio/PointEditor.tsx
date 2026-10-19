import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useBlocker } from "@tanstack/react-router";
import { Crosshair, Undo2 } from "lucide-react";
import { api, pointProfileOptions } from "@/api/queries";
import { ApiError } from "@/api/client";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { type PointDomain, type SurfaceLocation } from "./point-placement";
import type { StudioScene } from "./scene";
import { BODY_ZONES, bodyZone, type BodyZoneId } from "./body-zones";
import {
  mergeLocations,
  profileLocations,
  profilePoints,
  toAnchor,
  type PointChanges,
  type PointProfile,
} from "./point-storage";
import type { components } from "@/api/types";
import { completeLayout, pendingPointWrites, persistPoints } from "./save-all";

type Write = {
  domain: PointDomain;
  key: string;
  pointKey: string;
  revision: number | null;
  location: SurfaceLocation | null;
};

export function PointEditor({
  plant,
  model,
  assetVersion,
  canSave,
  panels = true,
  registerLeaveGuard,
  active,
  scene,
  stage,
  ready,
  onDirtyChange,
  zone,
  onZone,
}: {
  plant: string;
  model: string;
  assetVersion: string;
  canSave: boolean;
  panels?: boolean;
  registerLeaveGuard?: (guard: (() => boolean) | null) => void;
  active: boolean;
  scene: StudioScene | null;
  stage: HTMLDivElement | null;
  ready: boolean;
  onDirtyChange: (dirty: boolean) => void;
  zone: BodyZoneId | null;
  onZone: (zone: BodyZoneId | null) => void;
}) {
  const [domain, setDomain] = useState<PointDomain>("wavescan");
  const [selected, setSelected] = useState<string | null>(null);
  const [armed, setArmed] = useState(false);
  const [search, setSearch] = useState("");
  const [changes, setChanges] = useState<PointChanges>({});
  const [history, setHistory] = useState<PointChanges[]>([]);
  const [conflict, setConflict] = useState<string | null>(null);
  const [retryWrite, setRetryWrite] = useState<Write | null>(null);
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("Choose a Standard point to begin.");
  const [discard, setDiscard] = useState(false);
  const [savingAll, setSavingAll] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);
  const [listScope, setListScope] = useState<"available" | "panel" | "all">("available");
  const placementAction = useRef<HTMLButtonElement>(null);
  const stay = useRef<HTMLButtonElement>(null);
  const ws = useQuery({
    ...pointProfileOptions(plant, model, "wavescan"),
    enabled: active && domain === "wavescan",
  });
  const film = useQuery({
    ...pointProfileOptions(plant, model, "film"),
    enabled: active && domain === "film",
  });
  const points = useMemo(
    () => (domain === "wavescan" ? profilePoints(ws.data) : profilePoints(film.data)),
    [domain, ws.data, film.data],
  );
  const query = domain === "wavescan" ? ws : film;
  const saved = useMemo(
    () => ({
      ...profileLocations(ws.data, assetVersion),
      ...profileLocations(film.data, assetVersion),
    }),
    [ws.data, film.data, assetVersion],
  );
  const draft = useMemo(() => mergeLocations(saved, changes), [saved, changes]);
  const current = points.find((p) => p.key === selected);
  const savedPoint = query.data?.points.find((p) => p.point_key === current?.pointKey);
  const dirty = Object.keys(changes).length > 0;
  const write = useMutation({
    mutationFn: (request: Write) =>
      request.location
        ? api().savePointAnchor(plant, model, request.domain, {
            point_key: request.pointKey,
            expected_revision: request.revision,
            anchor: toAnchor(request.location),
          })
        : api().removePointAnchor(plant, model, request.domain, {
            point_key: request.pointKey,
            expected_revision: request.revision!,
          }),
    onSuccess: (result, request) => {
      queryClient.setQueryData<PointProfile>(
        pointProfileOptions(plant, model, request.domain).queryKey,
        (previous) =>
          previous
            ? {
                ...previous,
                state: "configured",
                last_saved_at: result.saved_at,
                profile_revision: previous.profile_revision + (result.replayed ? 0 : 1),
                points: previous.points.map((p) => (p.point_key === result.point_key ? result : p)),
              }
            : previous,
      );
      setChanges((previous) => {
        const next = { ...previous };
        delete next[request.key];
        return next;
      });
      setHistory([]);
      setConflict(null);
      setRetryWrite(null);
      setMessage(
        `${result.label} ${result.anchor ? "saved" : "location removed"} · revision ${result.revision} · ${result.saved_by ?? "Saved in system"}.`,
      );
      void queryClient.invalidateQueries({
        queryKey: pointProfileOptions(plant, model, request.domain).queryKey,
      });
    },
    onError: async (error, request) => {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(request.key);
        setRetryWrite(null);
        await queryClient.invalidateQueries({
          queryKey: pointProfileOptions(plant, model, request.domain).queryKey,
        });
        setMessage(
          "This point changed in the system. Your draft is kept. Review the latest saved point before reapplying.",
        );
      } else {
        setRetryWrite(request);
        setMessage(`Save failed. Your draft is kept. ${error.message}`);
      }
    },
  });
  const placed = points.filter((p) => draft[p.key]).length;
  const busy = write.isPending || savingAll;
  const usable = active && ready && !query.isError && !query.isPending;
  const editable = usable && !busy && canSave && query.data?.asset?.asset_version === assetVersion;
  const allPlaced = completeLayout(query.data, draft);
  const pending = query.data ? pendingPointWrites(query.data, changes) : [];
  const saveAll = async () => {
    if (!editable || !allPlaced || !pending.length || conflict) return;
    const requests = pending.map((r) => (retryWrite?.key === r.key ? retryWrite : r));
    setSavingAll(true);
    setDiscard(false);
    setArmed(false);
    setBulkProgress({ done: 0, total: requests.length });
    try {
      const result = await persistPoints(
        requests,
        (r) => write.mutateAsync(r),
        (done, total) => setBulkProgress({ done, total }),
      );
      if (result.failed) {
        setSelected(result.failed.key);
        setMessage(
          `Save all paused: ${result.completed} of ${requests.length} changed points saved. The failed point and remaining drafts are kept. Review this point and retry.`,
        );
      } else
        setMessage(
          `All ${requests.length} changed ${domain === "wavescan" ? "Wave Scan" : "Film Thickness"} points saved in the system.`,
        );
    } finally {
      setSavingAll(false);
      setBulkProgress(null);
    }
  };
  useEffect(() => {
    registerLeaveGuard?.(() => {
      if (busy) {
        setMessage("Wait for this point to finish saving before leaving Model Detail.");
        return false;
      }
      if (dirty) {
        setMessage("Save or discard your point changes before leaving Model Detail.");
        return false;
      }
      return true;
    });
    return () => registerLeaveGuard?.(null);
  }, [registerLeaveGuard, dirty, busy]);
  const edit = useCallback(
    (key: string, location: SurfaceLocation | null) => {
      setHistory((previous) => [...previous, changes]);
      setChanges((previous) => {
        const next = { ...previous };
        if (JSON.stringify(location) === JSON.stringify(saved[key] ?? null)) delete next[key];
        else next[key] = location;
        return next;
      });
      setRetryWrite(null);
    },
    [changes, saved],
  );
  const zoneLabel = BODY_ZONES.find((item) => item.id === zone)?.label;
  const onPanel = (key: string) => {
    const location = draft[key];
    return !!location && (location.zone ?? bodyZone(location.mesh, location.position)) === zone;
  };
  const listed = points
    .filter(
      (p) =>
        !zone ||
        listScope === "all" ||
        (listScope === "panel" ? onPanel(p.key) : !draft[p.key] || onPanel(p.key)),
    )
    .filter((p) => `${p.number} ${p.code}`.toLowerCase().includes(search.toLowerCase()));
  const chooseZone = useCallback(
    (next: BodyZoneId | null) => {
      setArmed(false);
      setSelected(null);
      onZone(next);
      setMessage(
        next
          ? "Panel isolated. Select the matching Standard point, then place it."
          : "Click a panel on the car, or choose one from the panel list.",
      );
    },
    [onZone],
  );
  const blocker = useBlocker({
    shouldBlockFn: () => dirty || busy,
    disabled: !dirty && !busy,
    enableBeforeUnload: dirty || busy,
    withResolver: true,
  });
  useEffect(() => {
    onDirtyChange(dirty || busy);
  }, [dirty, busy, onDirtyChange]);
  useEffect(() => {
    if (blocker.status === "blocked") stay.current?.focus();
  }, [blocker.status]);
  useEffect(() => {
    setArmed(false);
  }, [active, domain, ready, zone]);
  useEffect(() => {
    if (!active || !armed) return;
    const cancel = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setArmed(false);
      setMessage("Placement cancelled.");
      placementAction.current?.focus();
    };
    window.addEventListener("keydown", cancel);
    return () => window.removeEventListener("keydown", cancel);
  }, [active, armed]);
  const selectPoint = useCallback(
    (key: string) => {
      setSelected(key);
      setArmed(canSave);
      setMessage("Click the body to place this point, or drag its existing dot to adjust it.");
    },
    [canSave],
  );
  const place = useCallback(
    (location: SurfaceLocation | null) => {
      if (!current || !editable) return;
      if (!location) {
        setMessage(
          `No ${zoneLabel ?? "body"} surface here. Click a visible surface and try again.`,
        );
        return;
      }
      edit(current.key, location);
      setArmed(false);
      setMessage(
        `${current.number} · ${current.code} placed. Drag its dot to adjust. Unsaved draft.`,
      );
    },
    [current, editable, edit, zoneLabel],
  );
  const movePoint = useCallback(
    (key: string, location: SurfaceLocation) => {
      if (!editable || !points.some((point) => point.key === key)) return;
      edit(key, location);
      setSelected(key);
      setArmed(false);
      setMessage("Point moved. Unsaved draft. Undo restores the previous position.");
    },
    [editable, points, edit],
  );
  const cancelDrag = useCallback(() => {
    setArmed(false);
    setMessage("Move cancelled. The previous position was restored.");
  }, []);
  useEffect(() => {
    scene?.points(
      usable
        ? {
            readOnly: !editable,
            points,
            draft,
            selected: current?.key ?? null,
            armed: editable && armed && !!current,
            zone,
            onZone: chooseZone,
            onSelect: selectPoint,
            onPlace: place,
            onMove: movePoint,
            onDragCancel: cancelDrag,
          }
        : null,
    );
  }, [
    scene,
    usable,
    points,
    draft,
    current,
    armed,
    editable,
    selectPoint,
    place,
    zone,
    chooseZone,
    movePoint,
    cancelDrag,
  ]);
  useEffect(() => () => scene?.points(null), [scene]);
  const remove = () => {
    if (!current || !draft[current.key]) return;
    edit(current.key, null);
    setArmed(false);
    setMessage(`${current.code} location removed. The Standard point is unchanged.`);
  };
  return (
    <>
      <aside className="studio-points" hidden={!active} aria-label="Inspection point placement">
        <div className="studio-point-heading">
          <Crosshair size={20} aria-hidden="true" />
          <h3>Place inspection points</h3>
        </div>
        {panels && (
          <label className="studio-zone-select">
            Body panel
            <select
              value={zone ?? ""}
              onChange={(event) =>
                chooseZone(event.target.value ? (event.target.value as BodyZoneId) : null)
              }
              disabled={!ready}
            >
              <option value="">Whole body</option>
              {BODY_ZONES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <p className="studio-zone-help">
          {zone
            ? `${zoneLabel} is isolated. Drag empty space to rotate; points stay on this panel.`
            : panels
              ? "Select a point and click the body to place it. For a closer view, choose a panel above."
              : "Select a point and click the body to place it. Use the camera cube and zoom to inspect a surface."}
        </p>
        <div className="studio-domain-switch" role="group" aria-label="Point measurement type">
          {(
            [
              ["wavescan", "Wave Scan"],
              ["film", "Film Thickness"],
            ] as const
          ).map(([id, label]) => (
            <button
              type="button"
              key={id}
              aria-pressed={domain === id}
              disabled={busy}
              onClick={() => {
                setDomain(id);
                setSelected(null);
                setSearch("");
                setMessage("Choose a Standard point to begin.");
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="studio-draft-note">
          <strong>
            {dirty
              ? "Unsaved changes."
              : query.data?.state === "unconfigured"
                ? "No saved profile yet."
                : "System profile."}
          </strong>{" "}
          {dirty
            ? "Save each changed point to keep its location."
            : "Saved locations are reused across colours and months."}
        </p>
        {!canSave && <p>Viewing saved points. An Engineer or Admin can change this profile.</p>}
        {query.data && !query.data.asset && (
          <p role="alert">
            Point saving is unavailable for this model’s body registration. Reload Studio after its
            registration is available.
          </p>
        )}
        {!!query.data?.unavailable.length && (
          <div role="status">
            <p>
              {query.data.unavailable.length} saved locations belong to points that are no longer
              live. They are retained in the system.
            </p>
            <ul>
              {query.data.unavailable.map((point) => (
                <li key={point.point_key}>
                  {point.label} ·{" "}
                  {point.unavailable_reason === "retired" ? "Retired" : "Not on Point Check list"}
                </li>
              ))}
            </ul>
          </div>
        )}
        {query.data?.asset && query.data.asset.asset_version !== assetVersion && (
          <p role="alert">
            This body version differs from the registered surface. Reload Studio before placing
            points.
          </p>
        )}
        {query.isPending ? (
          <LoadingState>Loading Standard points…</LoadingState>
        ) : query.isError ? (
          <ApiErrorState error={query.error} retry={() => void query.refetch()} />
        ) : (
          <>
            <div className="studio-point-count">
              <strong>
                {placed} / {points.length} placed
              </strong>
              <span>From Standard → Point Check</span>
              {zone && (
                <span>
                  {points.filter((p) => onPanel(p.key)).length} on {zoneLabel}
                </span>
              )}
            </div>
            {allPlaced && canSave && (
              <div className="studio-save-all">
                <button
                  className="studio-point-save"
                  type="button"
                  disabled={!editable || !pending.length || !!conflict}
                  onClick={() => void saveAll()}
                >
                  {savingAll
                    ? `Saving ${bulkProgress?.done ?? 0} / ${bulkProgress?.total ?? pending.length}…`
                    : "Save all points"}
                </button>
                <p className="studio-point-footnote">
                  {pending.length
                    ? `${pending.length} changed points in this ${domain === "wavescan" ? "Wave Scan" : "Film Thickness"} layout.`
                    : "All point locations are saved."}
                </p>
              </div>
            )}
            {zone && (
              <label className="studio-zone-select">
                Point list
                <select
                  value={listScope}
                  onChange={(event) => setListScope(event.target.value as typeof listScope)}
                >
                  <option value="available">This panel + unplaced</option>
                  <option value="panel">Placed on this panel</option>
                  <option value="all">All Standard points</option>
                </select>
              </label>
            )}
            <label className="studio-point-search">
              Find a point
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Point name or number"
              />
            </label>
            <div className="studio-point-list" role="group" aria-label="Standard inspection points">
              {listed.map((point) => (
                <button
                  type="button"
                  key={point.key}
                  aria-pressed={selected === point.key}
                  disabled={busy}
                  onClick={() => {
                    selectPoint(point.key);
                    if (window.matchMedia("(max-width: 1050px)").matches) {
                      stage?.scrollIntoView({ block: "center", behavior: "instant" });
                    }
                  }}
                >
                  <span className="studio-point-number">{point.number}</span>
                  <span>
                    <strong>{point.code}</strong>
                    <small>
                      {draft[point.key]
                        ? `Placed · ${BODY_ZONES.find((item) => item.id === (draft[point.key].zone ?? bodyZone(draft[point.key].mesh, draft[point.key].position)))?.label ?? "Body"}`
                        : "Not placed"}
                      {Object.hasOwn(changes, point.key)
                        ? " · Unsaved"
                        : query.data?.points.find((p) => p.point_key === point.pointKey)?.anchor
                          ? " · Saved"
                          : ""}
                      {!point.counted && " · Not counted"}
                    </small>
                  </span>
                </button>
              ))}
              {!points.length && (
                <p>No live points for this model. Configure them in Standard → Point Check.</p>
              )}
              {!!points.length && !listed.length && (
                <p>
                  {search
                    ? `No points match “${search}” in this list.`
                    : "No points in this list yet. Choose This panel + unplaced to assign a Standard point."}
                </p>
              )}
            </div>
            {current && (
              <div className="studio-point-actions">
                <h4>
                  {current.number} · {current.code}
                </h4>
                <p>
                  {armed
                    ? `Click ${zoneLabel ?? "the body"} to place this point. Escape cancels.`
                    : "Drag the dot to adjust its position, or choose Place again."}
                </p>
                <div className="studio-point-buttons">
                  <button
                    type="button"
                    ref={placementAction}
                    disabled={!editable}
                    aria-pressed={armed}
                    onClick={() => {
                      setArmed(!armed);
                      if (!armed) stage?.scrollIntoView({ block: "center", behavior: "instant" });
                      setMessage(
                        armed ? "Placement cancelled." : `Click the body to place ${current.code}.`,
                      );
                    }}
                  >
                    {armed ? "Cancel placement" : "Place again"}
                  </button>
                  <button
                    type="button"
                    disabled={!editable || !draft[current.key]}
                    onClick={remove}
                  >
                    Remove location
                  </button>
                </div>
                <button
                  className="studio-point-save"
                  type="button"
                  disabled={
                    !editable || !Object.hasOwn(changes, current.key) || conflict === current.key
                  }
                  onClick={() => {
                    const request =
                      retryWrite?.key === current.key
                        ? retryWrite
                        : {
                            domain,
                            key: current.key,
                            pointKey: current.pointKey!,
                            revision: savedPoint?.revision ?? null,
                            location: changes[current.key],
                          };
                    write.mutate(request);
                  }}
                  aria-describedby="studio-point-save-help"
                >
                  {write.isPending
                    ? "Saving…"
                    : retryWrite?.key === current.key
                      ? "Retry save"
                      : changes[current.key] === null
                        ? "Save removal"
                        : "Save point"}
                </button>
                <p id="studio-point-save-help" className="studio-point-footnote">
                  {savedPoint?.saved_at
                    ? `Saved by ${savedPoint.saved_by ?? "System"} · ${new Date(savedPoint.saved_at).toLocaleString()} · revision ${savedPoint.revision}`
                    : "No saved location yet."}
                </p>
                {conflict === current.key && (
                  <div role="alert">
                    <p>Another saved revision exists. Your draft has been kept.</p>
                    <button
                      type="button"
                      onClick={async () => {
                        const refreshed = await query.refetch();
                        if (!refreshed.isError) {
                          setConflict(null);
                          setMessage("Latest revision loaded. Click Save to reapply your draft.");
                        }
                      }}
                    >
                      Keep my draft and reapply
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setChanges((previous) => {
                          const next = { ...previous };
                          delete next[current.key];
                          return next;
                        });
                        setConflict(null);
                        setHistory([]);
                      }}
                    >
                      Use saved location
                    </button>
                  </div>
                )}
              </div>
            )}
          </>
        )}
        <p className="studio-placement-message" role="status">
          {message}
        </p>
        <div className="studio-point-buttons">
          <button
            type="button"
            disabled={!history.length || busy}
            onClick={() => {
              setChanges(history[history.length - 1]);
              setHistory(history.slice(0, -1));
              setArmed(false);
              setMessage("Last placement change undone.");
            }}
          >
            <Undo2 size={16} aria-hidden="true" /> Undo
          </button>
          <button type="button" disabled={!dirty || busy} onClick={() => setDiscard(true)}>
            Discard draft
          </button>
        </div>
        {discard && (
          <div className="studio-point-discard">
            <p>Discard all unsaved Wave Scan and Film Thickness locations?</p>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (busy) return;
                setHistory([]);
                setChanges({});
                setRetryWrite(null);
                setConflict(null);
                setArmed(false);
                setDiscard(false);
                setMessage("Draft discarded.");
              }}
            >
              Discard locations
            </button>
            <button type="button" onClick={() => setDiscard(false)}>
              Keep editing
            </button>
          </div>
        )}
        <p className="studio-point-footnote">
          One default per model and measurement type at this plant, shared across its colours and
          months. Body variants have separate profiles.
        </p>
      </aside>
      {blocker.status === "blocked" &&
        createPortal(
          <div
            className="studio-navigation-guard"
            role="alertdialog"
            aria-modal="true"
            aria-label="Unsaved point locations"
          >
            <p>
              {busy
                ? "Point locations are saving. Wait for saving to finish before leaving."
                : "Point locations have not been saved. Leave and discard this draft?"}
            </p>
            <button type="button" ref={stay} onClick={() => blocker.reset()}>
              Keep editing
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (!busy) blocker.proceed();
              }}
            >
              Leave and discard
            </button>
          </div>,
          document.body,
        )}
    </>
  );
}
