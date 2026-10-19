"""FilmThickness micron standard DTOs (T62). Append-only publish, plant read.

Microns, 0-500, at most two decimals (``film_standard`` is numeric(6,2), so
a third decimal is refused rather than silently rounded). ``target`` is the
CLEAR "avg" only (D-FS-07). No status and no pass-rate field: D1 is open.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.domain.film_standards import LAYERS
from app.schemas.common import StrictModel
from app.schemas.standards import PLANTS

#: T67 D-67-07: the refusal text for ``hi`` on CLEAR.
CLEAR_HAS_NO_MAXIMUM = "Clear has no Maximum; use target for Minimum requirement"

LayerCode = Literal["ECOAT", "PRIMER", "BASE", "CLEAR"]
assert tuple(LayerCode.__args__) == LAYERS  # one layer vocabulary (film_header)


class FilmRuleIn(StrictModel):
    lo: float | None = Field(default=None, ge=0, le=500, description="Floor, microns.")
    hi: float | None = Field(default=None, ge=0, le=500, description="Ceiling, microns.")
    target: float | None = Field(
        default=None,
        ge=0,
        le=500,
        description="CLEAR only: the avg target (lo <= target <= hi).",
    )

    @field_validator("lo", "hi", "target")
    @classmethod
    def _two_decimals(cls, value: float | None) -> float | None:
        if value is not None and abs(round(value, 2) - value) > 1e-9:
            raise ValueError("at most two decimals (numeric(6,2))")
        return value

    @model_validator(mode="after")
    def _shape(self) -> "FilmRuleIn":
        if self.lo is None and self.hi is None:
            raise ValueError("at least one of lo or hi is required")
        if self.lo is not None and self.hi is not None and self.lo > self.hi:
            raise ValueError("lo must be <= hi")
        if self.target is not None:
            if self.lo is not None and self.target < self.lo:
                raise ValueError("target must be >= lo")
            if self.hi is not None and self.target > self.hi:
                raise ValueError("target must be <= hi")
        return self


class FilmStandardPublishIn(StrictModel):
    plant_code: str = Field(
        min_length=1,
        max_length=16,
        description="AAT, FTM, FVL or SAP. The rule applies to this plant only.",
    )
    layer_code: LayerCode
    color_name: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "NULL = plant-wide layer rule. Set = plant x colour rule; the "
            "colour must be offered at this plant (D-FS-08)."
        ),
    )
    h: FilmRuleIn
    v: FilmRuleIn
    source_document: str | None = Field(default=None, max_length=128)
    source_note: str = Field(min_length=1, max_length=500)

    @field_validator("plant_code")
    @classmethod
    def _plant(cls, value: str) -> str:
        code = value.strip().upper()
        if code not in PLANTS:
            raise ValueError(f"unknown plant {value!r}")
        return code

    @field_validator("color_name", "source_document")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("source_note")
    @classmethod
    def _note(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("source_note is required")
        return text

    @model_validator(mode="after")
    def _target_clear_only(self) -> "FilmStandardPublishIn":
        if self.layer_code != "CLEAR" and (
            self.h.target is not None or self.v.target is not None
        ):
            raise ValueError("target is allowed on CLEAR only")
        # T67 D-67-07: API only, no DB CHECK, so the T63 AAT row stays valid history.
        if self.layer_code == "CLEAR" and (self.h.hi is not None or self.v.hi is not None):
            raise ValueError(CLEAR_HAS_NO_MAXIMUM)
        return self


class FilmStandardPublishOut(StrictModel):
    plant_code: str
    layer_code: LayerCode
    color_name: str | None
    audit_id: int
    created_at: datetime


class FilmRuleOut(StrictModel):
    lo: float | None
    hi: float | None
    target: float | None
    source_document: str | None
    source_note: str
    created_at: datetime


class FilmLayerRuleOut(StrictModel):
    layer_code: LayerCode
    color_name: str | None = Field(description="NULL = plant-wide layer rule.")
    h: FilmRuleOut | None = Field(description="Latest H row, or null when none.")
    v: FilmRuleOut | None = Field(description="Latest V row, or null when none.")


class FilmPlantColorOut(StrictModel):
    color_name: str
    family_name: str | None = Field(
        description="Context only (D-FS-01): a family never selects a film number."
    )


class FilmStandardsOut(StrictModel):
    plant_code: str
    rules: list[FilmLayerRuleOut] = Field(
        description=(
            "Latest row per (layer, colour-or-NULL, orient) at this plant. A "
            "reading uses its colour's rule, else the plant-wide one, else none."
        )
    )
    colors: list[FilmPlantColorOut] = Field(description="Colours offered at this plant.")
