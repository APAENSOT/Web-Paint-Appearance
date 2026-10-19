"""FilmThickness micron standards: plant read and Admin append-only publish (T62).

The container only (T62-CONTEXT): no number is seeded, nothing is graded,
no status or pass rate -- D1 is open and ``grading_available`` stays false.
The GET is open to any authenticated role, like the T48 film reads, so a
later dashboard can show the numbers; the POST is Admin only, like WaveScan
``POST /standards``. No SQL in this module.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import AdminPrincipal, DbConnection, WriteConnection
from app.api.v1.history import PlantCode
from app.core.correlation import correlation_id_of
from app.core.security import CurrentPrincipal
from app.repositories import film_standards as repo
from app.schemas.common import ErrorResponse
from app.schemas.film_standards import (
    FilmLayerRuleOut,
    FilmPlantColorOut,
    FilmRuleOut,
    FilmStandardPublishIn,
    FilmStandardPublishOut,
    FilmStandardsOut,
)
from app.services.history import HistoryError, resolve_plant

router = APIRouter(tags=["filmthickness-standards"])

PLANT_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such plant."}}
PUBLISH_REFUSED = {
    404: {"model": ErrorResponse, "description": "Unknown colour."},
    422: {
        "model": ErrorResponse,
        "description": (
            "Request validation failed (lo/hi/target shape, target on a layer "
            "other than CLEAR), or the colour is not offered at this plant "
            "(D-FS-08)."
        ),
    },
}


def _rule_out(row: dict | None) -> FilmRuleOut | None:
    if row is None:
        return None
    return FilmRuleOut(
        **{
            key: (float(row[key]) if row[key] is not None else None)
            for key in ("lo", "hi", "target")
        },
        source_document=row["source_document"],
        source_note=row["source_note"],
        created_at=row["created_at"],
    )


def _rules_out(rows: list[dict]) -> list[FilmLayerRuleOut]:
    paired: dict[tuple[str, str | None], dict[str, dict]] = {}
    for row in rows:
        paired.setdefault((row["layer_code"], row["color_name"]), {})[row["orient"]] = row
    return [
        FilmLayerRuleOut(
            layer_code=layer,
            color_name=color,
            h=_rule_out(pair.get("H")),
            v=_rule_out(pair.get("V")),
        )
        for (layer, color), pair in paired.items()
    ]


@router.get(
    "/plants/{plant_code}/filmthickness/standards",
    response_model=FilmStandardsOut,
    responses=PLANT_NOT_FOUND,
    summary="Latest FilmThickness micron standards at one plant (H and V). Any role.",
)
def get_film_standards(
    principal: CurrentPrincipal,
    conn: DbConnection,
    plant_code: PlantCode,
) -> FilmStandardsOut:
    """Latest rule per (layer, colour-or-NULL, orient) at this plant.

    No rule from another plant is ever shown. No status, no pass rate.
    """
    try:
        plant = resolve_plant(conn, plant_code)
    except HistoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    found = repo.latest(conn, plant["plant_code"])
    return FilmStandardsOut(
        plant_code=plant["plant_code"],
        rules=_rules_out(found["rules"]),
        colors=[FilmPlantColorOut(**c) for c in found["colors"]],
    )


@router.post(
    "/filmthickness/standards",
    response_model=FilmStandardPublishOut,
    status_code=status.HTTP_201_CREATED,
    responses=PUBLISH_REFUSED,
    summary=(
        "Append a FilmThickness micron standard (H and V) for one plant x "
        "layer [x colour]. Admin. Prior rows stay."
    ),
)
def publish_film_standard(
    principal: AdminPrincipal,
    conn: WriteConnection,
    request: Request,
    body: FilmStandardPublishIn,
) -> FilmStandardPublishOut:
    try:
        row = repo.publish(
            conn,
            plant_code=body.plant_code,
            layer_code=body.layer_code,
            color_name=body.color_name,
            h=body.h.model_dump(),
            v=body.v.model_dump(),
            source_document=body.source_document,
            source_note=body.source_note,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except repo.FilmStandardColorUnknown as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except repo.FilmStandardColorNotOffered as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message
        ) from exc
    return FilmStandardPublishOut.model_validate(row)
