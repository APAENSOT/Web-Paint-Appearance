"""Admin catalogue and append-only Ford/Min publish.

RO13: the two reads (catalogue, a plant's model points) are any signed-in
role, as History's are; every write here stays Admin.

Replaces the reserved stub of ``POST /api/v1/standards``. Family is
plant-scoped (ADR 0010). D1 stays open: this module does not flip
``grading_available`` and does not write ``ref_color.grading_family``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import (
    AdminPrincipal,
    DbConnection,
    WriteConnection,
    get_ingest_service,
)
from app.api.v1.history import PlantCode
from app.core.correlation import correlation_id_of
from app.core.security import CurrentPrincipal
from app.repositories import standards as repo
from app.services import model_offer
from app.services.ingest import IngestService
from app.schemas.common import ErrorResponse
from app.schemas.standards import (
    CatalogueOut,
    ColorMintIn,
    ColourMintOut,
    PlantColorPatchIn,
    PlantColorPatchOut,
    PlantModelAttachIn,
    PlantModelAttachOut,
    PlantModelOfferedIn,
    PlantModelOfferedOut,
    PlantModelPointsOut,
    StandardPublishIn,
    StandardPublishOut,
)
from app.services.history import HistoryError, resolve_plant

router = APIRouter(tags=["standards"])

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Unknown colour, model, or family."}}
#: T46 (F5): a FilmThickness-only model (wavescan_ok = false) is not this domain.
NOT_THIS_DOMAIN = {
    422: {
        "model": ErrorResponse,
        "description": (
            "Request validation failed, or (T46) the model is FilmThickness-only "
            "(wavescan_ok = false): not this domain."
        ),
    }
}
CONFLICT = {
    409: {
        "model": ErrorResponse,
        "description": "Colour name already exists, or the model is already attached.",
    }
}


def _http(
    exc: repo.StandardsNotFound | repo.StandardsConflict | repo.StandardsNotThisDomain,
) -> HTTPException:
    if isinstance(exc, repo.StandardsNotThisDomain):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(exc, repo.StandardsNotFound):
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail=exc.message)


@router.get(
    "/standards/catalogue",
    response_model=CatalogueOut,
    summary="Plant-scoped colour families, offered ticks, and series. Any role.",
)
def get_catalogue(principal: CurrentPrincipal, conn: DbConnection) -> CatalogueOut:
    return CatalogueOut.model_validate(repo.catalogue(conn))



@router.get(
    "/plants/{plant_code}/model-points",
    response_model=PlantModelPointsOut,
    responses={404: {"model": ErrorResponse, "description": "No such plant."}},
    summary="Model screen cards (offered models, both domains) and the Attach list. Any role.",
)
def get_model_points(
    principal: CurrentPrincipal, conn: DbConnection, plant_code: PlantCode
) -> PlantModelPointsOut:
    try:
        plant = resolve_plant(conn, plant_code)
    except HistoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return PlantModelPointsOut(
        plant_code=plant["plant_code"],
        models=repo.model_points(conn, plant["plant_code"]),
        attachable_models=repo.attachable_models(conn, plant["plant_code"]),
    )

@router.post(
    "/standards/colours",
    response_model=ColourMintOut,
    status_code=status.HTTP_201_CREATED,
    responses={**NOT_FOUND, **CONFLICT},
    summary="Mint a catalogue colour under a family heading. Admin.",
)
def mint_colour(
    principal: AdminPrincipal,
    conn: WriteConnection,
    request: Request,
    body: ColorMintIn,
) -> ColourMintOut:
    try:
        row = repo.mint_color(
            conn,
            color_name=body.color_name,
            family_code=body.family_code,
            plants=body.plants,
            color_group=body.color_group,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except (repo.StandardsNotFound, repo.StandardsConflict) as exc:
        raise _http(exc) from exc
    return ColourMintOut.model_validate(row)


@router.post(
    "/standards/plant-colours",
    response_model=PlantColorPatchOut,
    responses=NOT_FOUND,
    summary="Set offered flag and/or family for one plant colour. Admin.",
)
def set_plant_colour(
    principal: AdminPrincipal,
    conn: WriteConnection,
    request: Request,
    body: PlantColorPatchIn,
) -> PlantColorPatchOut:
    try:
        row = repo.set_plant_color(
            conn,
            plant_code=body.plant_code,
            color_name=body.color_name,
            is_offered=body.is_offered,
            family_code=body.family_code,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except (
        repo.StandardsNotFound, repo.StandardsConflict, repo.StandardsNotThisDomain,
    ) as exc:
        raise _http(exc) from exc
    return PlantColorPatchOut.model_validate(row)


def _reloader(conn, ingest: IngestService, model_code: str, principal, request: Request):
    """T115 (D-115-4): the reload an Attach runs where the offer turned on."""
    return lambda plants: model_offer.reload_held(
        conn, ingest,
        plants=plants,
        model_code=model_code,
        actor_user_id=principal.user_id or "",
        correlation_id=correlation_id_of(request),
    )


@router.post(
    "/standards/plant-models",
    response_model=PlantModelAttachOut,
    status_code=status.HTTP_201_CREATED,
    responses={**NOT_FOUND, **CONFLICT, **NOT_THIS_DOMAIN},
    summary="Attach an existing model_code to plants. Admin. Does not mint models.",
)
def attach_plant_models(
    principal: AdminPrincipal,
    conn: WriteConnection,
    request: Request,
    body: PlantModelAttachIn,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
) -> PlantModelAttachOut:
    """T115 (D-115-4): where the model was not offered, the same request
    reloads the sheets its absence held there (`reloaded_load_ids`)."""
    try:
        row = repo.attach_models(
            conn,
            model_code=body.model_code,
            plants=body.plants,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
            reload=_reloader(conn, ingest, body.model_code, principal, request),
        )
    except (
        repo.StandardsNotFound, repo.StandardsConflict, repo.StandardsNotThisDomain,
    ) as exc:
        raise _http(exc) from exc
    return PlantModelAttachOut.model_validate(row)


@router.post(
    "/standards/plant-models/offered",
    response_model=PlantModelOfferedOut,
    responses={**NOT_FOUND, **NOT_THIS_DOMAIN},
    summary="Set is_offered for one plant model. Admin.",
)
def set_plant_model_offered(
    principal: AdminPrincipal,
    conn: WriteConnection,
    request: Request,
    body: PlantModelOfferedIn,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
) -> PlantModelOfferedOut:
    """T115 (D-115-4): false/absent -> true also reloads the sheets the
    model's absence held at this plant. Remove (false) reloads nothing."""
    try:
        row = repo.set_plant_model_offered(
            conn,
            plant_code=body.plant_code,
            model_code=body.model_code,
            is_offered=body.is_offered,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
            reload=_reloader(conn, ingest, body.model_code, principal, request),
        )
    except (
        repo.StandardsNotFound, repo.StandardsConflict, repo.StandardsNotThisDomain,
    ) as exc:
        raise _http(exc) from exc
    return PlantModelOfferedOut.model_validate(row)


@router.post(
    "/standards",
    response_model=StandardPublishOut,
    status_code=status.HTTP_201_CREATED,
    responses=NOT_FOUND,
    summary="Append a plant x FAMILY Ford/Min version (H and V). Admin. Prior rows stay.",
)
def publish_standard(
    principal: AdminPrincipal,
    conn: WriteConnection,
    request: Request,
    body: StandardPublishIn,
) -> StandardPublishOut:
    try:
        row = repo.publish_family(
            conn,
            plant_code=body.plant_code,
            family_code=body.family_code,
            family_name=body.family_name,
            ford_h=body.ford_h,
            ford_v=body.ford_v,
            min_h=body.min_h,
            min_v=body.min_v,
            effective_from=body.effective_from,
            source_document=body.source_document,
            source_note=body.source_note,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except (repo.StandardsNotFound, repo.StandardsConflict) as exc:
        raise _http(exc) from exc
    return StandardPublishOut.model_validate(row)
