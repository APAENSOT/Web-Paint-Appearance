"""Reference data for filter controls.

The colour block is the part with a rule attached. `ref_color.grading_family`
is NULL for all 21 colours because **D2 is open**, and
`ref_color.color_group` (GREEN / SILVER / ...) is a display grouping, not the
grading taxonomy (`01-DATA-MODEL.md` section 6.5, `AGENTS.md` section 4). So:

* the endpoint returns **no colour families** -- not the six seeded rows of
  `ref_color_family`, not a list derived from `color_group`;
* every colour states `grading_family_status`, and today that is always
  `"unmapped"`.

A client that wants to grade has to notice the absence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import StrictModel


class PlantOut(StrictModel):
    plant_code: str
    plant_name: str
    country: str | None
    is_active: bool


class ModelOut(StrictModel):
    model_code: str
    model_family: str
    body_style: str
    expected_zone_count: int
    is_active: bool


class ColorOut(StrictModel):
    color_name: str
    color_group: str | None = Field(
        description=(
            "Display grouping only (GREEN / SILVER / ...). NOT the grading "
            "family and never a substitute for one."
        )
    )
    is_active: bool
    grading_family: str | None = Field(
        description=(
            "Unused optional default. Grading family is plant-scoped "
            "(ref_plant_color). This column stays null in this slice."
        )
    )
    grading_family_status: Literal["mapped", "unmapped"] = Field(
        description=(
            "'unmapped' on this DTO means ref_color.grading_family is null. "
            "Plant-scoped family lives on the Admin catalogue, not here."
        )
    )


class CheckzoneOut(StrictModel):
    zone_code: str
    zone_name: str
    panel_group: str
    tolerance_group: Literal["Horizontal", "Vertical"]


class MetaResponse(StrictModel):
    plants: list[PlantOut]
    models: list[ModelOut]
    colors: list[ColorOut]
    checkzones: list[CheckzoneOut]
    grading_available: Literal[False] = Field(
        default=False,
        description=(
            "Product pass-rate is not available. D1 (grouping key) stays open. "
            "Plant-scoped D2 does not flip this flag."
        ),
    )
    unmapped_color_count: int = Field(
        description=(
            "Offered plant-colours with a null family. Not len(colors), and "
            "not permission to compute a dashboard pass-rate."
        )
    )
