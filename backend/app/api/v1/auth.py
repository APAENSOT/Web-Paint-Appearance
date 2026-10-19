from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.scoping import D3_TEMPORARY_RULE, visible_plants
from app.api.deps import CurrentUser
from app.schemas.auth import MeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/me",
    response_model=MeResponse,
    summary="The calling identity, its roles, and the plants it may read.",
    description=(
        "Creates the app_user row on first sign-in (T04), so principal.user_id "
        "is the id every later batch, audit event and supersession is "
        "attributed to."
    ),
)
def me(request: Request, principal: CurrentUser) -> MeResponse:
    return MeResponse(
        principal=principal,
        plant_scope=visible_plants(principal),
        plant_scope_note=D3_TEMPORARY_RULE,
        environment=request.app.state.settings.env,
    )
