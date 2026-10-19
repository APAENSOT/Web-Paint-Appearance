from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbConnection
from app.core.security import CurrentPrincipal
from app.repositories import meta as meta_repo
from app.schemas.meta import CheckzoneOut, ColorOut, MetaResponse, ModelOut, PlantOut

router = APIRouter(tags=["meta"])


@router.get(
    "/meta",
    response_model=MetaResponse,
    summary="Reference data for filters. Colour families are Admin catalogue, not here.",
)
def get_meta(principal: CurrentPrincipal, conn: DbConnection) -> MetaResponse:
    colors = [
        ColorOut(
            color_name=row["color_name"],
            color_group=row["color_group"],
            is_active=row["is_active"],
            grading_family=row["grading_family"],
            grading_family_status="mapped" if row["grading_family"] else "unmapped",
        )
        for row in meta_repo.list_colors(conn)
    ]
    return MetaResponse(
        plants=[PlantOut(**row) for row in meta_repo.list_plants(conn)],
        models=[ModelOut(**row) for row in meta_repo.list_models(conn)],
        colors=colors,
        checkzones=[CheckzoneOut(**row) for row in meta_repo.list_checkzones(conn)],
        unmapped_color_count=meta_repo.unmapped_offered_count(conn),
    )
