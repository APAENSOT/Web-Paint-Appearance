"""Measurement History: four reads, any authenticated role.

`/api/v1/plants/{plant_code}/history/...` is the contract Measurement
History is built against (design F13-F15, section 8). It is deliberately
**not** under `/workbooks`: those routes are the Admin Data Manager and show
proposals, pending sheets and retired ones. These show **active facts** --
what `GET /measurements` already calls current -- so a Viewer and an Engineer
read them (200), exactly as they read the measurement list, while the
workbook manager stays Admin (`03-SECURITY.md` section 5).

Everything here is a read. No mutation, no audit event, no workbook opened,
and no grade: editing a point is the existing T09 correction POST against
its `measurement_id`, and D1 is still open.

Plant visibility comes from the shared scope dependency, which is D3's
single seam (`core/scoping.py`); this module does not decide it.

No SQL in this module (`00-ARCHITECTURE.md` section 5 rule 2).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from app.api.deps import ActiveScope, DbConnection
from app.core.security import CurrentPrincipal
from app.domain import history as rules
from app.schemas.common import ErrorResponse, PageInfo
from app.schemas.history import (
    MONTH_PATTERN,
    VEHICLE_ID_PATTERN,
    HistoryCardOut,
    HistoryFacetsOut,
    HistoryPointOut,
    HistoryPointPage,
    HistorySummariesOut,
    HistoryVehiclePage,
    HistoryVehicleSetOut,
    HistoryWeekOut,
)
from app.services import history as service
from app.services.history import HistoryError

router = APIRouter(prefix="/plants", tags=["history"])

PlantCode = Annotated[
    str,
    Path(
        min_length=1,
        max_length=32,
        description=(
            "ref_plant.plant_code or any approved ref_plant_alias, in any "
            "case: /plants/ftm and /plants/FTM are one plant."
        ),
        examples=["AAT"],
    ),
]
VehicleId = Annotated[
    str,
    Path(
        pattern=VEHICLE_ID_PATTERN,
        description=(
            "The T21 vehicle id: SHA-256 of "
            "'{load_id}|{measured_date}|{model}|{color}|{serial_no}'."
        ),
    ),
]
Month = Annotated[
    str,
    Query(
        pattern=MONTH_PATTERN,
        description=(
            "Calendar month of measured_date, YYYY-MM. Not the upload month: "
            "a June workbook uploaded in September is June data."
        ),
        examples=["2026-07"],
    ),
]
OptionalMonth = Annotated[str | None, Query(pattern=MONTH_PATTERN, examples=["2026-07"])]
ModelQuery = Annotated[str | None, Query(max_length=64, description="ref_model.model_code")]
ColorQuery = Annotated[str | None, Query(max_length=64, description="ref_color.color_name")]

NOT_FOUND = {
    404: {
        "model": ErrorResponse,
        "description": (
            "No such plant, or no such active vehicle set at this plant. A "
            "set that never committed, or whose batch has been retired, is "
            "not readable here."
        ),
    }
}


def _refused(exc: HistoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _vehicle_dto(found: rules.HistoryVehicle, plant_code: str) -> HistoryVehicleSetOut:
    return HistoryVehicleSetOut(
        vehicle_id=found.vehicle_id,
        load_id=found.load_id,
        plant_code=plant_code,
        measured_date=found.measured_date,
        model=found.model,
        color=found.color,
        serial_no=found.serial_no,
        identity_complete=found.identity_complete,
        point_count=found.point_count,
        expected_point_count=found.expected_point_count,
        incomplete_set=found.incomplete_set,
        source_file=found.source_file,
        source_sheet=found.source_sheet,
        week=found.week,
        car_label=found.car_label,
        date_is_month_only=found.date_is_month_only,
    )


@router.get(
    "/{plant_code}/history/facets",
    response_model=HistoryFacetsOut,
    responses=NOT_FOUND,
    summary="Months, then models, then colours with active data. Any role.",
)
def history_facets(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    month: OptionalMonth = None,
    model: ModelQuery = None,
    color: ColorQuery = None,
) -> HistoryFacetsOut:
    """The cascading pick lists, as API fields (design F14).

    The client must not download every active row to build them. Without a
    `month` the model and colour lists are empty: there is nothing to cascade
    from yet, and a `color` without a `month` is a 422 for the same reason.

    A plant this platform knows but has not onboarded (FVL, D5) answers 200
    with no months and `plant_is_active: false`, not the upload route's 422.
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
            conn,
            plant["plant_code"],
            plant_scope=scope.plant_scope,
            month=month,
            model=model,
            color=color,
        )
    except HistoryError as exc:
        raise _refused(exc) from exc
    return HistoryFacetsOut(
        plant_code=plant["plant_code"],
        plant_is_active=bool(plant["is_active"]),
        **found,
    )


