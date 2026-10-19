"""FilmThickness reads: four GETs, any authenticated role (T48; T66 overview).

`/api/v1/plants/{plant_code}/filmthickness/...` is the film counterpart of
Measurement History. It is deliberately **not** `GET /measurements` and not
`/history/*`: those are WaveScan (CF, DOI, checkzone), and a PELT thickness
row in that list would be a silent wrong grain (T48 locked 1).

Everything here is a read of `filmthickness_active`. No mutation, no film
correction, no audit event, and no grade -- D1 is still open, so there is no
pass rate and no average of layers.

Plant visibility comes from the shared scope dependency (D3's single seam).
No SQL in this module (`00-ARCHITECTURE.md` section 5 rule 2).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from app.api.deps import ActiveScope, DbConnection
from app.api.v1.history import ColorQuery, Month, ModelQuery, OptionalMonth, PlantCode
from app.core.security import CurrentPrincipal
from app.schemas.common import ErrorResponse, PageInfo
from app.schemas.film_overview import FilmOverviewOut
from app.schemas.filmthickness import (
    FilmCardOut,
    FilmFacetsOut,
    FilmLayersOut,
    FilmPointGridOut,
    FilmPointOut,
    FilmSummariesOut,
    FilmVehicleOut,
    FilmVehiclePage,
    FilmWeekOut,
)
from app.schemas.history import VEHICLE_ID_PATTERN
from app.services import film_overview as overview_service
from app.services import filmthickness as service
from app.services.filmthickness import HistoryError

router = APIRouter(prefix="/plants", tags=["filmthickness"])

LogicalVehicleId = Annotated[
    str,
    Path(
        pattern=VEHICLE_ID_PATTERN,
        description=(
            "filmthickness.logical_vehicle_id (T46): 64-hex SHA-256 of "
            "'plant|measured_date|model|colour|identity'. Not the WaveScan "
            "History vehicle id: load_id is not inside it."
        ),
    ),
]

NOT_FOUND = {
    404: {
        "model": ErrorResponse,
        "description": (
            "No such plant, or no active FilmThickness facts for this vehicle "
            "at this plant."
        ),
    }
}


#: T108: one week band of `measured_date`, as WaveScan History's week is.
WeekQuery = Annotated[
    int | None,
    Query(
        ge=0,
        le=5,
        description=(
            "Week band 1..5 of measured_date (1 = days 1-7 ... 5 = 29 to the "
            "end of the month); 0 = day not recorded (RO18). Omit for the "
            "whole month."
        ),
    ),
]

ModelsQuery = Annotated[
    list[str] | None,
    Query(description="Repeatable ref_model.model_code. Omit for all."),
]
ColorsQuery = Annotated[
    list[str] | None,
    Query(
        description=(
            "Repeatable canonical (folded) colour name (ADR 0014). Omit for "
            "all. A merged old name matches no box."
        )
    ),
]


def _refused(exc: HistoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _vehicle_dto(found: dict, plant_code: str) -> FilmVehicleOut:
    return FilmVehicleOut(plant_code=plant_code, **found)


@router.get(
    "/{plant_code}/filmthickness/facets",
    response_model=FilmFacetsOut,
    responses=NOT_FOUND,
    summary="Months, then models, then colours with film facts. Any role.",
)
def film_facets(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    month: OptionalMonth = None,
    model: ModelQuery = None,
    color: ColorQuery = None,
) -> FilmFacetsOut:
    """Cascading pick lists for FilmThickness, as History's are for WaveScan.

    Only months that hold active film facts are listed. Without a `month` the
    model and colour lists are empty, and a `color` without a `month` is 422.
    A known plant with no film facts answers 200 with no months.
    """
    if color and not month:
        raise HTTPException(
            status_code=422,
            detail=(
                "color needs a month: the colour list cascades from the "
                "selected month (and model). Send month=YYYY-MM."
            ),
        )
    try:
        plant = service.resolve_plant(conn, plant_code)
        found = service.facets(
            conn, plant["plant_code"], plant_scope=scope.plant_scope,
            month=month, model=model, color=color,
        )
    except HistoryError as exc:
        raise _refused(exc) from exc
    return FilmFacetsOut(
        plant_code=plant["plant_code"],
        plant_is_active=bool(plant["is_active"]),
        **found,
    )


@router.get(
    "/{plant_code}/filmthickness/summaries",
    response_model=FilmSummariesOut,
    responses=NOT_FOUND,
    summary="Week, model and colour cards for one Film month. Any role.",
)
def film_summaries(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    month: Month,
    model: ModelQuery = None,
    color: ColorQuery = None,
) -> FilmSummariesOut:
    """T108 (D-108-1): Film History's week cards, as WaveScan History's are.

    Weeks descending, weeks with no matching cars omitted, one card per
    (week, model, colour). The week bands are the same rule as
    `/history/summaries` -- the same function, imported, not a second copy.

    A card's numbers are the numbers of the cars behind it: summing a
    month's `vehicle_count` gives what `.../filmthickness/vehicles` reports
    for the same plant, month, model and colour, and `box_count` /
    `no_box_count` / `incomplete_count` are those cars' own tag (T103) and
    flag (T99). `point_count` is active film **readings** -- one (car,
    point, layer) thickness -- not a count of points.

    There is no pass rate, no band and no average of layers here. D1 is open.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        weeks = service.summaries(
            conn, plant["plant_code"], plant_scope=scope.plant_scope,
            month=month, model=model, color=color,
        )
    except HistoryError as exc:
        raise _refused(exc) from exc
    return FilmSummariesOut(
        plant_code=plant["plant_code"],
        plant_is_active=bool(plant["is_active"]),
        month=month,
        model=model,
        color=color,
        weeks=[
            FilmWeekOut(
                week=week.week,
                measured_date_min=week.measured_date_min,
                measured_date_max=week.measured_date_max,
                cards=[
                    FilmCardOut(
                        model=card.model,
                        model_display_name=card.model_display_name,
                        color=card.color,
                        vehicle_count=card.vehicle_count,
                        point_count=card.point_count,
                        box_count=card.box_count,
                        no_box_count=card.no_box_count,
                        incomplete_count=card.incomplete_count,
                        measured_date_min=card.measured_date_min,
                        measured_date_max=card.measured_date_max,
                    )
                    for card in week.cards
                ],
            )
            for week in weeks
        ],
    )


