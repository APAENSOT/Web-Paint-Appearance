import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/queries";
import { reloadedSheetsCopy } from "@/features/measurements/PlantStandard";
import type { components } from "@/api/types";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

type Catalogue = components["schemas"]["CatalogueOut"];
const PLANTS = ["AAT", "FTM", "FVL", "SAP"] as const;

export function ModelAccordion({ catalogue }: { catalogue: Catalogue }) {
  const client = useQueryClient();
  const [error, setError] = useState<Error | null>(null);
  const [attach, setAttach] = useState<{ model: string; plants: string[] } | null>(null);
  const [picked, setPicked] = useState("");
  const [plants, setPlants] = useState<Record<string, boolean>>({ AAT: true });
  const [reloaded, setReloaded] = useState(0);

  const allModels = useMemo(
    () => catalogue.series.flatMap((series) => series.models.map((model) => model.model_code)),
    [catalogue.series],
  );

  const refresh = () => client.invalidateQueries({ queryKey: ["standards"] });
  const attachMut = useMutation({
    mutationFn: (body: components["schemas"]["PlantModelAttachIn"]) =>
      api().attachPlantModels(body),
    onSuccess: async (out) => {
      setAttach(null);
      setError(null);
      // T115 (D-115-4): the held sheets this Attach reloaded.
      setReloaded(out.reloaded_load_ids?.length ?? 0);
      await refresh();
    },
    onError: (err) => setError(err instanceof Error ? err : new Error(String(err))),
  });
  const offeredMut = useMutation({
    mutationFn: (body: components["schemas"]["PlantModelOfferedIn"]) =>
      api().setPlantModelOffered(body),
    onSuccess: async (out) => {
      setError(null);
      setReloaded(out.reloaded_load_ids?.length ?? 0);
      await refresh();
    },
    onError: (err) => setError(err instanceof Error ? err : new Error(String(err))),
  });
  const pending = attachMut.isPending || offeredMut.isPending;

  return (
    <details className="panel border border-border p-4">
      <summary className="min-h-11 cursor-pointer text-base font-semibold">Model</summary>
      {error && (
        <div className="mt-3">
          <ApiErrorState error={error} />
        </div>
      )}
      <div className="mt-4 space-y-6">
        {catalogue.series.map((series) => (
          <section key={series.series_code} className="space-y-3 border-t border-border pt-4">
            <h3 className="text-sm font-semibold">{series.series_code}</h3>
            <ul className="space-y-3">
              {series.models.map((model) => (
                <li key={model.model_code} className="space-y-1">
                  <p className="text-sm font-medium">
                    {model.model_code}
                    <span className="ml-2 text-xs text-muted-foreground">
                      {model.body_style} · {model.expected_zone_count} zones
                    </span>
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {PLANTS.map((plant) => {
                      const offered = model.plants.find(
                        (row) => row.plant_code === plant,
                      )?.is_offered;
                      return (
                        <label
                          key={plant}
                          className="inline-flex min-h-11 items-center gap-2 px-1 text-sm"
                        >
                          <input
                            type="checkbox"
                            className="h-4 w-4"
                            checked={Boolean(offered)}
                            disabled={pending}
                            onChange={(event) => {
                              const next = event.target.checked;
                              if (next) {
                                attachMut.mutate({ model_code: model.model_code, plants: [plant] });
                              } else {
                                offeredMut.mutate({
                                  plant_code: plant,
                                  model_code: model.model_code,
                                  is_offered: false,
                                });
                              }
                            }}
                          />
                          <span>
                            {plant}
                            {offered ? " offered" : " not offered"}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
        <form
          className="space-y-2 rounded-md border border-border p-3"
          onSubmit={(event) => {
            event.preventDefault();
            const ticked = PLANTS.filter((plant) => plants[plant]);
            if (!picked || !ticked.length) return;
            setAttach({ model: picked, plants: ticked });
          }}
        >
          <p className="text-xs font-medium">Attach existing model</p>
          <label className="block text-xs" htmlFor="attach-model">
            Model code
            <select
              id="attach-model"
              className="mt-1 min-h-11 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              value={picked}
              disabled={pending}
              onChange={(event) => setPicked(event.target.value)}
            >
              <option value="">Pick existing model_code</option>
              {allModels.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap gap-2">
            {PLANTS.map((plant) => (
              <label key={plant} className="inline-flex min-h-11 items-center gap-2 px-1 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={Boolean(plants[plant])}
                  disabled={pending}
                  onChange={(event) =>
                    setPlants((prev) => ({ ...prev, [plant]: event.target.checked }))
                  }
                />
                {plant}
              </label>
            ))}
          </div>
          <Button type="submit" className="min-h-11" disabled={pending}>
            Attach model
          </Button>
          {reloadedSheetsCopy(reloaded) && (
            <p role="status" className="text-xs text-muted-foreground">
              {reloadedSheetsCopy(reloaded)}
            </p>
          )}
        </form>
      </div>
      <Dialog open={attach !== null} onOpenChange={(open) => !open && !pending && setAttach(null)}>
        <DialogContent>
          <DialogTitle>Confirm attach</DialogTitle>
          {attach && (
            <>
              <DialogDescription>
                {`Attach ${attach.model} at ${attach.plants.join(", ")}. This uses an existing model_code; it does not mint a new one.`}
              </DialogDescription>
              <div className="flex flex-wrap gap-2">
                <Button
                  className="min-h-11"
                  disabled={pending}
                  onClick={() =>
                    attachMut.mutate({ model_code: attach.model, plants: attach.plants })
                  }
                >
                  Confirm
                </Button>
                <Button
                  className="min-h-11"
                  variant="outline"
                  disabled={pending}
                  onClick={() => setAttach(null)}
                >
                  Cancel
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </details>
  );
}
