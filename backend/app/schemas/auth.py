from __future__ import annotations

from pydantic import Field

from app.core.security import Principal
from app.schemas.common import StrictModel


class MeResponse(StrictModel):
    principal: Principal
    plant_scope: list[str] | None = Field(
        description="Plant codes this caller may read. null = all plants (D3 open)."
    )
    plant_scope_note: str
    environment: str
