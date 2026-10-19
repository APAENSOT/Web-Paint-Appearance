import { useState } from "react";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { FilmCoatingSelector } from "./FilmCoatingSelector";
import { FilmOverviewChart } from "./FilmOverviewChart";
import {
  FILM_LAYERS,
  filmMonthTitle,
  groupFilmBoxes,
  type FilmOverviewData,
} from "./film-overview-display";
import "./film-overview.css";
import { PointLabelsProvider } from "@/features/measurements/point-labels";

export function FilmOverview({
  data,
  isLoading,
  error,
  retry,
}: {
  data?: FilmOverviewData;
  isLoading: boolean;
  error: Error | null;
  retry: () => void;
}) {
  const [layer, setLayer] = useState("ECOAT");
  return (
    // D-RO17-16: the box summary's outside-limit points show the plant's label.
    <PointLabelsProvider plant={data?.plant_code}>
      <section
        className="film-overview panel min-w-0 p-4 sm:p-5"
        aria-label="Film Monthly Overview"
      >
        <Tabs value={layer} onValueChange={setLayer} className="min-w-0">
          <header className="film-overview-header">
            <div>
              <h2 className="text-xl font-bold">Film Thickness</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Monthly overview · thickness in µm
              </p>
              {!isLoading && !error && data && (
                <p className="mt-2 text-sm">{filmMonthTitle(data.month)}</p>
              )}
            </div>
            <FilmCoatingSelector selected={layer} />
          </header>
          {!isLoading && !error && data && (
            <details className="film-overview-method">
              <summary>Standards & colour order</summary>
              <p>{data.standards_note}</p>
              <p>
                Colours follow current Base standards; colours without Base standards appear last.
              </p>
            </details>
          )}
          {FILM_LAYERS.map((item) => (
            <TabsContent value={item.code} key={item.code} className="film-layer-content">
              <h2 className="film-selected-layer mt-5 text-lg font-semibold">{item.label}</h2>
              {error ? (
                <ApiErrorState error={error} retry={retry} />
              ) : isLoading || !data ? (
                <LoadingState>Loading Film Thickness overview...</LoadingState>
              ) : data.month === null ? (
                <p className="py-6">No Film Thickness measurements for this plant.</p>
              ) : data.boxes.length === 0 ? (
                <p className="py-6">No active Film Thickness readings for this selection.</p>
              ) : groupFilmBoxes(data, item.code).length === 0 ? (
                <p className="py-6">No readings for this layer.</p>
              ) : (
                groupFilmBoxes(data, item.code).map((group) => (
                  <section
                    className="mt-5 min-w-0"
                    key={group.model}
                    aria-label={`${group.model} ${item.label}`}
                  >
                    <h3 className="mb-3 text-base font-semibold">{group.model}</h3>
                    <FilmOverviewChart
                      key={`${data.plant_code}-${data.month}-${JSON.stringify(data.models)}-${JSON.stringify(data.colors)}-${group.model}-${item.code}`}
                      {...group}
                    />
                  </section>
                ))
              )}
            </TabsContent>
          ))}
        </Tabs>
      </section>
    </PointLabelsProvider>
  );
}
