"""RO19 independent measuring order. Stable point_no is never a rank."""
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StrictModel

Domain = Literal["FILMTHICKNESS", "WAVESCAN"]


class PointWalkItem(StrictModel):
    point_code: str
    point_no: int = Field(ge=1, description="Stable catalogue number; unchanged by measuring-order edits.")
    label: str
    walk_rank: int = Field(ge=1, description="Position in this plant/model/domain measuring order.")


class PointWalkOut(StrictModel):
    plant_code: str
    model_code: str
    domain: Domain
    version_id: int | None
    set_by: str | None
    set_at: datetime | None
    reason: str | None
    items: list[PointWalkItem]


class PointWalkSetIn(StrictModel):
    point_codes: list[str] = Field(min_length=1, description="Every live point exactly once, in the chosen measuring order.")
    expected_version_id: int | None = Field(description="The version shown when editing; null for a list with no saved version.")
    reason: str = Field(min_length=3, max_length=500)


class PointWalkWritten(PointWalkOut):
    audit_id: int


class PointWalkDryRunIn(StrictModel):
    point_codes: list[str] = Field(min_length=1)
    simulate_film_rules: bool = Field(default=False, description="Film only: simulate counted points and their own H/V without enabling any setting.")


class PointWalkHeldSheet(StrictModel):
    load_id: int
    source_file: str
    source_sheet: str
    reasons: list[str]


class PointWalkDryRunOut(StrictModel):
    stored_sheets: int = Field(ge=0)
    changed_sheets: int = Field(ge=0)
    changed_dispositions: int = Field(ge=0)
    changed_vehicle_ids: int = Field(ge=0)
    held_sheets: list[PointWalkHeldSheet]
