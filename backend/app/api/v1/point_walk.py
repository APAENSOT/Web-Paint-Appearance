"""RO19 measuring-order controls. Dry-run is an attributed-write-free read."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import DbConnection, EngineerPrincipal, WriteConnection, get_ingest_service
from app.api.v1.history import PlantCode
from app.core.correlation import correlation_id_of
from app.core.security import CurrentPrincipal, Principal, require_role
from app.schemas.point_walk import Domain, PointWalkOut, PointWalkSetIn, PointWalkWritten, PointWalkDryRunIn, PointWalkDryRunOut
from app.services import point_walk as service
from app.services.workbooks import WorkbookError

router = APIRouter(tags=["point-walk"])
BASE = "/plants/{plant_code}/point-walk/{domain}/{model_code}"
AdminReader = Annotated[Principal, Depends(require_role("admin"))]


@router.get(BASE, response_model=PointWalkOut, summary="Read this list's independent measuring order. Any role.")
def read_order(principal: CurrentPrincipal, conn: DbConnection, plant_code: PlantCode, domain: Domain, model_code: str):
    try:
        return service.read(conn, plant_code, model_code, domain)
    except WorkbookError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.put(BASE, response_model=PointWalkWritten, summary="Save a new measuring-order version. Engineer or Admin.")
def write_order(request: Request, principal: EngineerPrincipal, conn: WriteConnection, plant_code: PlantCode, domain: Domain, model_code: str, body: PointWalkSetIn):
    try:
        return service.set_order(conn, plant_code, model_code, domain,
                                 point_codes=body.point_codes, expected_version_id=body.expected_version_id,
                                 reason=body.reason, actor=principal.user_id or "", correlation_id=correlation_id_of(request))
    except WorkbookError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(BASE + "/dry-run", response_model=PointWalkDryRunOut, summary="Count stored sheets that would read differently. Admin; read only.")
def dry_order(principal: AdminReader, conn: DbConnection, plant_code: PlantCode, domain: Domain, model_code: str, body: PointWalkDryRunIn, ingest=Depends(get_ingest_service)):
    try:
        return service.dry_run(conn, plant_code, model_code, domain, point_codes=body.point_codes,
                               simulate_film_rules=body.simulate_film_rules, ingest_service=ingest)
    except WorkbookError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
