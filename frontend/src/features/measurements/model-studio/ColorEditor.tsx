import { useEffect, useId, useRef, useState, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import { Pencil, X } from "lucide-react";
import * as Popover from "@radix-ui/react-popover";
import { useBlocker } from "@tanstack/react-router";
import { ApiError } from "@/api/client";
import {
  hexToRgb,
  hsvToRgb,
  NEUTRAL_BODY,
  parseChannel,
  parseHex,
  rgbToHex,
  rgbToHsv,
  wheelPosition,
  type HSV,
  type RGB,
} from "./color-values";

type Props = {
  name: string;
  shade: string | null;
  expectedRevision: number | null;
  inheritedFrom: string | null;
  canSave: boolean;
  disabled: boolean;
  onBegin: () => void;
  onPreview: (hex: string) => void;
  onCancel: () => void;
  onApply: (hex: string) => void;
  onSave: (hex: string, expectedRevision: number | null) => Promise<void>;
  onReload: () => Promise<{ hex: string | null; revision: number | null }>;
};

export function ColorEditor({
  name,
  shade,
  expectedRevision,
  inheritedFrom,
  canSave,
  disabled,
  onBegin,
  onPreview,
  onCancel,
  onApply,
  onSave,
  onReload,
}: Props) {
  const [open, setOpen] = useState(false);
  const [discard, setDiscard] = useState(false);
  const [hex, setHex] = useState(shade ?? NEUTRAL_BODY);
  const [hexInput, setHexInput] = useState(hex);
  const [channels, setChannels] = useState(hexToRgb(hex).map(String));
  const [hsv, setHsv] = useState(() => rgbToHsv(hexToRgb(hex)));
  const [touched, setTouched] = useState(false);
  const [loadedRevision, setLoadedRevision] = useState(expectedRevision);
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const stayButton = useRef<HTMLButtonElement>(null);
  const id = useId();
  const valid = /^#?[\da-f]{6}$/i.test(hexInput) && channels.every((c) => parseChannel(c) !== null);
  const dirty = touched && (hex !== (shade ?? NEUTRAL_BODY) || !valid || shade === null);
  const blocker = useBlocker({
    shouldBlockFn: () => open && dirty,
    disabled: !open || !dirty,
    enableBeforeUnload: open && dirty,
    withResolver: true,
  });
  useEffect(() => {
    if (blocker.status === "blocked") stayButton.current?.focus();
  }, [blocker.status]);

  function resetFields(next: string | null) {
    const initial = next ?? NEUTRAL_BODY;
    setHex(initial);
    setHexInput(initial);
    setChannels(hexToRgb(initial).map(String));
    setHsv(rgbToHsv(hexToRgb(initial)));
    setTouched(false);
    setDiscard(false);
    setSaveError(null);
    setConflict(false);
  }

  function update(next: string, nextHsv = rgbToHsv(hexToRgb(next))) {
    setHex(next);
    setHexInput(next);
    setChannels(hexToRgb(next).map(String));
    setHsv(nextHsv);
    setTouched(true);
    setDiscard(false);
    onPreview(next);
  }
  function requestClose() {
    if (saving || reloading) return;
    if (dirty) setDiscard(true);
    else {
      setOpen(false);
      onCancel();
    }
  }
  function setWheel(e: PointerEvent<HTMLDivElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const point = wheelPosition(
      (e.clientX - box.left - box.width / 2) / (box.width / 2),
      (e.clientY - box.top - box.height / 2) / (box.height / 2),
    );
    const next = { ...hsv, ...point };
    update(rgbToHex(hsvToRgb(next)), next);
  }
  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) return requestClose();
        resetFields(shade);
        setLoadedRevision(expectedRevision);
        onBegin();
        setOpen(true);
      }}
    >
      <Popover.Trigger asChild>
        <button
          type="button"
          className="studio-edit-swatch"
          disabled={disabled}
          aria-label={`Edit appearance for ${name}`}
        >
          <span
            className={`studio-swatch${shade ? "" : " is-unconfigured"}`}
            style={shade ? { backgroundColor: shade } : undefined}
            aria-hidden="true"
          >
            <Pencil size={14} />
          </span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="studio-color-editor"
          side="left"
          align="start"
          sideOffset={12}
          collisionPadding={12}
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-description`}
          onEscapeKeyDown={(e) => {
            e.preventDefault();
            requestClose();
          }}
          onInteractOutside={(e) => {
            e.preventDefault();
          }}
        >
          <header>
            <div>
              <h3 id={`${id}-title`}>{name}</h3>
              <p id={`${id}-description`}>
                {shade ? "Colour appearance · Saved profile" : "Colour appearance · Not configured"}
              </p>
            </div>
            <button
              type="button"
              aria-label="Close colour editor"
              disabled={saving}
              onClick={requestClose}
            >
              <X size={18} />
            </button>
          </header>
          <div className="studio-editor-scroll">
            <div
              className="studio-wheel"
              aria-hidden="true"
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
                setWheel(e);
              }}
              onPointerMove={(e) => {
                if (e.currentTarget.hasPointerCapture(e.pointerId)) setWheel(e);
              }}
            >
              <span className="studio-wheel-darken" style={{ opacity: 1 - hsv.v }} />
              <span
                className="studio-wheel-cursor"
                style={{
                  left: `${50 + Math.cos((hsv.h * Math.PI) / 180) * hsv.s * 50}%`,
                  top: `${50 + Math.sin((hsv.h * Math.PI) / 180) * hsv.s * 50}%`,
                  backgroundColor: hex,
                }}
              />
            </div>
            <label className="studio-brightness">
              Brightness <output>{Math.round(hsv.v * 100)}%</output>
              <input
                type="range"
                min="0"
                max="100"
                value={Math.round(hsv.v * 100)}
                onChange={(e) => {
                  const next: HSV = { ...hsv, v: Number(e.target.value) / 100 };
                  update(rgbToHex(hsvToRgb(next)), next);
                }}
              />
            </label>
            <p className="studio-editor-hint">Choose on the wheel or enter RGB / HEX.</p>
            <div className="studio-rgb-fields">
              {["Red", "Green", "Blue"].map((label, index) => (
                <label key={label}>
                  {label}
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="off"
                    value={channels[index]}
                    aria-invalid={parseChannel(channels[index]) === null}
                    aria-describedby={!valid ? `${id}-error` : undefined}
                    onChange={(e) => {
                      const next = [...channels];
                      next[index] = e.target.value;
                      setChannels(next);
                      setTouched(true);
                      setDiscard(false);
                      const parsed = next.map(parseChannel);
                      if (parsed.every((c) => c !== null)) update(rgbToHex(parsed as RGB));
                    }}
                  />
                </label>
              ))}
            </div>
            <label className="studio-hex-field">
              HEX
              <input
                type="text"
                autoComplete="off"
                spellCheck={false}
                value={hexInput}
                aria-invalid={!/^#?[\da-f]{6}$/i.test(hexInput)}
                aria-describedby={!valid ? `${id}-error` : undefined}
                onChange={(e) => {
                  setHexInput(e.target.value);
                  setTouched(true);
                  setDiscard(false);
                  const next = parseHex(e.target.value);
                  if (next) {
                    setHex(next);
                    setChannels(hexToRgb(next).map(String));
                    setHsv(rgbToHsv(hexToRgb(next)));
                    onPreview(next);
                  }
                }}
              />
            </label>
            {!valid && (
              <p className="studio-editor-error" role="alert" id={`${id}-error`}>
                Use whole RGB values from 0 to 255 and a 6-digit HEX colour.
              </p>
            )}
            <div className="studio-color-compare">
              <div>
                <span
                  className={`studio-swatch${shade ? "" : " is-unconfigured"}`}
                  style={shade ? { backgroundColor: shade } : undefined}
                />
                <span>{shade ? "Saved appearance" : "Not configured"}</span>
              </div>
              <div>
                <span className="studio-swatch" style={{ backgroundColor: hex }} />
                <span>New preview</span>
              </div>
            </div>
            <p>
              Screen appearance only; this is not a calibrated paint match. Standard name and colour
              family stay linked.
            </p>
            {inheritedFrom && (
              <p>
                Showing an appearance inherited from {inheritedFrom}. Your first save for {name}{" "}
                starts its own profile.
              </p>
            )}
            {!canSave && (
              <p id={`${id}-save-note`}>
                An Engineer or Admin can save appearances. You can preview a shade.
              </p>
            )}
            {saveError && (
              <div className="studio-save-error" role="alert">
                <p>{saveError}</p>
                {conflict && (
                  <button
                    type="button"
                    disabled={reloading}
                    onClick={async () => {
                      setReloading(true);
                      try {
                        const latest = await onReload();
                        resetFields(latest.hex);
                        setLoadedRevision(latest.revision);
                        onPreview(latest.hex ?? NEUTRAL_BODY);
                      } catch (error) {
                        setSaveError(
                          error instanceof Error
                            ? error.message
                            : "Could not reload the saved appearance.",
                        );
                      } finally {
                        setReloading(false);
                      }
                    }}
                  >
                    {reloading ? "Reloading…" : "Reload saved appearance"}
                  </button>
                )}
              </div>
            )}
          </div>
          {discard ? (
            <div className="studio-discard" role="alert">
              <p>Discard your colour changes?</p>
              <div className="studio-editor-actions">
                <button type="button" autoFocus onClick={() => setDiscard(false)}>
                  Keep editing
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    onCancel();
                  }}
                >
                  Discard changes
                </button>
              </div>
            </div>
          ) : (
            <footer className="studio-editor-actions">
              <button type="button" disabled={saving} onClick={requestClose}>
                Cancel
              </button>
              <button
                type="button"
                className="studio-apply"
                disabled={!valid || !dirty || saving}
                onClick={() => {
                  onApply(hex);
                  setOpen(false);
                }}
              >
                Apply preview
              </button>
              <button
                type="button"
                disabled={!canSave || !valid || !dirty || saving || reloading || conflict}
                aria-describedby={!canSave ? `${id}-save-note` : undefined}
                onClick={async () => {
                  setSaving(true);
                  setSaveError(null);
                  try {
                    await onSave(hex, loadedRevision);
                    setOpen(false);
                  } catch (error) {
                    setConflict(error instanceof ApiError && error.status === 409);
                    setSaveError(
                      error instanceof Error
                        ? error.message
                        : "Could not save appearance. Try again.",
                    );
                  } finally {
                    setSaving(false);
                  }
                }}
              >
                {saving ? "Saving…" : "Save appearance"}
              </button>
            </footer>
          )}
        </Popover.Content>
      </Popover.Portal>
      {blocker.status === "blocked" &&
        createPortal(
          <div
            className="studio-navigation-guard"
            role="alertdialog"
            aria-modal="true"
            aria-label="Unsaved colour changes"
          >
            <p>Leave Model Detail and discard your colour changes?</p>
            <button ref={stayButton} type="button" onClick={() => blocker.reset()}>
              Keep editing
            </button>
            <button type="button" onClick={() => blocker.proceed()}>
              Discard and leave
            </button>
          </div>,
          document.body,
        )}
    </Popover.Root>
  );
}
