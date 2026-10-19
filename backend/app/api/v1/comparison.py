"""Read-only T79/T81 Comparison endpoints; same auth and scope as History."""
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import StringConstraints

from app.api.deps import ActiveScope, DbConnection
from app.api.v1.history import PlantCode
from app.core.security import CurrentPrincipal
from app.schemas.common import ErrorResponse
from app.schemas.comparison import ComparisonDomain, ComparisonMetric, ComparisonPointsOut, ComparisonVehiclesOut
from app.schemas.comparison import ComparisonMonthlyPreviewIn, ComparisonMonthlyPreviewOut, ComparisonVehicleVisualsOut, MONTHLY_REQUEST_EXAMPLES, MONTHLY_RESPONSE_EXAMPLES
from app.schemas.history import MONTH_PATTERN, VEHICLE_ID_PATTERN
from app.services import comparison as service
from app.services.history import HistoryError

router = APIRouter(prefix="/plants", tags=["comparison"])
Domain = Annotated[ComparisonDomain, Query(description="Required single domain: WAVESCAN or FILMTHICKNESS; metrics and vehicle IDs never cross domains.")]
MonthToken = Annotated[str, StringConstraints(pattern=MONTH_PATTERN)]
IdToken = Annotated[str, StringConstraints(pattern=VEHICLE_ID_PATTERN)]
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Unknown plant or any ID absent from active facts for this plant/domain/model. No silent omission."}}


@router.get("/{plant_code}/comparison/vehicles", response_model=ComparisonVehiclesOut, responses=NOT_FOUND,
            summary="Comparison vehicle picker across measured months and weeks. Any History reader.")
def comparison_vehicles(
    principal: CurrentPrincipal, conn: DbConnection, scope: ActiveScope, plant_code: PlantCode, domain: Domain,
    month: Annotated[list[MonthToken] | None, Query(description="Repeatable measured YYYY-MM months, not upload months. Omit for latest active domain month; no data yields empty options/items. Effective months echoed as selected_months.")] = None,
    model: Annotated[str | None, Query(min_length=1, max_length=64, description="One model code offered in at least one effective month, else 422. A known empty/inactive plant returns empty 200. Until selected only model options are returned, items=[], color_options=[], week_options=[].")] = None,
    color: Annotated[list[str] | None, Query(description="Repeatable exact active paint colour names; omit for all. Options ignore this filter.")] = None,
    period: Annotated[list[str] | None, Query(description="Repeatable YYYY-MM-Wn, n=1..5, in an effective month. Malformed/out-of-scope is 422. Existing History bands: 1-7, 8-14, 15-21, 22-28, 29-end for both domains. Omit for every week; options ignore this filter.")] = None,
    q: Annotated[str | None, Query(description="Trimmed case-insensitive substring of serial_no and Film job_nos only; empty means no search. Hidden IDs are not searched; options ignore search.")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Candidate page size 1..100; total is before pagination.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Zero-based candidate offset in measured_date DESC, identity ASC null last, vehicle_id ASC order.")] = 0,
) -> ComparisonVehiclesOut:
    try:
        return ComparisonVehiclesOut(**service.vehicles(conn, plant_code, plant_scope=scope.plant_scope,
            domain=domain, months=month, model=model, colors=color, periods=period, q=q, limit=limit, offset=offset))
    except HistoryError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/{plant_code}/comparison/points", response_model=ComparisonPointsOut, responses=NOT_FOUND,
            summary="Align one raw metric to the full live plant/model catalogue. Any History reader.")