@router.get(
    "/{plant_code}/filmthickness/vehicles",
    response_model=FilmVehiclePage,
    responses=NOT_FOUND,
    summary="Cars with film facts in one month. Any role.",
)
def film_vehicles(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    month: Month,
    week: WeekQuery = None,
    model: ModelQuery = None,
    color: ColorQuery = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FilmVehiclePage:
    """One item per `logical_vehicle_id`, newest measured day first.

    A Cab and a Box file of one car are **one** item with two `load_ids`;
    `mapped_point_count` is distinct gold points across both. Held labels
    (extra points, unmapped locations) were never facts and are not counted.

    T108: `week` narrows the month to one band of `measured_date`, which is
    what a week card of `.../filmthickness/summaries` was clicked on. It is
    optional, so the whole month is still one read; the band itself is the
    server's rule, never the client's arithmetic on a date.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        found, total = service.vehicles(
            conn, plant["plant_code"], plant_scope=scope.plant_scope,
            month=month, week=week, model=model, color=color,
            limit=limit, offset=offset,
        )
    except HistoryError as exc:
        raise _refused(exc) from exc
    return FilmVehiclePage(
        items=[_vehicle_dto(v, plant["plant_code"]) for v in found],
        page=PageInfo(limit=limit, offset=offset, total=total, returned=len(found)),
        plant_code=plant["plant_code"],
        plant_is_active=bool(plant["is_active"]),
        month=month,
        week=week,
        model=model,
        color=color,
    )


@router.get(
    "/{plant_code}/filmthickness/vehicles/{logical_vehicle_id}/points",
    response_model=FilmPointGridOut,
    responses=NOT_FOUND,
    summary="The model's whole gold catalogue for one car, Hor/Ver and 4 layers. Any role.",
)
def film_points(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    logical_vehicle_id: LogicalVehicleId,
) -> FilmPointGridOut:
    """Every catalogue point of the vehicle's model, in `point_no` order.

    P703 DBL Ranger / Raptor: 94 points, each `H` or `V` from the gold
    catalogue. RAPCAP / SGL: their own catalogue, `orientation` null. A
    point with no active fact has `src_location_text: null` and four null
    layers -- never a number. Not paginated: a catalogue is at most 94.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        found = service.points(
            conn, plant["plant_code"], logical_vehicle_id, plant_scope=scope.plant_scope,
        )
    except HistoryError as exc:
        raise _refused(exc) from exc
    return FilmPointGridOut(
        vehicle=_vehicle_dto(found["vehicle"], plant["plant_code"]),
        items=[
            FilmPointOut(**{**p, "layers": FilmLayersOut(**p["layers"])})
            for p in found["items"]
        ],
        plant_code=plant["plant_code"],
    )


@router.get(
    "/{plant_code}/filmthickness/overview",
    response_model=FilmOverviewOut,
    responses=NOT_FOUND,
    summary=(
        "Plant-month Film boxplots per layer x model x colour x H/V, with the "
        "latest spec lines. No status, no pass rate. Any role."
    ),
)
def film_overview(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    month: OptionalMonth = None,
    models: ModelsQuery = None,
    colors: ColorsQuery = None,
) -> FilmOverviewOut:
    """T66: every active Film car of the month, all four layers at once.

    Without `month` the latest Film month at the plant is used. An unknown
    month answers 200 with no boxes. Each box carries `lo` / `hi` / `target`
    from the latest `film_standard` rule (per colour, else plant-wide, else
    `NONE` with null lines); those lines apply to every month.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        found = overview_service.overview(
            conn, plant["plant_code"], plant_scope=scope.plant_scope,
            month=month, models=models, colors=colors,
        )
    except HistoryError as exc:
        raise _refused(exc) from exc
    return FilmOverviewOut(plant_code=plant["plant_code"], **found)
