"""Read-only authenticated IMG family summary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActiveScope, DbConnection
from app.core.security import CurrentPrincipal
from app.domain.history import month_date_bounds
from app.repositories.img_overview import PLANTS
from app.schemas.history import MONTH_PATTERN
from app.schemas.img_overview import FilmMeasure, ImgColorsOut, ImgMonthsOut, ImgOverviewOut
from app.services import img_overview as service

router = APIRouter(prefix="/img/overview", tags=["img-overview"])
colors_router = APIRouter(prefix="/img/colors", tags=["img-overview"])


def _in_scope(scope):
    return [p for p in PLANTS if scope.plant_scope is None or p in scope.plant_scope]


@router.get("/months", response_model=ImgMonthsOut)
def img_months(principal: CurrentPrincipal, conn: DbConnection, scope: ActiveScope) -> ImgMonthsOut:
    return ImgMonthsOut(months=service.months(conn, scope.plant_scope), plants=_in_scope(scope))


@router.get("", response_model=ImgOverviewOut)
def img_overview(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    month: Annotated[str, Query(pattern=MONTH_PATTERN, description="Measured month YYYY-MM")],
    film_measure: FilmMeasure = "CALCULATED_TOTAL",
) -> ImgOverviewOut:
    try:
        month_date_bounds(month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImgOverviewOut(month=month, film_measure=film_measure,
                          plants=_in_scope(scope),
                          series=service.overview(conn, scope.plant_scope, month, film_measure))


@colors_router.get("", response_model=ImgColorsOut,
                   summary="IMG Color: average CF per plant x colour, ranked.")
def img_colors(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    month: Annotated[str, Query(pattern=MONTH_PATTERN, description="Measured month YYYY-MM")],
) -> ImgColorsOut:
    try:
        month_date_bounds(month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImgColorsOut(month=month, plants=_in_scope(scope),
                        series=service.colors(conn, scope.plant_scope, month))
