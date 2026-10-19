import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import {
  api,
  catalogueOptions,
  meOptions,
  modelPointsOptions,
  refreshPlantWorkbooks,
} from "@/api/queries";
import { isAdmin } from "@/api/roles";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { PointCheck } from "@/features/filmthickness/PointCheck";
import { identityChrome } from "./plant-lens";
import "./plant-standard-polish.css";

type Catalogue = components["schemas"]["CatalogueOut"];
type Family = components["schemas"]["CatalogueFamilyOut"];
type Color = components["schemas"]["CatalogueColorOut"];
type ModelCard = components["schemas"]["ModelPointsOut"];
/**
 * T109 (D-109-1): `"points"` is Point Check -- its own entry inside Standard,
 * not a standard. It renders here because `PlantMeasurements.tsx` sends every
 * view but `"film"` to this component, so the new entry needed no change
 * there.
 */
export type StandardView = "family" | "model" | "points";

const THRESHOLDS = [
  { field: "ford_h", label: "Standard Horizontal" },
  { field: "min_h", label: "Minimum Horizontal" },
  { field: "ford_v", label: "Standard Vertical" },
  { field: "min_v", label: "Minimum Vertical" },
] as const;

function plantRow(color: Color, plant: string) {
  return color.plants.find((row) => row.plant_code === plant);
}

function offeredColor(color: Color, plant: string) {
  return plantRow(color, plant)?.is_offered === true;
}

/**
 * T112 (D-112-3) / T112-FIX (D-112F-6): live and counted points; a domain with
 * no list is omitted. A Film-only model says so first, and an attached one with
 * no Film list yet says that rather than nothing.
 */
