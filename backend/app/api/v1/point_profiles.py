"""Model Studio 3D inspection-point profiles. No SQL in this module.

Read: any authenticated role. Save / remove: Engineer or Admin; a Viewer gets
403 before anything is written.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request

from app.api.deps import DbConnection, EngineerPrincipal, WriteConnection
from app.api.v1.history import PlantCode
from app.core.correlation import correlation_id_of
from app.core.security import CurrentPrincipal
from app.schemas.common import ErrorResponse
from app.schemas.point_profiles import (
    AnchorRemoveIn,
    AnchorSaveIn,
    AnchorWritten,
    Domain,
    PointProfileOut,
)
from app.services import point_profiles as service
from app.services.history import HistoryError

router = APIRouter(tags=["point-profiles"])

ModelCode = Annotated[
    str,
    Path(min_length=1, max_length=64,
         description="ref_model.model_code, exact (URL-encoded). Aliases are not resolved."),
]
DomainPath = Annotated[Domain, Path(description="Measurement domain; each has its own layout.")]

BASE = "/plants/{plant_code}/point-profiles/{model_code}/{domain}"
READ_REFUSED = {404: {"model": ErrorResponse, "description": "No such plant, or no exact canonical model."}}
WRITE_REFUSED = {
    **READ_REFUSED,
    409: {
        "model": ErrorResponse,
        "description": (
            "expected_revision is not this point's saved revision (stale, or a concurrent "
            "write won). The message names the current revision. Reload the profile; "
            "nothing was written."
        ),
    },
    422: {
        "model": ErrorResponse,
        "description": (
            "Unknown, retired (save only), wrong-model or wrong-domain point; point_no "
            "mismatch; unregistered or other-model asset; unknown mesh; non-finite, "
            "out-of-bounds or non-unit values; zone that disagrees with mesh/side; "
            "removing a location that does not exist."
        ),
    },
}


def _refused(exc: service.PointProfileError | HistoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get(
    BASE,
    response_model=PointProfileOut,
    responses=READ_REFUSED,
    summary="Default 3D point layout for a plant x model x domain, shared by every colour and month. Any role.",
)
def read_point_profile(
    principal: CurrentPrincipal,
    conn: DbConnection,
    plant_code: PlantCode,
    model_code: ModelCode,
    domain: DomainPath,
) -> PointProfileOut:
    """``state: unconfigured`` before the first save. Monthly Detail reads the
    same layout for any colour or month: join ``zone_code`` / ``point_code``
    to readings, draw only anchors with ``asset_compatible``, and list
    ``unavailable`` and anchor-less points as unplaced."""
    try:
        return PointProfileOut(**service.read(conn, plant_code, model_code, domain))
    except (service.PointProfileError, HistoryError) as exc:
        raise _refused(exc) from exc


@router.post(
    BASE + "/save",
    response_model=AnchorWritten,
    responses=WRITE_REFUSED,
    summary="Place or move one point (new revision of that anchor). Engineer.",
)
def save_point_anchor(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: ModelCode,
    domain: DomainPath,
    body: AnchorSaveIn,
) -> AnchorWritten:
    """Every other anchor is untouched. Append-only, with its ``audit_event``
    in the same transaction. A same-person same-content retry answers 200
    ``replayed: true``."""
    try:
        return AnchorWritten(**service.save(
            conn, plant_code, model_code, domain,
            point_key=body.point_key, point_no=body.point_no,
            expected_revision=body.expected_revision,
            anchor=body.anchor.model_dump(),
            actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except (service.PointProfileError, HistoryError) as exc:
        raise _refused(exc) from exc


@router.post(
    BASE + "/remove",
    response_model=AnchorWritten,
    responses=WRITE_REFUSED,
    summary="Remove one point's location (tombstone revision). The Standard point stays. Engineer.",
)
def remove_point_anchor(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: ModelCode,
    domain: DomainPath,
    body: AnchorRemoveIn,
) -> AnchorWritten:
    """Answers the point with ``anchor: null`` and its new revision."""
    try:
        return AnchorWritten(**service.remove(
            conn, plant_code, model_code, domain,
            point_key=body.point_key, point_no=body.point_no,
            expected_revision=body.expected_revision,
            actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except (service.PointProfileError, HistoryError) as exc:
        raise _refused(exc) from exc