@router.get(
    "/{plant_code}/history/summaries",
    response_model=HistorySummariesOut,
    responses=NOT_FOUND,
    summary="Week, model and colour cards for one month. Any role.",
)
def history_summaries(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    month: Month,
    model: ModelQuery = None,
    color: ColorQuery = None,
) -> HistorySummariesOut:
    """Weeks descending, weeks with no matching rows omitted.

    A card's `point_count` is active measurement rows, so summing a month's
    cards gives what `GET /measurements` reports for the same plant, month,
    model and colour. `vehicle_count` counts vehicle sets. There is no pass
    rate, no Ford band and no expected-32 here; the expected count belongs to
    a vehicle, not to a card.

    `week` is a **field**, not a resource: T21's Upload Data weeks stay the
    client's, computed from `uploaded_at`.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        weeks = service.summaries(
            conn,
            plant["plant_code"],
            plant_scope=scope.plant_scope,
            month=month,
            model=model,
            color=color,
        )
    except HistoryError as exc:
        raise _refused(exc) from exc
    return HistorySummariesOut(
        plant_code=plant["plant_code"],
        plant_is_active=bool(plant["is_active"]),
        month=month,
        model=model,
        color=color,
        weeks=[
            HistoryWeekOut(
                week=week.week,
                measured_date_min=week.measured_date_min,
                measured_date_max=week.measured_date_max,
                cards=[
                    HistoryCardOut(
                        model=card.model,
                        color=card.color,
                        vehicle_count=card.vehicle_count,
                        point_count=card.point_count,
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
    "/{plant_code}/history/vehicles",
    response_model=HistoryVehiclePage,
    responses=NOT_FOUND,
    summary="Vehicle sets behind one week, model and colour card. Any role.",
)
def history_vehicles(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    month: Month,
    week: Annotated[int, Query(ge=0, le=5, description="Week band 1..5 of measured_date; 0 = day not recorded (RO18).")],
    model: Annotated[str, Query(min_length=1, max_length=64)],
    color: Annotated[str, Query(min_length=1, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HistoryVehiclePage:
    """The card click. `model` and `color` are required: this is one card.

    Two serials are two sets, and two sheets that measured the same serial on
    the same day are two sets -- `load_id` is inside the id. A set whose
    serial is blank is `identity_complete: false`; no serial is generated.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        found, total = service.vehicles(
            conn,
            plant["plant_code"],
            plant_scope=scope.plant_scope,
            month=month,
            week=week,
            model=model,
            color=color,
            limit=limit,
            offset=offset,
        )
    except HistoryError as exc:
        raise _refused(exc) from exc
    return HistoryVehiclePage(
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
    "/{plant_code}/history/vehicles/{vehicle_id}/points",
    response_model=HistoryPointPage,
    responses=NOT_FOUND,
    summary="Active measurements of one vehicle set. Any role.",
)
def history_points(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    vehicle_id: VehicleId,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HistoryPointPage:
    """One row per checkzone, ordered by checkzone then source row.

    Each point carries its `measurement_id`, because the edit on this screen
    is the existing `POST /api/v1/measurements/{measurement_id}/corrections`
    -- never the T21 review override, which belongs to rows that have not
    been committed.

    The parent set rides along so a client can show "N of expected" without
    computing anything.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        found = service.points(
            conn,
            plant["plant_code"],
            vehicle_id,
            plant_scope=scope.plant_scope,
            limit=limit,
            offset=offset,
        )
    except HistoryError as exc:
        raise _refused(exc) from exc
    return HistoryPointPage(
        items=[HistoryPointOut(**row) for row in found["items"]],
        page=PageInfo(
            limit=limit, offset=offset, total=found["total"], returned=len(found["items"])
        ),
        vehicle=_vehicle_dto(found["vehicle"], plant["plant_code"]),
        plant_code=plant["plant_code"],
    )