export function modelPointsLine(model: ModelCard) {
  if (!model.wavescan_ok) {
    const film =
      model.film_points == null ? "no Film points yet" : `Film ${model.film_points} points`;
    return `Film Thickness only · ${film}`;
  }
  return [
    model.wavescan_points == null ? null : `Wave Scan ${model.wavescan_points} points`,
    model.film_points == null ? null : `Film ${model.film_points} points`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** T112-FIX (D-112F-8): Remove now stops two domains, so it asks once first. */
export function removeModelCopy(model: string, plant: string) {
  return `New Wave Scan and Film files of ${model} at ${plant} will be refused. Readings already loaded stay. Attach brings it back.`;
}

/**
 * T115 (D-115-4): Attach reloads the sheets a Removed model held at the plant.
 * One line, only when it reloaded something.
 */
export function reloadedSheetsCopy(count: number) {
  if (count <= 0) return null;
  return `Reloaded ${count} held sheet${count === 1 ? "" : "s"} from the stored file${count === 1 ? "" : "s"}. ${count === 1 ? "It is" : "They are"} back in review on Upload Data.`;
}

export function coloursNotOffered(colors: Color[], plant: string) {
  return colors
    .filter((color) => !offeredColor(color, plant))
    .map((color) => color.color_name)
    .sort((left, right) => left.localeCompare(right));
}

function thresholdValue(
  family: Family,
  plant: string,
  field: (typeof THRESHOLDS)[number]["field"],
) {
  const value = family.plants.find((row) => row.plant_code === plant)?.[field];
  return value == null ? "—" : String(value);
}

export function PlantStandard({ code, view = "family" }: { code: string; view?: StandardView }) {
  const plant = code.toUpperCase();
  const catalogue = useQuery(catalogueOptions);
  const title = view === "model" ? `${plant} model` : `${plant} color family`;
  // T109 (D-109-1): Point Check is not a colour standard, so it does not wait
  // on the catalogue read the two standard views need.
  if (view === "points") return <PointCheck code={plant} />;
  if (catalogue.isPending) {
    return (
      <section className="panel min-w-0 p-5" aria-label={`${plant} standard`}>
        <LoadingState>Loading {title}...</LoadingState>
      </section>
    );
  }
  if (catalogue.isError) {
    return (
      <section className="panel min-w-0 p-5" aria-label={`${plant} standard`}>
        <ApiErrorState error={catalogue.error} retry={() => void catalogue.refetch()} />
      </section>
    );
  }
  return <PlantStandardBody plant={plant} view={view} catalogue={catalogue.data} />;
}

function PlantStandardBody({
  plant,
  view,
  catalogue,
}: {
  plant: string;
  view: StandardView;
  catalogue: Catalogue;
}) {
  const client = useQueryClient();
  // RO12 (D-RO12-4): every write on this page is an Admin route (standards.py);
  // other roles read the same page with the controls hidden.
  const identity = useQuery(meOptions);
  const admin = identity.isSuccess && isAdmin(identity.data.principal);
  const [error, setError] = useState<Error | null>(null);
  const [adjustError, setAdjustError] = useState<string | null>(null);
  const [editingFamily, setEditingFamily] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [mintName, setMintName] = useState<Record<string, string>>({});
  const [colorPick, setColorPick] = useState<Record<string, string>>({});
  const [pickedModel, setPickedModel] = useState("");
  const [confirmMint, setConfirmMint] = useState<{ family: Family; name: string } | null>(null);
  const [confirmAttach, setConfirmAttach] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [reloaded, setReloaded] = useState(0);
  const [openFamilies, setOpenFamilies] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(catalogue.families.map((family) => [family.family_code, true])),
  );
  const [pickedColor, setPickedColor] = useState<string | null>(null);
  const [pickedOffered, setPickedOffered] = useState<string | null>(null);

  // T112: the prefix also refreshes the Model cards' model-points read.
  const refresh = () => client.invalidateQueries({ queryKey: ["standards"] });
  const onErr = (err: unknown) => setError(err instanceof Error ? err : new Error(String(err)));

  const mintMut = useMutation({
    mutationFn: (body: components["schemas"]["ColorMintIn"]) => api().mintColour(body),
    onSuccess: async () => {
      setConfirmMint(null);
      setColorPick({});
      setError(null);
      await refresh();
    },
    onError: onErr,
  });
  const plantMut = useMutation({
    mutationFn: (body: components["schemas"]["PlantColorPatchIn"]) => api().setPlantColour(body),
    onSuccess: async () => {
      setColorPick({});
      setError(null);
      await refresh();
    },
    onError: onErr,
  });
  const publishMut = useMutation({
    mutationFn: (body: components["schemas"]["StandardPublishIn"]) => api().publishStandard(body),
    onSuccess: async () => {
      setEditingFamily(null);
      setAdjustError(null);
      setError(null);
      await refresh();
      await client.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: onErr,
  });
  const attachMut = useMutation({
    mutationFn: (body: components["schemas"]["PlantModelAttachIn"]) =>
      api().attachPlantModels(body),
    onSuccess: async (out) => {
      setConfirmAttach(null);
      setPickedModel("");
      setError(null);
      // T115 (D-115-4): the held sheets this Attach reloaded.
      setReloaded(out.reloaded_load_ids?.length ?? 0);
      await refresh();
      if (out.reloaded_load_ids?.length) await refreshPlantWorkbooks(client, plant);
    },
    onError: onErr,
  });
  const offeredMut = useMutation({
    mutationFn: (body: components["schemas"]["PlantModelOfferedIn"]) =>
      api().setPlantModelOffered(body),
    onSuccess: async (out) => {
      setConfirmRemove(null);
      setError(null);
      setReloaded(out.reloaded_load_ids?.length ?? 0);
      await refresh();
    },
    onError: onErr,
  });

  const pending =
    mintMut.isPending ||
    plantMut.isPending ||
    publishMut.isPending ||
    attachMut.isPending ||
    offeredMut.isPending;

  const startAdjust = (family: Family) => {
    const targets = family.plants.find((row) => row.plant_code === plant);
    setAdjustError(null);
    setEditingFamily(family.family_code);
    setDraft(
      Object.fromEntries(
        THRESHOLDS.map((item) => [
          item.field,
          targets?.[item.field] == null ? "" : String(targets[item.field]),
        ]),
      ),
    );
  };

  const saveAdjust = (family: Family) => {
    const targets = family.plants.find((row) => row.plant_code === plant);
    const values: Record<(typeof THRESHOLDS)[number]["field"], number> = {
      ford_h: 0,
      ford_v: 0,
      min_h: 0,
      min_v: 0,
    };
    for (const item of THRESHOLDS) {
      const raw = (draft[item.field] ?? "").trim();
      if (!/^\d+$/.test(raw) || Number(raw) > 200) {
        setAdjustError(`${item.label} must be a whole number from 0 to 200.`);
        return;
      }
      values[item.field] = Number(raw);
    }
    setAdjustError(null);
    const unchanged = THRESHOLDS.every((item) => values[item.field] === targets?.[item.field]);
    if (unchanged) {
      setEditingFamily(null);
      return;
    }
    const today = new Date();
    const effectiveFrom = [
      today.getFullYear(),
      String(today.getMonth() + 1).padStart(2, "0"),
      String(today.getDate()).padStart(2, "0"),
    ].join("-");
    publishMut.mutate({
      plant_code: plant,
      family_code: family.family_code,
      ford_h: values.ford_h,
      ford_v: values.ford_v,
      min_h: values.min_h,
      min_v: values.min_v,
      effective_from: effectiveFrom,
      source_note: `Adjust ${family.family_name} standards`,
    });
  };

  const byFamily = useMemo(() => {
    const map = new Map<string, Color[]>();
    for (const color of catalogue.colors) {
      if (!offeredColor(color, plant)) continue;
      const familyCode = plantRow(color, plant)?.family_code ?? "";
      const list = map.get(familyCode) ?? [];
      list.push(color);
      map.set(familyCode, list);
    }
    return map;
  }, [catalogue.colors, plant]);

  // T112 (D-112-4) / T112-FIX (D-112F-6): the cards are the server's read --
  // every model offered here, Wave Scan and Film-only alike -- grouped by series.
  const modelPoints = useQuery({ ...modelPointsOptions(plant), enabled: view === "model" });
  const plantSeries = useMemo(() => {
    const bySeries = new Map<string, ModelCard[]>();
    for (const model of modelPoints.data?.models ?? []) {
      bySeries.set(model.series_code, [...(bySeries.get(model.series_code) ?? []), model]);
    }
    return [...bySeries].map(([series_code, models]) => ({ series_code, models }));
  }, [modelPoints.data]);

  const historicalColors = useMemo(
    () => coloursNotOffered(catalogue.colors, plant),
    [catalogue.colors, plant],
  );

  // T112-FIX (D-112F-4): every active model not offered here, Film-only included.
  const attachable = modelPoints.data?.attachable_models ?? [];

  const heading = view === "model" ? "Model" : "Color Family";
  const intro =
    view === "model"
      ? `Models offered on this plant.${admin ? " Attach an existing model_code; this screen does not mint one." : ""}`
      : `Review horizontal and vertical standards by family, and manage colours offered at ${plant}.`;

  return (
    <section className="panel plant-standard min-w-0 p-5" aria-label={`${plant} standard`}>
      <div className="plant-standard__intro mb-6">
        <p className="eyebrow mb-1">{plant} · Standard</p>
        <h2 className="text-xl font-bold">{heading}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{intro}</p>
      </div>
      {error && (
        <div className="mb-4">
          <ApiErrorState error={error} />
        </div>
      )}

      {view === "family" ? (
        <div className="plant-standard__families space-y-4">
          {catalogue.families.map((family) => {
            const colors = byFamily.get(family.family_code) ?? [];
            const key = family.family_code;
            const open = openFamilies[key] !== false;
            const editing = editingFamily === key;
            const pickedColour = colorPick[key] ?? "";
            const typingNewColour = pickedColour === "__other__";
            return (
              <article
                key={key}
                data-family={key}
                className="family-standard-card motion-reduce:transition-none"
              >
                <div className="family-standard-card__header flex flex-wrap items-center justify-between gap-3 px-5 py-5">
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={`family-colours-${plant}-${key}`}
                    onClick={() => setOpenFamilies((prev) => ({ ...prev, [key]: !open }))}
                    className="min-h-11 min-w-0 flex-1 rounded-[var(--radius-sm)] px-1 text-left transition-colors duration-200 hover:bg-[var(--surface-2)]"
                  >
                    <span className="flex items-center gap-2">
                      <ChevronDown
                        aria-hidden
                        className={cn(
                          "size-4 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none",
                          open ? "rotate-0" : "-rotate-90",
                        )}
                      />
                      <span className="min-w-0">
                        <span className="block text-base font-semibold">{family.family_name}</span>
                        <span className="mt-2 flex flex-wrap items-center gap-2">
                          <span className="family-standard-card__code eyebrow">
                            {family.family_code}
                          </span>
                          <span className="eyebrow">
                            {colors.length} {colors.length === 1 ? "colour" : "colours"}
                          </span>
                        </span>
                      </span>
                    </span>
                  </button>
                  {admin && editing ? (
                    <div className="flex flex-wrap gap-2">
                      <Button
                        className="min-h-11"
                        disabled={pending}
                        onClick={() => saveAdjust(family)}
                      >
                        Save standards
                      </Button>
                      <Button
                        variant="outline"
                        className="min-h-11"
                        disabled={pending}
                        onClick={() => {
                          setEditingFamily(null);
                          setAdjustError(null);
                        }}
                      >
                        Cancel
                      </Button>
                    </div>
                  ) : admin ? (
                    <Button
                      variant="outline"
                      className="min-h-11"
                      disabled={pending}
                      onClick={() => startAdjust(family)}
                    >
                      Adjust standards
                    </Button>
                  ) : null}
                </div>
                <ThresholdGrid
                  family={family}
                  plant={plant}
                  editing={editing}
                  values={draft}
                  onChange={(field, value) => setDraft((prev) => ({ ...prev, [field]: value }))}
                />
                {editing && adjustError && (
                  <p className="px-5 pb-2 text-sm text-destructive" role="alert">
                    {adjustError}
                  </p>
                )}
                {editing && (
                  <p className="px-5 pb-4 text-xs text-muted-foreground">
                    Saving keeps the previous Standard and Minimum version.
                  </p>
                )}
                {open && (
                  <div
                    id={`family-colours-${plant}-${key}`}
                    className="space-y-3 border-t border-border px-4 py-4"
                  >
                    {colors.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        No colours on this plant in this family.
                      </p>
                    ) : (
                      <ul className="grid gap-2 sm:grid-cols-2">
                        {colors.map((color) => {
                          const selected = pickedColor === color.color_name;
                          return (
                            <li key={color.color_name}>
                              <div
                                className={cn(
                                  "flex min-h-11 items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-border bg-[var(--panel)] px-3 py-2 transition-[transform,background-color] duration-200 motion-reduce:transform-none",
                                  selected
                                    ? "bg-[var(--primary-soft)]"
                                    : "hover:-translate-y-px hover:bg-[var(--surface-2)]",
                                )}
                                style={
                                  selected
                                    ? { boxShadow: "inset 2px 0 0 var(--color-primary)" }
                                    : undefined
                                }
                              >
                                <button
                                  type="button"
                                  aria-pressed={selected}
                                  className="min-h-11 min-w-0 flex-1 text-left text-sm font-medium"
                                  onClick={() =>
                                    setPickedColor((prev) =>
                                      prev === color.color_name ? null : color.color_name,
                                    )
                                  }
                                >
                                  {color.color_name}
                                </button>
                                {admin && (
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="min-h-11"
                                    disabled={pending}
                                    onClick={() =>
                                      plantMut.mutate({
                                        plant_code: plant,
                                        color_name: color.color_name,
                                        is_offered: false,
                                      })
                                    }
                                  >
                                    Remove from {plant}
                                  </Button>
                                )}
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                    {admin && (
                      <form
                        className="flex flex-wrap items-end gap-2"
                        onSubmit={(event) => {
                          event.preventDefault();
                          if (typingNewColour) {
                            const name = (mintName[key] ?? "").trim();
                            if (!name) return;
                            setConfirmMint({ family, name });
                            return;
                          }
                          if (!pickedColour) return;
                          plantMut.mutate({
                            plant_code: plant,
                            color_name: pickedColour,
                            is_offered: true,
                            family_code: family.family_code,
                          });
                        }}
                      >
                        <label
                          className="block min-w-[12rem] flex-1 text-xs"
                          htmlFor={`pick-colour-${plant}-${key}`}
                        >
                          Add colour at {plant}
                          <Select
                            value={pickedColour || undefined}
                            disabled={pending}
                            onValueChange={(value) =>
                              setColorPick((prev) => ({ ...prev, [key]: value }))
                            }
                          >
                            <SelectTrigger
                              id={`pick-colour-${plant}-${key}`}
                              type="button"
                              className="mt-1 min-h-11 bg-popover text-popover-foreground"
                            >
                              <SelectValue placeholder="Select a historical colour" />
                            </SelectTrigger>
                            <SelectContent className="bg-popover text-popover-foreground">
                              {historicalColors.map((name) => (
                                <SelectItem key={name} value={name} className="min-h-11">
                                  {name}
                                </SelectItem>
                              ))}
                              <SelectItem value="__other__" className="min-h-11">
                                Other — type a new colour
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </label>
                        {typingNewColour && (
                          <label
                            className="block min-w-[12rem] flex-1 text-xs"
                            htmlFor={`mint-${plant}-${key}`}
                          >
                            New colour name
                            <Input
                              id={`mint-${plant}-${key}`}
                              className="mt-1 min-h-11"
                              value={mintName[key] ?? ""}
                              disabled={pending}
                              onChange={(event) =>
                                setMintName((prev) => ({ ...prev, [key]: event.target.value }))
                              }
                            />
                          </label>
                        )}
                        <Button
                          type="submit"
                          className="min-h-11"
                          disabled={
                            pending ||
                            !pickedColour ||
                            (typingNewColour && !(mintName[key] ?? "").trim())
                          }
                        >
                          Add colour
                        </Button>
                      </form>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="space-y-4">
          {modelPoints.isPending ? (
            <LoadingState>Loading models...</LoadingState>
          ) : modelPoints.isError ? (
            <ApiErrorState error={modelPoints.error} retry={() => void modelPoints.refetch()} />
          ) : plantSeries.length === 0 ? (
            <p className="text-sm text-muted-foreground">No models on this plant.</p>
          ) : (
            plantSeries.map((series) => (
              <article
                key={series.series_code}
                className="overflow-hidden rounded-[var(--radius-md)] border border-border bg-[var(--panel-raised)]"
                style={identityChrome}
              >
                <div className="px-4 py-4">
                  <h3 className="text-base font-semibold">{series.series_code}</h3>
                  <p className="eyebrow mt-1">
                    {series.models.length} {series.models.length === 1 ? "model" : "models"}
                  </p>
                </div>
                <ul className="grid gap-2 border-t border-border px-4 py-4 sm:grid-cols-2">
                  {series.models.map((model) => {
                    const selected = pickedOffered === model.model_code;
                    return (
                      <li key={model.model_code}>
                        <div
                          className={cn(
                            "flex min-h-11 flex-col gap-3 rounded-[var(--radius-sm)] border border-border bg-[var(--panel)] px-3 py-3 transition-[transform,background-color] duration-200 motion-reduce:transform-none",
                            selected
                              ? "bg-[var(--primary-soft)]"
                              : "hover:-translate-y-px hover:bg-[var(--surface-2)]",
                          )}
                          style={
                            selected
                              ? { boxShadow: "inset 2px 0 0 var(--color-primary)" }
                              : undefined
                          }
                        >
                          <button
                            type="button"
                            aria-pressed={selected}
                            className="min-h-11 text-left"
                            onClick={() =>
                              setPickedOffered((prev) =>
                                prev === model.model_code ? null : model.model_code,
                              )
                            }
                          >
                            {/* T112-FIX (D-112F-7): one design -- model_code, one line, Remove. */}
                            <span className="block text-sm font-medium">{model.model_code}</span>
                            <span className="mt-1 block text-xs text-muted-foreground">
                              {modelPointsLine(model)}
                            </span>
                          </button>
                          {admin && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="min-h-11 self-start"
                              disabled={pending}
                              onClick={() => setConfirmRemove(model.model_code)}
                            >
                              Remove from {plant}
                            </Button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </article>
            ))
          )}
          {admin && (
            <form
              className="flex flex-wrap items-end gap-2 rounded-[var(--radius-md)] border border-border bg-[var(--panel-raised)] p-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (!pickedModel) return;
                setConfirmAttach(pickedModel);
              }}
            >
              <label
                className="block min-w-[12rem] flex-1 text-xs"
                htmlFor={`attach-model-${plant}`}
              >
                Attach existing model
                <Select
                  value={pickedModel || undefined}
                  disabled={pending || attachable.length === 0}
                  onValueChange={setPickedModel}
                >
                  <SelectTrigger
                    id={`attach-model-${plant}`}
                    type="button"
                    className="mt-1 min-h-11 bg-popover text-popover-foreground"
                  >
                    <SelectValue placeholder="Pick existing model_code" />
                  </SelectTrigger>
                  <SelectContent className="bg-popover text-popover-foreground">
                    {attachable.map((code) => (
                      <SelectItem key={code} value={code} className="min-h-11">
                        {code}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <Button type="submit" className="min-h-11" disabled={pending || !pickedModel}>
                Attach model
              </Button>
              {reloadedSheetsCopy(reloaded) && (
                <p role="status" className="basis-full text-xs text-muted-foreground">
                  {reloadedSheetsCopy(reloaded)}
                </p>
              )}
            </form>
          )}
        </div>
      )}

      <Dialog
        open={confirmMint !== null}
        onOpenChange={(open) => !open && !pending && setConfirmMint(null)}
      >
        <DialogContent>
          <DialogTitle>Confirm new colour</DialogTitle>
          {confirmMint && (
            <>
              <DialogDescription>
                {`Add colour ${confirmMint.name} under ${confirmMint.family.family_name} (${confirmMint.family.family_code}) at ${plant} only. This cannot be undone from this screen.`}
              </DialogDescription>
              <div className="flex flex-wrap gap-2">
                <Button
                  className="min-h-11"
                  disabled={pending}
                  onClick={() =>
                    mintMut.mutate({
                      color_name: confirmMint.name,
                      family_code: confirmMint.family.family_code,
                      plants: [plant],
                    })
                  }
                >
                  Confirm
                </Button>
                <Button
                  variant="outline"
                  className="min-h-11"
                  disabled={pending}
                  onClick={() => setConfirmMint(null)}
                >
                  Cancel
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmAttach !== null}
        onOpenChange={(open) => !open && !pending && setConfirmAttach(null)}
      >
        <DialogContent>
          <DialogTitle>Confirm attach</DialogTitle>
          {confirmAttach && (
            <>
              <DialogDescription>
                {`Attach ${confirmAttach} at ${plant}. This uses an existing model_code; it does not mint a new one.`}
              </DialogDescription>
              <div className="flex flex-wrap gap-2">
                <Button
                  className="min-h-11"
                  disabled={pending}
                  onClick={() => attachMut.mutate({ model_code: confirmAttach, plants: [plant] })}
                >
                  Confirm
                </Button>
                <Button
                  variant="outline"
                  className="min-h-11"
                  disabled={pending}
                  onClick={() => setConfirmAttach(null)}
                >
                  Cancel
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmRemove !== null}
        onOpenChange={(open) => !open && !pending && setConfirmRemove(null)}
      >
        <DialogContent>
          <DialogTitle>Remove from {plant}?</DialogTitle>
          {confirmRemove && (
            <>
              <DialogDescription>{removeModelCopy(confirmRemove, plant)}</DialogDescription>
              <div className="flex flex-wrap gap-2">
                <Button
                  className="min-h-11"
                  disabled={pending}
                  onClick={() =>
                    offeredMut.mutate({
                      plant_code: plant,
                      model_code: confirmRemove,
                      is_offered: false,
                    })
                  }
                >
                  Remove
                </Button>
                <Button
                  variant="outline"
                  className="min-h-11"
                  disabled={pending}
                  onClick={() => setConfirmRemove(null)}
                >
                  Cancel
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}

function ThresholdGrid({
  family,
  plant,
  editing,
  values,
  onChange,
}: {
  family: Family;
  plant: string;
  editing: boolean;
  values: Record<string, string>;
  onChange: (field: string, value: string) => void;
}) {
  return (
    <div
      className="family-standard-card__metrics grid gap-2 border-t border-border px-4 py-4 sm:grid-cols-2"
      role="group"
      aria-label={`${family.family_name} Standard and Minimum`}
    >
      {THRESHOLDS.map((item) => (
        <label
          key={item.field}
          className="family-standard-card__metric rounded-[var(--radius-sm)] border px-3 py-3"
          htmlFor={editing ? `std-${family.family_code}-${item.field}` : undefined}
        >
          <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
          {editing ? (
            <Input
              id={`std-${family.family_code}-${item.field}`}
              className="num mt-2 min-h-11 text-2xl font-semibold"
              inputMode="numeric"
              value={values[item.field] ?? ""}
              onChange={(event) => onChange(item.field, event.target.value)}
            />
          ) : (
            <span className="num mt-2 block text-2xl font-semibold tabular-nums tracking-tight">
              {thresholdValue(family, plant, item.field)}
            </span>
          )}
        </label>
      ))}
    </div>
  );
}
