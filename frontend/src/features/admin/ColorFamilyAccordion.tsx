import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

type Catalogue = components["schemas"]["CatalogueOut"];
type Family = components["schemas"]["CatalogueFamilyOut"];
type Color = components["schemas"]["CatalogueColorOut"];

const PLANTS = ["AAT", "FTM", "FVL", "SAP"] as const;
const WORKBOOK_HASH = "b9f54fcd8c921eb10b834f59ddafcf4c07369857fc3b2dedff45e855640aacd8";

function PlantTicks({
  values,
  disabled,
  onToggle,
}: {
  values: Record<string, boolean>;
  disabled: boolean;
  onToggle: (plant: string, next: boolean) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {PLANTS.map((plant) => (
        <label key={plant} className="inline-flex min-h-11 items-center gap-2 px-1 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={Boolean(values[plant])}
            disabled={disabled}
            onChange={(event) => onToggle(plant, event.target.checked)}
          />
          <span>
            {plant}
            {values[plant] ? " offered" : " not offered"}
          </span>
        </label>
      ))}
    </div>
  );
}

export function ColorFamilyAccordion({ catalogue }: { catalogue: Catalogue }) {
  const client = useQueryClient();
  const [mint, setMint] = useState<{
    family: Family;
    name: string;
    plants: string[];
  } | null>(null);
  const [publish, setPublish] = useState<Family | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [targetPlant, setTargetPlant] = useState<string>("AAT");
  const [error, setError] = useState<Error | null>(null);

  const refresh = () => client.invalidateQueries({ queryKey: ["standards", "catalogue"] });

  const mintMut = useMutation({
    mutationFn: (body: components["schemas"]["ColorMintIn"]) => api().mintColour(body),
    onSuccess: async () => {
      setMint(null);
      setError(null);
      await refresh();
    },
    onError: (err) => setError(err instanceof Error ? err : new Error(String(err))),
  });
  const plantMut = useMutation({
    mutationFn: (body: components["schemas"]["PlantColorPatchIn"]) => api().setPlantColour(body),
    onSuccess: async () => {
      setError(null);
      await refresh();
    },
    onError: (err) => setError(err instanceof Error ? err : new Error(String(err))),
  });
  const publishMut = useMutation({
    mutationFn: (body: components["schemas"]["StandardPublishIn"]) => api().publishStandard(body),
    onSuccess: async () => {
      setPublish(null);
      setError(null);
      await refresh();
      await client.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (err) => setError(err instanceof Error ? err : new Error(String(err))),
  });

  const pending = mintMut.isPending || plantMut.isPending || publishMut.isPending;

  return (
    <details className="panel border border-border p-4">
      <summary className="min-h-11 cursor-pointer text-base font-semibold">Color Family</summary>
      {error && (
        <div className="mt-3">
          <ApiErrorState error={error} />
        </div>
      )}
      <div className="mt-4 space-y-6">
        {catalogue.families.map((family) => {
          const nested = catalogue.colors.filter((color) =>
            color.plants.some((plant) => plant.family_code === family.family_code),
          );
          const key = family.family_code;
          const targets = family.plants.find((row) => row.plant_code === targetPlant);
          return (
            <section key={key} className="space-y-3 border-t border-border pt-4">
              <h3 className="text-sm font-semibold">
                {family.family_name} ({family.family_code})
              </h3>
              <label className="block text-xs">
                Plant for Ford/Min
                <select
                  className="mt-1 min-h-11 border border-border bg-background px-3"
                  value={targetPlant}
                  onChange={(event) => setTargetPlant(event.target.value)}
                >
                  {PLANTS.map((plant) => (
                    <option key={plant} value={plant}>
                      {plant}
                    </option>
                  ))}
                </select>
              </label>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {(
                  [
                    ["ford_h", "Ford H", targets?.ford_h],
                    ["ford_v", "Ford V", targets?.ford_v],
                    ["min_h", "Min H", targets?.min_h],
                    ["min_v", "Min V", targets?.min_v],
                  ] as const
                ).map(([field, label, current]) => (
                  <label key={field} className="block text-xs">
                    {label}
                    <Input
                      className="mt-1 min-h-11"
                      inputMode="numeric"
                      value={
                        draft[`${key}:${targetPlant}:${field}`] ??
                        (current == null ? "" : String(current))
                      }
                      onChange={(event) =>
                        setDraft((prev) => ({
                          ...prev,
                          [`${key}:${targetPlant}:${field}`]: event.target.value,
                        }))
                      }
                    />
                  </label>
                ))}
              </div>
              <Button className="min-h-11" disabled={pending} onClick={() => setPublish(family)}>
                Publish new version
              </Button>
              <ul className="space-y-3">
                {nested.map((color) => (
                  <li key={color.color_name} className="space-y-1">
                    <p className="text-sm font-medium">{color.color_name}</p>
                    <PlantTicks
                      disabled={pending}
                      values={Object.fromEntries(
                        color.plants.map((plant) => [plant.plant_code, plant.is_offered]),
                      )}
                      onToggle={(plant, next) =>
                        plantMut.mutate({
                          plant_code: plant,
                          color_name: color.color_name,
                          is_offered: next,
                          family_code: next ? family.family_code : undefined,
                        })
                      }
                    />
                  </li>
                ))}
              </ul>
              <MintForm
                disabled={pending}
                family={family}
                onAsk={(name, plants) => setMint({ family, name, plants })}
              />
            </section>
          );
        })}
      </div>
      <Dialog open={mint !== null} onOpenChange={(open) => !open && !pending && setMint(null)}>
        <DialogContent>
          <DialogTitle>Confirm new colour</DialogTitle>
          {mint && (
            <>
              <DialogDescription>
                {`Add colour ${mint.name} under ${mint.family.family_name} (${mint.family.family_code}) at ${mint.plants.join(", ")}. This cannot be undone from this screen.`}
              </DialogDescription>
              <div className="flex flex-wrap gap-2">
                <Button
                  className="min-h-11"
                  disabled={pending}
                  onClick={() =>
                    mintMut.mutate({
                      color_name: mint.name,
                      family_code: mint.family.family_code,
                      plants: mint.plants,
                    })
                  }
                >
                  Confirm
                </Button>
                <Button
                  className="min-h-11"
                  variant="outline"
                  disabled={pending}
                  onClick={() => setMint(null)}
                >
                  Cancel
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
      <Dialog
        open={publish !== null}
        onOpenChange={(open) => !open && !pending && setPublish(null)}
      >
        <DialogContent>
          <DialogTitle>Confirm publish</DialogTitle>
          {publish && (
            <PublishConfirm
              family={publish}
              plant={targetPlant}
              draft={draft}
              pending={pending}
              onCancel={() => setPublish(null)}
              onConfirm={(body) => publishMut.mutate(body)}
            />
          )}
        </DialogContent>
      </Dialog>
    </details>
  );
}

function MintForm({
  family,
  disabled,
  onAsk,
}: {
  family: Family;
  disabled: boolean;
  onAsk: (name: string, plants: string[]) => void;
}) {
  const [name, setName] = useState("");
  const [plants, setPlants] = useState<Record<string, boolean>>({ AAT: true });
  return (
    <form
      className="space-y-2 rounded-md border border-border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        const ticked = PLANTS.filter((plant) => plants[plant]);
        if (!name.trim() || !ticked.length) return;
        onAsk(name.trim(), ticked);
      }}
    >
      <p className="text-xs font-medium">Add colour under {family.family_name}</p>
      <label className="block text-xs">
        Colour name
        <Input
          className="mt-1 min-h-11"
          value={name}
          disabled={disabled}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <PlantTicks
        disabled={disabled}
        values={plants}
        onToggle={(plant, next) => setPlants((prev) => ({ ...prev, [plant]: next }))}
      />
      <Button type="submit" className="min-h-11" disabled={disabled}>
        Add colour
      </Button>
    </form>
  );
}

function PublishConfirm({
  family,
  plant,
  draft,
  pending,
  onCancel,
  onConfirm,
}: {
  family: Family;
  plant: string;
  draft: Record<string, string>;
  pending: boolean;
  onCancel: () => void;
  onConfirm: (body: components["schemas"]["StandardPublishIn"]) => void;
}) {
  const key = family.family_code;
  const targets = family.plants.find((row) => row.plant_code === plant);
  const num = (field: string, fallback: number | null | undefined) => {
    const raw = draft[`${key}:${plant}:${field}`];
    if (raw == null || raw === "") return fallback ?? 0;
    return Number(raw);
  };
  const [note, setNote] = useState(`Admin publish ${family.family_code}`);
  const [from, setFrom] = useState("2026-09-22");
  return (
    <>
      <DialogDescription>
        Prior Ford/Min versions stay. This appends two FAMILY rows (H and V) for{" "}
        {family.family_name} at {plant}.
      </DialogDescription>
      <label className="block text-xs">
        Effective from
        <Input
          className="mt-1 min-h-11"
          type="date"
          value={from}
          onChange={(e) => setFrom(e.target.value)}
        />
      </label>
      <label className="block text-xs">
        Source note
        <Input className="mt-1 min-h-11" value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          disabled={pending}
          onClick={() =>
            onConfirm({
              plant_code: plant,
              family_code: family.family_code,
              ford_h: num("ford_h", targets?.ford_h),
              ford_v: num("ford_v", targets?.ford_v),
              min_h: num("min_h", targets?.min_h),
              min_v: num("min_v", targets?.min_v),
              effective_from: from,
              source_document: WORKBOOK_HASH,
              source_note: note,
            })
          }
        >
          Confirm
        </Button>
        <Button className="min-h-11" variant="outline" disabled={pending} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </>
  );
}
