import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  filmFacetsOptions,
  historyFacetsOptions,
  historySummariesOptions,
  historyVehiclesOptions,
  historyVehiclePointsOptions,
} from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { MeasurementCorrection } from "./MeasurementCorrection";
import { FilmThickness } from "@/features/filmthickness/FilmThickness";
import { DataDomainFilter } from "./DataDomainFilter";
import type { DataDomain } from "./domain-tags";
import { modelVocabularyNote, type PlantSearch } from "./history-search";
import { wavescanMeasure } from "./wavescan-inspection";
import { carLine } from "./review-copy";
import { usePointLabels } from "./point-labels";
import { dayRange, dayText, weekText } from "./day-text";

type ChangeSearch = (next: PlantSearch, replace?: boolean) => void;
type Vehicle = components["schemas"]["HistoryVehicleSetOut"];
const selectClass =
  "mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm";

export function MeasurementHistory({
  code,
  canCorrect,
  search,
  onSearch,
}: {
  code: string;
  canCorrect: boolean;
  search: PlantSearch;
  onSearch: ChangeSearch;
}) {
  const [notice, setNotice] = useState<string | Error>("");
  const domain: DataDomain = search.dataDomain ?? "both";
  // T105 (D-105-1/D-105-4): the open card's identity is its own search params.
  // Old links that carry the filter params as the card identity still work.
  const cardModel = search.cardModel ?? search.model;
  const cardColor = search.cardColor ?? search.color;
  // T108: Film's open card reads its own two params only. There are no old
  // Film card links to keep working -- before T108 Film had no cards.
  const filmCardModel = search.filmCardModel;
  const filmCardColor = search.filmCardColor;
  const waveEnabled = domain !== "film";
  const filmEnabled = domain !== "wavescan";
  const waveBase = useQuery({ ...historyFacetsOptions(code), enabled: waveEnabled });
  const filmBase = useQuery({ ...filmFacetsOptions(code), enabled: filmEnabled });
  const waveMonths = waveEnabled ? (waveBase.data?.months ?? []) : [];
  const filmMonths = filmEnabled ? (filmBase.data?.months ?? []) : [];
  const months = [...new Set([...waveMonths, ...filmMonths])].sort((a, b) => b.localeCompare(a));
  const month = search.month && months.includes(search.month) ? search.month : months[0];
  const waveMonth = Boolean(month && waveMonths.includes(month));
  const filmMonth = Boolean(month && filmMonths.includes(month));
  const facets = useQuery({
    ...historyFacetsOptions(code, { month, model: search.model }),
    enabled: waveEnabled && waveMonth,
  });
  // T108 (D-108-3): Film honours Model / Colour, so the pick lists are both
  // domains' own facets, cascaded by the server. Film and WaveScan name
  // models differently (`P703` against `P703 DBL RANGER`), so this is a
  // union of two vocabularies and never a translation between them.
  const filmFacets = useQuery({
    ...filmFacetsOptions(code, { month, model: search.model }),
    enabled: filmEnabled && filmMonth,
  });
  const pickable = (waveEnabled && waveMonth) || (filmEnabled && filmMonth);
  const modelOptions = [
    ...new Set([...(facets.data?.models ?? []), ...(filmFacets.data?.models ?? [])]),
  ].sort();
  const colorOptions = [
    ...new Set([...(facets.data?.colors ?? []), ...(filmFacets.data?.colors ?? [])]),
  ].sort();
  const vocabularyNote = modelVocabularyNote(facets.data?.models, filmFacets.data?.models);
  const listsPending =
    (waveEnabled && waveMonth && facets.isPending) ||
    (filmEnabled && filmMonth && filmFacets.isPending);
  useEffect(() => {
    if (
      (!waveEnabled || waveBase.isSuccess) &&
      (!filmEnabled || filmBase.isSuccess) &&
      search.month !== month
    ) {
      onSearch(
        {
          ...search,
          month,
          model: undefined,
          color: undefined,
          cardModel: undefined,
          cardColor: undefined,
          week: undefined,
          vehicle: undefined,
          filmWeek: undefined,
          filmCardModel: undefined,
          filmCardColor: undefined,
          filmVehicle: undefined,
        },
        true,
      );
    }
  }, [search, month, waveEnabled, filmEnabled, waveBase.isSuccess, filmBase.isSuccess, onSearch]);
  return (
    <section className="panel min-w-0 p-5" aria-label="Measurement History">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow mb-1">Approved measurements</p>
          <h2 className="text-xl font-bold">Measurement History</h2>
        </div>
        {!canCorrect && <span className="text-xs text-muted-foreground">Read only</span>}
      </div>
      <div className="mb-5">
        <DataDomainFilter
          value={domain}
          onChange={(dataDomain) => onSearch({ ...search, dataDomain })}
        />
      </div>
      {notice instanceof Error ? (
        <ApiErrorState error={notice} />
      ) : (
        notice && (
          <p role="status" className="mb-4 text-sm">
            {notice}
          </p>
        )
      )}
      {(waveEnabled && waveBase.isPending) || (filmEnabled && filmBase.isPending) ? (
        <LoadingState>Loading History filters...</LoadingState>
      ) : waveEnabled && waveBase.isError ? (
        <ApiErrorState error={waveBase.error} retry={() => void waveBase.refetch()} />
      ) : filmEnabled && filmBase.isError ? (
        <ApiErrorState error={filmBase.error} retry={() => void filmBase.refetch()} />
      ) : (
        <>
          {months.length === 0 ? (
            <EmptyHistory domain={domain} />
          ) : (
            <>
              <div className="mb-6 grid gap-3 sm:grid-cols-3">
                <label className="text-xs font-medium">
                  Month
                  <select
                    aria-label="Month"
                    className={selectClass}
                    value={month ?? ""}
                    onChange={(e) =>
                      onSearch({
                        ...search,
                        month: e.target.value,
                        model: undefined,
                        color: undefined,
                        cardModel: undefined,
                        cardColor: undefined,
                        week: undefined,
                        vehicle: undefined,
                        filmWeek: undefined,
                        filmCardModel: undefined,
                        filmCardColor: undefined,
                        filmVehicle: undefined,
                      })
                    }
                  >
                    {months.map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                </label>
                {pickable && (
                  <label className="text-xs font-medium">
                    Model
                    <select
                      aria-label="Model"
                      className={selectClass}
                      disabled={!month || listsPending}
                      value={search.model ?? ""}
                      onChange={(e) =>
                        onSearch({
                          ...search,
                          month,
                          model: e.target.value || undefined,
                          color: undefined,
                          cardModel: undefined,
                          cardColor: undefined,
                          week: undefined,
                          vehicle: undefined,
                          filmWeek: undefined,
                          filmCardModel: undefined,
                          filmCardColor: undefined,
                          filmVehicle: undefined,
                        })
                      }
                    >
                      <option value="">All</option>
                      {search.model && !modelOptions.includes(search.model) && (
                        <option>{search.model}</option>
                      )}
                      {modelOptions.map((item) => (
                        <option key={item}>{item}</option>
                      ))}
                    </select>
                  </label>
                )}
                {pickable && (
                  <label className="text-xs font-medium">
                    Colour
                    <select
                      aria-label="Colour"
                      className={selectClass}
                      disabled={!month || listsPending}
                      value={search.color ?? ""}
                      onChange={(e) =>
                        onSearch({
                          ...search,
                          month,
                          model: search.model,
                          color: e.target.value || undefined,
                          cardModel: undefined,
                          cardColor: undefined,
                          week: undefined,
                          vehicle: undefined,
                          filmWeek: undefined,
                          filmCardModel: undefined,
                          filmCardColor: undefined,
                          filmVehicle: undefined,
                        })
                      }
                    >
                      <option value="">All</option>
                      {search.color && !colorOptions.includes(search.color) && (
                        <option>{search.color}</option>
                      )}
                      {colorOptions.map((item) => (
                        <option key={item}>{item}</option>
                      ))}
                    </select>
                  </label>
                )}
                {domain === "both" && waveMonth && filmMonth && vocabularyNote && (
                  <p className="text-xs text-muted-foreground sm:col-span-3">{vocabularyNote}</p>
                )}
              </div>
              {waveEnabled && waveMonth && month && (
                <section aria-label="WaveScan History" className="mb-6">
                  <h3 className="mb-3 text-lg font-semibold">WaveScan</h3>
                  {facets.isError ? (
                    <ApiErrorState error={facets.error} retry={() => void facets.refetch()} />
                  ) : facets.isPending ? (
                    <LoadingState>Loading WaveScan filters...</LoadingState>
                  ) : search.week !== undefined && cardModel && cardColor ? (
                    <div key={`${month}/${search.week}/${cardModel}/${cardColor}`}>
                      <div className="mb-4 flex flex-wrap items-center gap-3">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            onSearch({
                              ...search,
                              month,
                              cardModel: undefined,
                              cardColor: undefined,
                              week: undefined,
                              vehicle: undefined,
                            })
                          }
                        >
                          Back to week cards
                        </Button>
                        <h3 className="text-sm font-semibold">
                          {weekText(search.week)} / {cardModel} / {cardColor}
                        </h3>
                      </div>
                      {search.vehicle ? (
                        <HistoryPoints
                          key={search.vehicle}
                          code={code}
                          vehicleId={search.vehicle}
                          canCorrect={canCorrect}
                          onNotice={setNotice}
                          onBack={() => onSearch({ ...search, vehicle: undefined })}
                        />
                      ) : (
                        <HistoryVehicles
                          code={code}
                          month={month}
                          week={search.week}
                          model={cardModel}
                          color={cardColor}
                          onOpen={(vehicle) => onSearch({ ...search, vehicle })}
                        />
                      )}
                    </div>
                  ) : (
                    <HistoryWeeks code={code} search={{ ...search, month }} onSearch={onSearch} />
                  )}
                </section>
              )}
              {filmEnabled && filmMonth && month && (
                <FilmThickness
                  context="history"
                  code={code}
                  month={month}
                  // T108 (D-108-3): Film honours the Model / Colour filters.
                  // Before T108 it was sent `undefined` and ignored them.
                  model={search.model}
                  color={search.color}
                  // T105's rule, D-108-3: the open card is its own params, so
                  // opening one never writes a filter and Back never clears one.
                  week={search.filmWeek}
                  cardModel={filmCardModel}
                  cardColor={filmCardColor}
                  vehicleId={search.filmVehicle}
                  onCard={(card) =>
                    onSearch({
                      ...search,
                      month,
                      filmWeek: card?.week,
                      filmCardModel: card?.model,
                      filmCardColor: card?.color,
                      filmVehicle: undefined,
                    })
                  }
                  onVehicle={(filmVehicle) => onSearch({ ...search, month, filmVehicle })}
                />
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}

function EmptyHistory({ domain }: { domain: DataDomain }) {
  return (
    <p className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
      {domain === "film"
        ? "No Film Thickness measurements for this plant"
        : domain === "wavescan"
          ? "No WaveScan measurements for this plant"
          : "No approved measurements for this plant"}
    </p>
  );
}

function HistoryWeeks({
  code,
  search,
  onSearch,
}: {
  code: string;
  search: PlantSearch;
  onSearch: ChangeSearch;
}) {
  const summaries = useQuery(
    historySummariesOptions(code, {
      month: search.month!,
      model: search.model,
      color: search.color,
    }),
  );
  if (summaries.isPending) return <LoadingState>Loading week cards...</LoadingState>;
  if (summaries.isError)
    return <ApiErrorState error={summaries.error} retry={() => void summaries.refetch()} />;
  if (!summaries.data.weeks.length)
    return (
      <p className="py-8 text-sm text-muted-foreground">
        No approved measurements for this selection
      </p>
    );
  return (
    <div className="space-y-6">
      {summaries.data.weeks.map((week) => (
        <section key={week.week} aria-label={weekText(week.week)}>
          <h3 className="mb-3 border-b border-border pb-2 text-sm font-semibold">
            {weekText(week.week)}
          </h3>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {week.cards.map((card, index) => (
              <button
                key={`${card.model}/${card.color}/${index}`}
                type="button"
                disabled={!card.model || !card.color}
                className="min-w-0 rounded-lg border border-border bg-[var(--surface-2)] p-4 text-left transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-60"
                onClick={() =>
                  onSearch({
                    ...search,
                    month: summaries.data.month,
                    week: week.week,
                    cardModel: card.model ?? undefined,
                    cardColor: card.color ?? undefined,
                  })
                }
              >
                <span className="mb-2 inline-block rounded-sm border border-border px-2 py-0.5 text-[10px] font-semibold">
                  WaveScan
                </span>
                <span className="block break-words text-base font-semibold">
                  {card.model ?? "Model not recorded"} / {card.color ?? "Colour not recorded"}
                </span>
                <span className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-sm">
                  <span>{card.vehicle_count} vehicles</span>
                  <span>{card.point_count} points</span>
                </span>
                <span className="mt-2 block text-xs text-muted-foreground">
                  {dayRange(card.measured_date_min, card.measured_date_max, week.week === 0)}
                </span>
                {(!card.model || !card.color) && (
                  <span className="mt-2 block text-xs">Identity incomplete</span>
                )}
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function VehicleSummary({ vehicle }: { vehicle: Vehicle }) {
  // D-RO17-17: a same-day car with no serial is titled by its car label.
  const title = vehicle.identity_complete
    ? (vehicle.serial_no ?? vehicle.car_label)
    : "Identity incomplete";
  const car = carLine(vehicle, title ?? "");
  return (
    <>
      <span className="block break-all font-semibold">{title}</span>
      {car && <span className="block break-all text-xs">{car}</span>}
      {!vehicle.identity_complete && vehicle.serial_no && (
        <span className="block break-all text-xs">Serial: {vehicle.serial_no}</span>
      )}
      <span className="mt-2 block text-sm">
        {vehicle.point_count}{" "}
        {vehicle.expected_point_count == null
          ? "points; expected not available"
          : `of ${vehicle.expected_point_count} expected points`}
      </span>
      {vehicle.incomplete_set && (
        <span className="mt-1 block text-xs text-muted-foreground">Incomplete set</span>
      )}
      <span className="mt-2 block text-xs text-muted-foreground">
        {dayText(vehicle.measured_date, vehicle.date_is_month_only)} / Batch {vehicle.load_id}
      </span>
      <span className="mt-1 block break-all text-xs text-muted-foreground">
        Source file: {vehicle.source_file ?? "Not recorded"}
      </span>
      <span className="mt-1 block break-all text-xs text-muted-foreground">
        Source sheet: {vehicle.source_sheet ?? "Not recorded"}
      </span>
    </>
  );
}

function Pagination({
  page,
  setOffset,
}: {
  page: components["schemas"]["PageInfo"];
  setOffset: (offset: number) => void;
}) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3 text-xs">
      <Button
        variant="outline"
        size="sm"
        disabled={page.offset === 0}
        onClick={() => setOffset(Math.max(0, page.offset - page.limit))}
      >
        Previous
      </Button>
      <span>
        {page.returned} shown / {page.total} total
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page.offset + page.returned >= page.total || page.returned === 0}
        onClick={() => setOffset(page.offset + page.returned)}
      >
        Next
      </Button>
    </div>
  );
}

function HistoryVehicles({
  code,
  month,
  week,
  model,
  color,
  onOpen,
}: {
  code: string;
  month: string;
  week: number;
  model: string;
  color: string;
  onOpen: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const vehicles = useQuery(
    historyVehiclesOptions(code, { month, week, model, color, offset, limit: 50 }),
  );
  if (vehicles.isPending) return <LoadingState>Loading vehicle sets...</LoadingState>;
  if (vehicles.isError)
    return <ApiErrorState error={vehicles.error} retry={() => void vehicles.refetch()} />;
  return (
    <>
      <h4 className="mb-3 text-sm font-semibold">Vehicle sets</h4>
      {!vehicles.data.items.length && (
        <p className="text-sm text-muted-foreground">No active vehicle sets for this card</p>
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {vehicles.data.items.map((vehicle) => (
          <button
            type="button"
            key={vehicle.vehicle_id}
            onClick={() => onOpen(vehicle.vehicle_id)}
            className="min-w-0 rounded-lg border border-border p-4 text-left hover:border-primary focus-visible:outline-2 focus-visible:outline-primary"
          >
            <VehicleSummary vehicle={vehicle} />
          </button>
        ))}
      </div>
      <Pagination page={vehicles.data.page} setOffset={setOffset} />
    </>
  );
}

function HistoryPoints({
  code,
  vehicleId,
  canCorrect,
  onBack,
  onNotice,
}: {
  code: string;
  vehicleId: string;
  canCorrect: boolean;
  onBack: () => void;
  onNotice: (notice: string | Error) => void;
}) {
  const [offset, setOffset] = useState(0);
  const points = useQuery(historyVehiclePointsOptions(code, vehicleId, { limit: 50, offset }));
  return (
    <>
      <Button variant="ghost" size="sm" onClick={onBack} className="mb-4">
        Back to vehicle sets
      </Button>
      {points.isPending ? (
        <LoadingState>Loading vehicle points...</LoadingState>
      ) : points.isError ? (
        <ApiErrorState error={points.error} retry={() => void points.refetch()} />
      ) : (
        <>
          <div className="mb-5 rounded-lg border border-border bg-[var(--surface-2)] p-4">
            <VehicleSummary vehicle={points.data.vehicle} />
          </div>
          <h4 className="mb-3 text-sm font-semibold">Vehicle points</h4>
          {!points.data.items.length && (
            <p className="text-sm text-muted-foreground">No active points for this vehicle set</p>
          )}
          <div className="space-y-3">
            {points.data.items.map((point) => (
              <HistoryPoint
                key={point.measurement_id}
                point={point}
                plant={code}
                canCorrect={canCorrect}
                onNotice={onNotice}
              />
            ))}
          </div>
          <Pagination page={points.data.page} setOffset={setOffset} />
        </>
      )}
    </>
  );
}

function PointTag({ children }: { children: string }) {
  return (
    <span className="rounded-sm border border-border px-1 text-[0.7rem] text-muted-foreground">
      {children}
    </span>
  );
}

function HistoryPoint({
  point,
  plant,
  canCorrect,
  onNotice,
}: {
  point: components["schemas"]["HistoryPointOut"];
  plant: string;
  canCorrect: boolean;
  onNotice: (notice: string | Error) => void;
}) {
  const [editing, setEditing] = useState(false);
  const labelOf = usePointLabels(plant);
  return (
    <article
      data-measurement-id={point.measurement_id}
      className="min-w-0 rounded-lg border border-border p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          {/* D-RO17-16: the plant's label first; the code is the Catalogue zone line. */}
          <h5 className="font-semibold">{labelOf("wavescan", point.model, point.checkzone)}</h5>
          {/* T114 (D-114-3..5): Point Check's word on this point. Tags only --
              History keeps every reading whatever they say. */}
          {(point.retired || !point.counted || point.is_extra) && (
            <p
              className="mt-1 flex flex-wrap gap-1"
              data-testid={`history-point-tags-${point.measurement_id}`}
            >
              {point.retired && <PointTag>Retired point</PointTag>}
              {!point.retired && !point.counted && <PointTag>Not counted</PointTag>}
              {point.is_extra && <PointTag>Extra</PointTag>}
            </p>
          )}
          <p className="text-xs text-muted-foreground">Catalogue zone: {point.checkzone}</p>
          {point.src_zone_text && (
            <p className="text-xs text-muted-foreground">In the file: {point.src_zone_text}</p>
          )}
          <p className="text-xs text-muted-foreground">
            Measurement {point.measurement_id} /{" "}
            {dayText(point.measured_date, point.date_is_month_only)}
          </p>
        </div>
        {canCorrect && (
          <Button
            variant="outline"
            size="sm"
            aria-label={`Edit measurement ${point.measurement_id}`}
            onClick={() => setEditing(!editing)}
          >
            Edit
          </Button>
        )}
      </div>
      <dl className="my-4 grid grid-cols-3 gap-3 sm:grid-cols-6 xl:grid-cols-11">
        {(["cf", "lw", "sw", "doi", "du", "wa", "wb", "wc", "wd", "we", "b"] as const).map(
          (key) => (
            <div key={key} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{key.toUpperCase()}</dt>
              <dd className="num mt-1 break-all text-sm">
                {point[key] == null ? "Not recorded" : wavescanMeasure(point[key])}
              </dd>
            </div>
          ),
        )}
      </dl>
      <div className="space-y-1 break-all text-xs text-muted-foreground">
        <p>Source file: {point.source_file ?? "Not recorded"}</p>
        <p>Source sheet: {point.source_sheet}</p>
        <p>Source row: {point.source_row}</p>
        {point.corrects_measurement_id != null && (
          <p>
            Corrects measurement {point.corrects_measurement_id}: {point.correction_reason}
          </p>
        )}
      </div>
      {editing && canCorrect && (
        <MeasurementCorrection
          id={point.measurement_id}
          onClose={() => setEditing(false)}
          onNotice={onNotice}
        />
      )}
    </article>
  );
}
