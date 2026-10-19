"""Analysis & Report, first version (AR03). Read only, any role. No SQL here."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActiveScope, DbConnection
from app.api.v1.history import OptionalMonth, PlantCode
from app.core.security import CurrentPrincipal
from app.schemas.common import ErrorResponse
from app.schemas.report import AnalysisReportOut, Domain
from app.services import report as service
from app.services.history import HistoryError
from app.services.overview import OverviewError

router = APIRouter(tags=["analysis"])


@router.get(
    "/plants/{plant_code}/analysis/report",
    response_model=AnalysisReportOut,
    responses={404: {"model": ErrorResponse, "description": "No such plant."}},
    summary="One plant month: glance, non-Pass boxes, month comparison, bands, "
    "relationships and a template summary. Statuses are the overviews'. Any role.",
)
def analysis_report(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    month: OptionalMonth = None,
    domain: Domain = "both",
    models: Annotated[list[str] | None, Query(description="Repeatable exact model_code. Omit for all.")] = None,
    colors: Annotated[list[str] | None, Query(description="Repeatable exact colour name. Omit for all.")] = None,
) -> AnalysisReportOut:
    """AR03. Counts and statistics with n; no rate, share or new status."""
    try:
        return AnalysisReportOut(**service.read(
            conn, plant_code, plant_scope=scope.plant_scope, month=month,
            domain=domain, models=models, colors=colors,
        ))
    except (HistoryError, OverviewError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
