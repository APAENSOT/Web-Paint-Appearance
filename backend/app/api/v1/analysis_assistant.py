"""Analysis assistant (AR04): one guided, no-AI answer. Read only, any role. No SQL here."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActiveScope, DbConnection
from app.api.v1.history import OptionalMonth, PlantCode
from app.core.security import CurrentPrincipal
from app.domain.assistant.catalog import CATALOG
from app.schemas.assistant import AssistantAnswerOut, AssistantQuestionsOut, Topic
from app.schemas.common import ErrorResponse
from app.schemas.report import Domain
from app.services import assistant as service
from app.services.history import HistoryError
from app.services.overview import OverviewError

router = APIRouter(tags=["analysis"])


@router.get(
    "/plants/{plant_code}/analysis/ask",
    response_model=AssistantAnswerOut,
    responses={404: {"model": ErrorResponse, "description": "No such plant."}},
    summary="One guided answer for a plant month: decision, proof, next step and evidence. "
    "Statuses are the overviews'. Any role.",
)
def analysis_ask(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    plant_code: PlantCode,
    topic: Annotated[Topic, Query(description="The question asked.")],
    target: Annotated[str | None, Query(description="Box key domain|layer|model|color|orient for questions with a box slot; ignored by others.")] = None,
    month: OptionalMonth = None,
    domain: Domain = "both",
    models: Annotated[list[str] | None, Query(description="Repeatable exact model_code. Omit for all.")] = None,
    colors: Annotated[list[str] | None, Query(description="Repeatable exact colour name. Omit for all.")] = None,
    a: Annotated[str | None, Query(description="First of a compared pair: model, colour or car.")] = None,
    b: Annotated[str | None, Query(description="Second of a compared pair: model, colour or car.")] = None,
    model: Annotated[str | None, Query(description="One model_code.")] = None,
    colour: Annotated[str | None, Query(description="One colour name.")] = None,
    layer: Annotated[str | None, Query(description="Film layer code: ECOAT, PRIMER, BASE or CLEAR.")] = None,
    metric: Annotated[str | None, Query(description="Film layer code or Wave Scan metric (lw sw cf doi du wa wb wc wd we b).")] = None,
    point: Annotated[str | None, Query(description="One point code.")] = None,
    car: Annotated[str | None, Query(description="One Film car id.")] = None,
    month2: Annotated[str | None, Query(description="The other month, YYYY-MM.")] = None,
    plant2: Annotated[str | None, Query(description="The other plant code.")] = None,
) -> AssistantAnswerOut:
    """AR04. Counts and statistics with n; no rate, share or new status."""
    try:
        return AssistantAnswerOut(**service.answer(
            conn, plant_code, plant_scope=scope.plant_scope, month=month, domain=domain,
            models=models, colors=colors, topic=topic, target=target,
            slots={"a": a, "b": b, "model": model, "colour": colour, "layer": layer, "metric": metric,
                   "point": point, "car": car, "month2": month2, "plant2": plant2},
        ))
    except (HistoryError, OverviewError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    "/plants/{plant_code}/analysis/questions",
    response_model=AssistantQuestionsOut,
    summary="The assistant's question catalog for the menu: labels, slots, graph kinds and keywords. "
    "Static per release; reads no data. Any role.",
)
def analysis_questions(principal: CurrentPrincipal, plant_code: PlantCode) -> AssistantQuestionsOut:
    """AR05 registry (spec §3)."""
    return AssistantQuestionsOut(
        questions=[{k: v for k, v in asdict(q).items() if k not in ("keywords", "keywords_th")} for q in CATALOG],
        keywords={q.id: [*q.keywords, *q.keywords_th] for q in CATALOG},
    )
