import { useQuery } from "@tanstack/react-query";
import { filmSummariesOptions, filmVehiclePointsOptions, filmVehiclesOptions } from "@/api/queries";
import type { components } from "@/api/types";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { FilmBoxTag } from "./FilmBoxTag";
import { FILM_LAYERS } from "./film-overview-display";
import { usePointLabels } from "@/features/measurements/point-labels";
import { dayRange, dayText, weekText } from "@/features/measurements/day-text";

type Point = components["schemas"]["FilmPointOut"];
type Card = components["schemas"]["FilmCardOut"];

/** T108 (D-108-2): which week card is open. `null` is "back to the cards". */
export type FilmCardKey = { week: number; model: string; color: string };

function PointSection({
  name,
  points,
  labelOf,
}: {
  name: string;
  points: Point[];
  labelOf: (code: string) => string;
}) {
  return (
    <section aria-label={`${name} points`} className="min-w-0">
      <h4 className="mb-2 text-sm font-semibold">
        {name} ({points.length})
      </h4>
      {points.length === 0 ? (
        <p className="text-xs text-muted-foreground">No catalogue points in this section.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full min-w-[570px] text-left text-xs">
            <thead className="bg-[var(--surface-2)] text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2">
                  Point
                </th>
                <th scope="col" className="px-3 py-2">
                  In the file
                </th>
                {FILM_LAYERS.map((layer) => (
                  <th key={layer.code} scope="col" className="px-3 py-2">
                    {layer.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {points.map((point) => (
                <tr
                  key={point.point_code}
                  className="border-t border-border"
                  data-point-retired={point.retired ? "true" : undefined}
                  data-point-extra={point.is_extra ? "true" : undefined}
                >
                  <th scope="row" className="px-3 py-2 font-mono font-medium">
                    {/* D-RO17-16: the plant's label first, the code beside it. */}
                    {labelOf(point.point_code)}
                    {labelOf(point.point_code) !== point.point_code && (
                      <span className="ml-2 font-normal text-muted-foreground">
                        code {point.point_code}
                      </span>
                    )}
                    {/* T100 (Part D): a point the setting says does not count
                        keeps its readings and its H/V group and says so. The
                        dashboard already leaves it out server-side. */}
                    {point.counted === false && (
                      <span
                        data-testid={`not-counted-${point.point_code}`}
                        className="ml-2 font-sans text-[0.7rem] font-normal text-muted-foreground"
                      >
                        Not counted
                      </span>
                    )}
                    {/* T109 (D-109-3): beyond the plant's standard list for
                        the model. A tag on the point, not on the reading. */}
                    {point.is_extra && (
                      <span
                        data-testid={`point-extra-${point.point_code}`}
                        className="ml-2 rounded-sm border border-border px-1 font-sans text-[0.7rem] font-normal text-muted-foreground"
                      >
                        Extra
                      </span>
                    )}
                    {/* T109 (D-109-4): this point is off the plant's walk and
                        off the dashboard, and it is in this grid because this
                        car was measured at it. The reading is kept. */}
                    {point.retired && (
                      <span
                        data-testid={`point-retired-${point.point_code}`}
                        title="Off the walk and off the dashboard. This car's reading is kept."
                        className="ml-2 rounded-sm border border-border px-1 font-sans text-[0.7rem] font-normal text-muted-foreground"
                      >
                        Retired point
                      </span>
                    )}
                  </th>
                  <td className="px-3 py-2 font-mono text-muted-foreground">
                    {point.src_location_text ?? "-"}
                  </td>
                  {(["ecoat", "primer", "base", "clear"] as const).map((layer) => (
                    <td key={layer} className="px-3 py-2 font-mono">
                      {point.layers[layer] ?? "Not measured"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * T108 (D-108-2): Film History walks Week -> model/colour card -> cars ->
 * one car's points, the way WaveScan History does, with Back at each level.
 *
 * Every number on every level is an API field (D-108-4): the week bands, the
 * card counts, the Box / No box tag (T103) and the incomplete flag (T99) all
 * come from the server. Nothing here groups a date, counts a car or decides
 * what a walk was.
 *
 * The open card is the caller's URL state, so opening one never writes a
 * filter (T105's rule, D-108-3).
 */
export function FilmThickness({
  code,
  month,
  model,
  color,
  week,
  cardModel,
  cardColor,
  vehicleId,
  onCard,
  onVehicle,
  context = "overview",
}: {
  code: string;
  month: string | undefined;
  model: string | undefined;
  color: string | undefined;
  week: number | undefined;
  cardModel: string | undefined;
  cardColor: string | undefined;
  vehicleId: string | undefined;
  onCard: (card: FilmCardKey | null) => void;
  onVehicle: (id: string | undefined) => void;
  context?: "overview" | "history";
}) {
  const open =
    month && week !== undefined && cardModel && cardColor
      ? { week, model: cardModel, color: cardColor }
      : null;
  return (
    <section
      className={
        context === "history" ? "min-w-0 border-t border-border pt-5" : "panel min-w-0 p-5"
      }
      aria-label="Film Thickness"
    >
      <p className="eyebrow mb-1">
        {context === "history" ? "Measurement History" : "Paint Functional"}
      </p>
      {context === "history" ? (
        <h3 className="mb-1 text-lg font-bold">Film Thickness</h3>
      ) : (
        <h2 className="mb-1 text-xl font-bold">Film Thickness</h2>
      )}
      <p className="mb-5 text-xs text-muted-foreground">
        Active vehicle measurements by gold catalogue point. Blank layers were not measured.
      </p>
      {!month ? (
        <p>No Film Thickness measurements for this plant.</p>
      ) : open ? (
        <div key={`${month}/${open.week}/${open.model}/${open.color}`}>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <Button variant="outline" size="sm" onClick={() => onCard(null)}>
              Back to week cards
            </Button>
            <h4 className="text-sm font-semibold">
              {weekText(open.week)} / {open.model} / {open.color}
            </h4>
          </div>
          {vehicleId ? (
            <FilmPoints
              key={vehicleId}
              code={code}
              vehicleId={vehicleId}
              onBack={() => onVehicle(undefined)}
            />
          ) : (
            <FilmCars
              code={code}
              month={month}
              week={open.week}
              model={open.model}
              color={open.color}
              onOpen={onVehicle}
            />
          )}
        </div>
      ) : (
        <FilmWeeks code={code} month={month} model={model} color={color} onCard={onCard} />
      )}
    </section>
  );
}

function FilmWeeks({
  code,
  month,
  model,
  color,
  onCard,
}: {
  code: string;
  month: string;
  model: string | undefined;
  color: string | undefined;
  onCard: (card: FilmCardKey) => void;
}) {
  const summaries = useQuery(filmSummariesOptions(code, { month, model, color }));
  if (summaries.isPending) return <LoadingState>Loading Film week cards...</LoadingState>;
  if (summaries.isError)
    return <ApiErrorState error={summaries.error} retry={() => void summaries.refetch()} />;
  if (!summaries.data.weeks.length)
    return <p className="text-sm">No Film Thickness vehicles for this selection.</p>;
  return (
    <div className="space-y-6">
      {summaries.data.weeks.map((item) => (
        <section key={item.week} aria-label={`Film ${weekText(item.week).toLowerCase()}`}>
          <h4 className="mb-3 border-b border-border pb-2 text-sm font-semibold">
            {weekText(item.week)}
          </h4>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {item.cards.map((card) => (
              <FilmCardButton
                key={`${card.model}/${card.color}`}
                card={card}
                monthOnly={item.week === 0}
                onOpen={() => onCard({ week: item.week, model: card.model, color: card.color })}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export function FilmCardButton({
  card,
  onOpen,
  monthOnly,
}: {
  card: Card;
  onOpen: () => void;
  /** RO18: a week-0 card's cars have no day. */
  monthOnly?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="min-w-0 rounded-lg border border-border bg-[var(--surface-2)] p-4 text-left transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-primary"
    >
      <span className="mb-2 inline-block rounded-sm border border-border px-2 py-0.5 text-[10px] font-semibold">
        Film Thickness
      </span>
      <span className="block break-words text-base font-semibold">
        {card.model_display_name ?? card.model} / {card.color}
      </span>
      <span className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <span>{card.vehicle_count} cars</span>
        <span>{card.point_count} readings</span>
      </span>
      {/* T108 (D-108-1 / D-108-4): the server's counts of its own tags. A
          card never adds one up from the cars it has not fetched. */}
      <span className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {/* RO13 (F7): a plant whose list names no complete stop tags no car either way. */}
        {card.box_count + card.no_box_count > 0 && (
          <>
            <span>Box {card.box_count}</span>
            <span>No box {card.no_box_count}</span>
          </>
        )}
        <span>Incomplete {card.incomplete_count}</span>
      </span>
      <span className="mt-2 block text-xs text-muted-foreground">
        {dayRange(card.measured_date_min, card.measured_date_max, monthOnly)}
      </span>
    </button>
  );
}

function FilmCars({
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
  const vehicles = useQuery(filmVehiclesOptions(code, { month, week, model, color }));
  if (vehicles.isPending) return <LoadingState>Loading Film Thickness vehicles...</LoadingState>;
  if (vehicles.isError)
    return <ApiErrorState error={vehicles.error} retry={() => void vehicles.refetch()} />;
  return (
    <>
      <h4 className="mb-2 text-sm font-semibold">Vehicles ({vehicles.data.items.length})</h4>
      {vehicles.data.items.length === 0 && (
        <p className="text-sm text-muted-foreground">No Film Thickness vehicles for this card.</p>
      )}
      <div className="mb-6 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {vehicles.data.items.map((vehicle) => (
          <button
            key={vehicle.logical_vehicle_id}
            type="button"
            onClick={() => onOpen(vehicle.logical_vehicle_id)}
            className="rounded-md border border-border p-3 text-left text-xs transition-colors hover:bg-[var(--surface-2)] hover:border-primary focus-visible:outline-2 focus-visible:outline-primary"
          >
            <span className="mb-1 inline-block rounded-sm border border-border px-2 py-0.5 text-[10px] font-semibold">
              Film Thickness
            </span>
            <span className="block font-semibold">
              {vehicle.job_nos.length
                ? `Job ${vehicle.job_nos.join(", ")}`
                : (vehicle.serial_no ?? "Unidentified vehicle")}
            </span>
            <span className="mt-1 block">
              {dayText(vehicle.measured_date, vehicle.date_is_month_only)} |{" "}
              {vehicle.model_display_name ?? vehicle.model} | {vehicle.color}
            </span>
            <span className="mt-1 flex flex-wrap items-center gap-2 text-muted-foreground">
              <span>
                Mapped points: {vehicle.mapped_point_count} /{" "}
                {vehicle.expected_point_count ?? "unknown"}
                {vehicle.incomplete ? " | Incomplete" : ""}
              </span>
              {/* T103 (D-103-3): the server's Box / No box tag, beside the
                  count it belongs with. Null renders nothing. */}
              <FilmBoxTag box={vehicle.box} label="Walk" />
            </span>
            {/* T103 (D-103-6): the warning this car's rows carried when
                they loaded, kept where somebody can find it. */}
            {vehicle.identity_note && (
              <span className="mt-1 block text-muted-foreground">{vehicle.identity_note}</span>
            )}
            <span className="mt-1 block break-all text-muted-foreground">
              Load IDs: {vehicle.load_ids.join(", ") || "-"}
            </span>
            <span className="mt-1 block break-all font-mono text-muted-foreground">
              {vehicle.logical_vehicle_id}
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

function FilmPoints({
  code,
  vehicleId,
  onBack,
}: {
  code: string;
  vehicleId: string;
  onBack: () => void;
}) {
  const points = useQuery(filmVehiclePointsOptions(code, vehicleId));
  const labels = usePointLabels(code);
  const labelOf = (point: string) => labels("film", points.data?.vehicle.model, point);
  return (
    <>
      <Button variant="ghost" size="sm" onClick={onBack} className="mb-4">
        Back to vehicles
      </Button>
      {points.isPending ? (
        <LoadingState>Loading catalogue points...</LoadingState>
      ) : points.isError ? (
        <ApiErrorState error={points.error} retry={() => void points.refetch()} />
      ) : (
        <div className="space-y-6">
          <div className="space-y-1">
            <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold">
              <span>Catalogue points ({points.data.items.length})</span>
              <FilmBoxTag box={points.data.vehicle.box} label="Walk" />
            </h3>
            <p className="text-xs text-muted-foreground">
              {points.data.vehicle.job_nos.length
                ? `Job ${points.data.vehicle.job_nos.join(", ")}`
                : (points.data.vehicle.serial_no ?? "Unidentified vehicle")}{" "}
              | {dayText(points.data.vehicle.measured_date, points.data.vehicle.date_is_month_only)}{" "}
              | {points.data.vehicle.model_display_name ?? points.data.vehicle.model} |{" "}
              {points.data.vehicle.color}
            </p>
            <p className="text-xs text-muted-foreground">
              Mapped points: {points.data.vehicle.mapped_point_count} /{" "}
              {points.data.vehicle.expected_point_count ?? "unknown"}
              {points.data.vehicle.incomplete ? " | Incomplete" : ""}
            </p>
            {points.data.vehicle.identity_note && (
              <p className="text-xs text-muted-foreground">{points.data.vehicle.identity_note}</p>
            )}
          </div>
          <PointSection
            name="Horizontal"
            labelOf={labelOf}
            points={points.data.items.filter((point) => point.orientation === "H")}
          />
          <PointSection
            name="Vertical"
            labelOf={labelOf}
            points={points.data.items.filter((point) => point.orientation === "V")}
          />
          <PointSection
            name="Unassigned"
            labelOf={labelOf}
            points={points.data.items.filter((point) => point.orientation === null)}
          />
        </div>
      )}
    </>
  );
}
