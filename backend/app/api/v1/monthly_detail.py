"""Authenticated monthly profile and point reads; no mutations."""
from typing import Annotated
from fastapi import APIRouter, HTTPException, Query
from app.api.deps import ActiveScope, DbConnection
from app.api.v1.history import PlantCode
from app.core.security import CurrentPrincipal
from app.schemas.comparison import ComparisonMetric, ComparisonMonth
from app.schemas.monthly_detail import MonthlyProfilesOut, MonthlyPointsOut, MonthlyPointStatusesOut
from app.schemas.point_profiles import Domain
from app.services import monthly_detail as service, point_profiles
from app.services.history import HistoryError

router = APIRouter(prefix='/plants', tags=['monthly-detail'])


@router.get('/{plant_code}/monthly-detail/profiles', response_model=MonthlyProfilesOut,
            summary='Monthly model and colour profile cards from Standard and active sample identities.')
def profiles(principal: CurrentPrincipal, conn: DbConnection, scope: ActiveScope, plant_code: PlantCode,
             domain: Domain, month: ComparisonMonth | None = None):
    try:
        return service.profiles(conn, plant_code, plant_scope=scope.plant_scope, domain=domain, month=month)
    except HistoryError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get('/{plant_code}/monthly-detail/points', response_model=MonthlyPointsOut,
            summary='All samples at one exact Standard point, with backend box statistics and provenance.')
def points(principal: CurrentPrincipal, conn: DbConnection, scope: ActiveScope, plant_code: PlantCode,
           domain: Domain, month: ComparisonMonth, metric: ComparisonMetric,
           model: Annotated[str, Query(min_length=1, max_length=64)],
           color: Annotated[str, Query(min_length=1, max_length=128)],
           point_key: Annotated[str, Query(min_length=1, max_length=128)]):
    try:
        return service.points(conn, plant_code, plant_scope=scope.plant_scope, domain=domain,
                              month=month, model=model, color=color, metric=metric, point_key=point_key)
    except (HistoryError, point_profiles.PointProfileError) as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get('/{plant_code}/monthly-detail/point-statuses', response_model=MonthlyPointStatusesOut,
            summary='Monthly mean and current Standard status for every live inspection point.')
def point_statuses(principal: CurrentPrincipal, conn: DbConnection, scope: ActiveScope, plant_code: PlantCode,
                   domain: Domain, month: ComparisonMonth, metric: ComparisonMetric,
                   model: Annotated[str, Query(min_length=1, max_length=64)],
                   color: Annotated[str, Query(min_length=1, max_length=128)]):
    try:
        return service.point_statuses(conn, plant_code, plant_scope=scope.plant_scope, domain=domain,
                                      month=month, model=model, color=color, metric=metric)
    except (HistoryError, point_profiles.PointProfileError) as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
