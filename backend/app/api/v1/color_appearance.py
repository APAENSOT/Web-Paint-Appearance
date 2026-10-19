"""Colour appearance profiles for Model Studio (T116). No SQL in this module.

Read: any role. Save: Engineer or Admin (D-116-1); a Viewer gets 403 before
anything is written.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request

from app.api.deps import DbConnection, EngineerPrincipal, WriteConnection
from app.api.v1.history import PlantCode
from app.core.correlation import correlation_id_of
from app.core.security import CurrentPrincipal
from app.schemas.color_appearance import (
    ColorAppearanceSaved,
    ColorAppearanceSaveIn,
    ColorAppearancesOut,
)
from app.schemas.common import ErrorResponse
from app.services import color_appearance as service
from app.services.history import HistoryError

router = APIRouter(tags=["color-appearance"])

#: ``:path`` because canonical names hold a slash ("Absolute / Shadow Black").
ColorName = Annotated[
    str,
    Path(min_length=1, max_length=64,
         description="ref_color.color_name, exact (URL-encoded). Never fuzzy-matched."),
]

READ_REFUSED = {404: {"model": ErrorResponse, "description": "No such plant."}}
SAVE_REFUSED = {
    404: {"model": ErrorResponse, "description": "No such plant, or unknown colour."},
    409: {
        "model": ErrorResponse,
        "description": (
            "expected_revision is not the saved revision (stale, or a concurrent "
            "save won). The message names the current revision and hex. Reload; "
            "nothing was written."
        ),
    },
    422: {
        "model": ErrorResponse,
        "description": (
            "Bad hex, the name is merged into a canonical colour (save that one), "
            "or the colour is not offered at this plant."
        ),
    },
}


def _refused(exc: service.ColorAppearanceError | HistoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get(
    "/plants/{plant_code}/color-appearances",
    response_model=ColorAppearancesOut,
    responses=READ_REFUSED,
    summary="Model Studio body shade per canonical colour offered at this plant. Any role.",
)
def list_color_appearances(
    principal: CurrentPrincipal,
    conn: DbConnection,
    plant_code: PlantCode,
) -> ColorAppearancesOut:
    """T116 (D-116-6). ``appearance: null`` means unconfigured. A failed read
    is an error status, never an empty list."""
    try:
        return ColorAppearancesOut(**service.read(conn, plant_code))
    except HistoryError as exc:
        raise _refused(exc) from exc


@router.post(
    "/plants/{plant_code}/color-appearances/{color_name:path}",
    response_model=ColorAppearanceSaved,
    responses=SAVE_REFUSED,
    summary="Save a colour's body shade at this plant (new revision). Engineer.",
)
def save_color_appearance(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    color_name: ColorName,
    body: ColorAppearanceSaveIn,
) -> ColorAppearanceSaved:
    """T116 (D-116-7). Append-only, with its ``audit_event`` in the same
    transaction. A retry of a save already persisted by the same person with
    the same hex answers 200 ``replayed: true``."""
    try:
        return ColorAppearanceSaved(**service.save(
            conn, plant_code, color_name, hex_value=body.hex,
            expected_revision=body.expected_revision,
            actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except (service.ColorAppearanceError, HistoryError) as exc:
        raise _refused(exc) from exc