def comparison_points(
    principal: CurrentPrincipal, conn: DbConnection, scope: ActiveScope, plant_code: PlantCode, domain: Domain,
    model: Annotated[str, Query(min_length=1, max_length=64, description="Required one model code. Any requested ID with another model, plant or domain returns 404.")],
    metric: Annotated[ComparisonMetric, Query(description="Required raw metric. WaveScan: lw, sw, cf, doi, du, wa, wb, wc, wd, we, b; Film: ecoat, primer, base, clear. Wrong domain is 422. Exact decimal strings, no calculated values.")],
    vehicle_id: Annotated[list[IdToken], Query(min_length=1, max_length=8, description="Required repeatable 1..8 distinct domain vehicle IDs, preserved in caller order. Duplicates/ninth ID are 422. WaveScan History ID includes load_id; Film logical_vehicle_id spans loads. Any absent/wrong plant/model/domain ID is 404, never silently omitted.")],
) -> ComparisonPointsOut:
    try:
        return ComparisonPointsOut(**service.points(conn, plant_code, plant_scope=scope.plant_scope,
            domain=domain, model=model, metric=metric, vehicle_ids=vehicle_id))
    except HistoryError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc




@router.post('/{plant_code}/comparison/monthly-preview', response_model=ComparisonMonthlyPreviewOut,
             responses={**NOT_FOUND, 200: {'content': {'application/json': {'examples': MONTHLY_RESPONSE_EXAMPLES}}}}, summary='Temporary monthly Comparison calculation; read only, any History reader.',
             description='Reads v_wavescan_active or filmthickness_active. Reuses individual Overview boxes without regrading. Group means weight each nonnull monthly mean once, never pooled reading counts. No saved group, audit, file or session write. Exact Decimal strings, explicit missing months, domain colour order, H before V, catalogue point_no/code and du->we order; group has no box/status/standard.')
def comparison_monthly_preview(principal: CurrentPrincipal, conn: DbConnection, scope: ActiveScope,
                               plant_code: PlantCode, request: Annotated[ComparisonMonthlyPreviewIn, Body(openapi_examples=MONTHLY_REQUEST_EXAMPLES)]) -> ComparisonMonthlyPreviewOut:
    try:
        return ComparisonMonthlyPreviewOut(**service.monthly_preview(conn, plant_code,
            plant_scope=scope.plant_scope, **request.model_dump()))
    except HistoryError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get('/{plant_code}/comparison/vehicle-visuals', response_model=ComparisonVehicleVisualsOut,
            responses=NOT_FOUND, summary='WaveScan ungraded CF boxes and raw DU-WE traces; any History reader.',
            description='v_wavescan_active only. T79 load-aware IDs and caller order. CF sample is every nonnull row across live catalogue locations of each orientation; box_stats linear quartiles and Tukey 1.5 IQR whiskers, no grade/status/standard. Full catalogue point_no ASC/code ASC; traces measurement_id ASC; historical unaligned rows checkzone ASC/measurement_id ASC. Nullable exact parameters/provenance, zero contributes, duplicate rows remain separate.')
def comparison_vehicle_visuals(
    principal: CurrentPrincipal, conn: DbConnection, scope: ActiveScope, plant_code: PlantCode,
    model: Annotated[str, Query(min_length=1, max_length=64, description='Exact WaveScan model at this plant; wrong model/plant/domain ID is 404.')],
    vehicle_id: Annotated[list[IdToken], Query(min_length=1, max_length=8, description='Required 1..8 distinct T79 WaveScan vehicle-set IDs including load identity, in caller order. Duplicate/ninth/malformed 422; missing/retired/wrong plant/model/domain 404, never omitted.')],
) -> ComparisonVehicleVisualsOut:
    try:
        return ComparisonVehicleVisualsOut(**service.vehicle_visuals(conn, plant_code,
            plant_scope=scope.plant_scope, model=model, vehicle_ids=vehicle_id))
    except HistoryError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def install_openapi_examples(app):
    """Preserve explicit missing values in the new response examples.

    FastAPI's OpenAPI encoder uses exclude_none=True recursively, including
    arbitrary example dictionaries. Attach these examples after that encoder
    so documented gaps carry the same nulls as real serialized responses.
    Existing paths and schemas are untouched.
    """
    from copy import deepcopy

    original = app.openapi

    def openapi():
        spec = original()
        response = spec['paths']['/api/v1/plants/{plant_code}/comparison/monthly-preview']['post']['responses']['200']
        response['content']['application/json']['examples'] = deepcopy(MONTHLY_RESPONSE_EXAMPLES)
        return spec

    app.openapi = openapi
