"""Plant WaveScan Monthly Overview. Any authenticated role. Read only.

No SQL in this module. Status comes from the overview service calling
the domain rule; this router does not load that module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from app.api.deps import ActiveScope, DbConnection
from app.core.security import CurrentPrincipal
from app.schemas.common import ErrorResponse
from app.schemas.history import MONTH_PATTERN
from app.schemas.overview import WavescanOverviewOut
from app.services import overview as service
from app.services.overview import OverviewError

router = APIRouter(prefix="/plants", tags=["overview"])

PlantCode = Annotated[
    str,
    Path(
        min_length=1,
        max_length=32,
        description=(
            "ref_plant.plant_code or any approved ref_plant_alias, in any "
            "case: /plants/ftm and /plants/FTM are one plant."
        ),
        examples=["FTM"],
    ),
]
Month = Annotated[
    str,
    Query(
        pattern=MONTH_PATTERN,
        description=(
            "Calendar month of measured_date, YYYY-MM. Not the upload month."
        ),
        examples=["2026-09"],
    ),
]
ModelQuery = Annotated[
    list[str] | None,
    Query(description="Repeatable ref_model.model_code. Omit for all."),
]
ColorQuery = Annotated[
    list[str] | None,
    Query(description="Repeatable ref_color.color_name. Omit for all."),
]

NOT_FOUND = {
    404: {
        "model": ErrorResponse,
        "description": "No such plant.",
    }
}


def _refused(exc: OverviewError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get(
    "/{plant_code}/wavescan/overview",
    response_model=WavescanOverviewOut,
    responses=NOT_FOUND,
    summary=(
        "Plant-month CF boxplots: full-population quartiles, exact mean, "
        "and stored Standard/Minimum status. Not a pass rate."
    ),
)
def wavescan_overview(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    month: Month,
    model: ModelQuery = None,
    color: ColorQuery = None,
) -> WavescanOverviewOut:
    try:
        plant = service.resolve_plant(conn, plant_code)
        found = service.overview(
            conn,
            plant["plant_code"],
            plant_scope=scope.plant_scope,
            month=month,
            models=model,
            colors=color,
        )
    except OverviewError as exc:
        raise _refused(exc) from exc
    return WavescanOverviewOut(
        plant_code=plant["plant_code"],
        plant_is_active=bool(plant["is_active"]),
        month=found["month"],
        models=found["models"],
        colors=found["colors"],
        available_months=found["available_months"],
        model_options=found["model_options"],
        color_options=found["color_options"],
        boxes=found["boxes"],
    )
