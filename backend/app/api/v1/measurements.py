"""Measurement reads, and the correction that replaces one.

`POST /api/v1/measurements/{measurement_id}/corrections` replaces the reserved
stub of the same path (T03 `api/v1/reserved.py`); the URL and the Engineer
role are unchanged, so no generated client breaks.

`GET /api/v1/measurements/{measurement_id}` is **new in T09** and is a
recorded contract change (`docs/reports/T09-IMMUTABLE.md`). It is not an extra:
an Engineer corrects the row the plant table is showing, and a client that
could not fetch one row would have to page the list to find it and would have
no way to re-read the result of its own correction. It reads the same view as
the list, so a retired or uncommitted measurement is a 404 here too rather
than a leaked original.

No SQL in this module (`00-ARCHITECTURE.md` §5 rule 2) and no grading field
(D1, still open).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.api.deps import (
    ActiveScope,
    DbConnection,
    EngineerPrincipal,
    Filters,
    WriteConnection,
    get_correction_service,
)
from app.core.correlation import correlation_id_of
from app.core.security import CurrentPrincipal
from app.repositories import measurements as repo
from app.schemas.common import ErrorResponse, PageInfo
from app.schemas.corrections import CorrectionCreate, CorrectionResult
from app.schemas.measurements import MeasurementFilters, MeasurementOut, MeasurementPage
from app.services.corrections import CorrectionError, CorrectionService

router = APIRouter(tags=["measurements"])

MAX_PAGE = 500

MeasurementId = Annotated[int, Path(ge=1, description="wavescan.measurement_id")]

#: Declared per-route because on the correction path a refusal IS the
#: behaviour: a generated client that did not know 409 was possible would
#: treat "already corrected" as an unexpected error (`AGENTS.md` rule 9).
NOT_FOUND = {
    404: {
        "model": ErrorResponse,
        "description": "No such measurement, or it is not a current reading.",
    }
}
CONFLICT = {
    409: {
        "model": ErrorResponse,
        "description": (
            "The measurement exists but is not correctable: already retired "
            "by an earlier correction, recorded as a duplicate, or owned by a "
            "batch that is not committed. Nothing was written."
        ),
    }
}


@router.get(
    "/measurements",
    response_model=MeasurementPage,
    summary="Active measurements, paginated. Reads v_wavescan_active.",
)
def list_measurements(
    principal: CurrentPrincipal,
    conn: DbConnection,
    filters: Filters,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MeasurementPage:
    total = repo.count_measurements(conn, filters)
    rows = repo.list_measurements(conn, filters, limit=limit, offset=offset)
    items = [MeasurementOut(**row) for row in rows]
    return MeasurementPage(
        items=items,
        page=PageInfo(limit=limit, offset=offset, total=total, returned=len(items)),
        filters=MeasurementFilters(
            plant=filters.plant,
            model=filters.model,
            color=filters.color,
            checkzone=filters.checkzone,
            date_from=filters.date_from,
            date_to=filters.date_to,
            load_id=filters.load_id,
        ),
    )


@router.get(
    "/measurements/{measurement_id}",
    response_model=MeasurementOut,
    responses=NOT_FOUND,
    summary="One active measurement. Any authenticated role.",
)
def get_measurement(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    measurement_id: MeasurementId,
) -> MeasurementOut:
    """404 covers "never existed" and "no longer current" alike.

    Telling the two apart would confirm the existence of a measurement the
    platform has retired, to a caller who is only allowed to read current
    ones. The correction route, whose caller is entitled to know, says which.
    """
    row = repo.get_active(conn, measurement_id, scope)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No current measurement {measurement_id}. It may never have "
                f"existed, or it may have been corrected, flagged as a "
                f"duplicate, or belong to a batch that is not committed."
            ),
        )
    return MeasurementOut(**row)


@router.post(
    "/measurements/{measurement_id}/corrections",
    response_model=CorrectionResult,
    status_code=status.HTTP_201_CREATED,
    responses={**NOT_FOUND, **CONFLICT},
    summary="Correct a measurement by adding a row. Engineer role.",
)
def correct_measurement(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    service: Annotated[CorrectionService, Depends(get_correction_service)],
    scope: ActiveScope,
    measurement_id: MeasurementId,
    body: CorrectionCreate,
) -> CorrectionResult:
    """One transaction: the new row, the supersession record, the audit event.

    The original is **not** edited. It stays in `wavescan` with the values it
    always had and leaves the active reads because the supersession trigger
    sets its flag -- the application holds no `UPDATE` on that table and could
    not do it any other way (ADR 0005, `01-DATA-MODEL.md` §5).

    Identity is not patchable: `plant`, `model`, `checkzone`, `color`,
    `tolerance_group`, `paintline`, `load_id`, `source_sheet` and `source_row`
    are not fields of the body, so sending one is a 422. They are copied from
    the original inside the INSERT.
    """
    try:
        result = service.correct(
            conn,
            measurement_id,
            body,
            actor_user_id=principal.user_id or "",
            scope=scope,
            correlation_id=correlation_id_of(request),
        )
    except CorrectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return CorrectionResult(
        measurement=MeasurementOut(**result["measurement"]),
        superseded_measurement_id=result["superseded_measurement_id"],
        supersession_id=result["supersession_id"],
    )
