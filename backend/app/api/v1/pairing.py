"""Wave Scan <-> Film pairing readiness (AR01). Read only, any role. No SQL here."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import DbConnection
from app.api.v1.history import PlantCode
from app.core.security import CurrentPrincipal
from app.schemas.common import ErrorResponse
from app.schemas.pairing import PairingReadinessOut
from app.services import pairing as service
from app.services.history import HistoryError

router = APIRouter(tags=["analysis"])


@router.get(
    "/plants/{plant_code}/analysis/pairing",
    response_model=PairingReadinessOut,
    responses={404: {"model": ErrorResponse, "description": "No such plant."}},
    summary="Wave Scan <-> Film pairs and data-quality counts at this plant. Any role.",
)
def pairing_readiness(
    principal: CurrentPrincipal,
    conn: DbConnection,
    plant_code: PlantCode,
) -> PairingReadinessOut:
    """AR01. Counts only; no score, rate, status or grade."""
    try:
        return PairingReadinessOut(**service.read(conn, plant_code))
    except HistoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
