from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbConnection, Filters
from app.core.security import CurrentPrincipal
from app.repositories import measurements as repo
from app.schemas.dashboard import (
    DashboardPreview,
    PreviewDimension,
    PreviewPoint,
    PreviewSeries,
)
from app.schemas.measurements import MeasurementFilters

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

MAX_POINTS = 20_000


@router.get(
    "/preview",
    response_model=DashboardPreview,
    summary="Raw CF values grouped for plotting. No grade, no pass rate (D1 open).",
)
def preview(
    principal: CurrentPrincipal,
    conn: DbConnection,
    filters: Filters,
    dimension: Annotated[
        PreviewDimension,
        Query(description="How to group the points for display. Not a grading key."),
    ] = "checkzone",
    point_limit: Annotated[int, Query(ge=1, le=MAX_POINTS)] = 5000,
) -> DashboardPreview:
    # One extra row is fetched purely to answer "was this truncated?" without
    # a second COUNT over the same predicate.
    rows = repo.preview_points(conn, filters, dimension=dimension, limit=point_limit + 1)
    truncated = len(rows) > point_limit
    rows = rows[:point_limit]

    series: dict[str, list[PreviewPoint]] = {}
    for row in rows:
        key = row.pop("series_key")
        series.setdefault(key, []).append(PreviewPoint(**row))

    return DashboardPreview(
        dimension=dimension,
        series=[PreviewSeries(key=k, points=v) for k, v in series.items()],
        filters=MeasurementFilters(
            plant=filters.plant,
            model=filters.model,
            color=filters.color,
            checkzone=filters.checkzone,
            date_from=filters.date_from,
            date_to=filters.date_to,
        ),
        point_limit=point_limit,
        truncated=truncated,
    )
