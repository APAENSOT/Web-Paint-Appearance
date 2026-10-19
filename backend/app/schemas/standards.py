"""Admin standards catalogue and append-only Ford/Min publish DTOs.

Plant-scoped family (ADR 0010). No product pass-rate. Extra keys 422.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import StrictModel

PLANTS = ("AAT", "FTM", "FVL", "SAP")


class PlantColorState(StrictModel):
    plant_code: str
    is_offered: bool
    family_code: str | None = None
    family_name: str | None = None


class CatalogueColorOut(StrictModel):
    color_name: str
    color_group: str | None
    plants: list[PlantColorState]


class PlantFamilyTargets(StrictModel):
    """Ford/Min this plant grades with for one family (ADR 0012).

    The plant's latest published row by ``created_at``; when the plant has
    none, the NULL-plant seed fallback and ``plant_specific`` false.
    """

    plant_code: str
    plant_specific: bool = Field(
        description="True when this plant has its own published row."
    )
    ford_h: int | None = None
    ford_v: int | None = None
    min_h: int | None = None
    min_v: int | None = None
    effective_from: date | None = None


class CatalogueFamilyOut(StrictModel):
    family_code: str
    family_name: str
    display_order: int
    ford_h: int | None = Field(
        default=None, description="NULL-plant seed fallback. Per-plant numbers are in plants."
    )
    ford_v: int | None = None
    min_h: int | None = None
    min_v: int | None = None
    effective_from: date | None = None
    plants: list[PlantFamilyTargets] = Field(
        description="One entry per plant AAT, FTM, FVL, SAP."
    )


class PlantModelState(StrictModel):
    plant_code: str
    is_offered: bool


class CatalogueModelOut(StrictModel):
    model_code: str
    body_style: str
    expected_zone_count: int
    plants: list[PlantModelState]


class CatalogueSeriesOut(StrictModel):
    series_code: str
    models: list[CatalogueModelOut]


class CatalogueOut(StrictModel):
    families: list[CatalogueFamilyOut]
    colors: list[CatalogueColorOut]
    series: list[CatalogueSeriesOut]



class ModelPointsOut(StrictModel):
    """T112: one Model-screen card. Counts are live and counted points.

    T112-FIX (D-112F-6): every card is a model offered at this plant, in
    either domain; ``wavescan_offered`` is true for a Wave Scan model.
    """

    model_code: str
    display_name: str | None
    series_code: str
    body_style: str
    wavescan_ok: bool
    wavescan_offered: bool
    wavescan_points: int | None = Field(
        description="Live Wave Scan points at this plant; null = no list."
    )
    film_points: int | None = Field(
        description="Live and counted Film points at this plant; null = no list."
    )


class PlantModelPointsOut(StrictModel):
    plant_code: str
    models: list[ModelPointsOut]
    attachable_models: list[str] = Field(
        description=(
            "T112-FIX (D-112F-4): active model_codes not offered at this "
            "plant, FilmThickness-only included -- the Attach list."
        )
    )

class ColorMintIn(StrictModel):
    color_name: str = Field(min_length=1, max_length=64)
    family_code: str = Field(min_length=2, max_length=8)
    plants: list[str] = Field(min_length=1)
    color_group: str | None = Field(default=None, max_length=32)

    @field_validator("color_name", "color_group")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("family_code")
    @classmethod
    def _family(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("family_code is required")
        return text

    @field_validator("plants")
    @classmethod
    def _plants(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for raw in value:
            code = raw.strip().upper()
            if code not in PLANTS:
                raise ValueError(f"unknown plant {raw!r}")
            if code not in out:
                out.append(code)
        if not out:
            raise ValueError("tick at least one plant")
        return out


class PlantColorPatchIn(StrictModel):
    plant_code: str = Field(min_length=1, max_length=16)
    color_name: str = Field(min_length=1, max_length=64)
    is_offered: bool | None = None
    family_code: str | None = Field(default=None, max_length=8)

    @field_validator("plant_code")
    @classmethod
    def _plant(cls, value: str) -> str:
        code = value.strip().upper()
        if code not in PLANTS:
            raise ValueError(f"unknown plant {value!r}")
        return code

    @field_validator("color_name")
    @classmethod
    def _name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("color_name is required")
        return text

    @field_validator("family_code")
    @classmethod
    def _family(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().upper()
        return text or None


class PlantModelAttachIn(StrictModel):
    model_code: str = Field(min_length=1, max_length=64)
    plants: list[str] = Field(min_length=1)

    @field_validator("model_code")
    @classmethod
    def _model(cls, value: str) -> str:
        return value.strip()

    @field_validator("plants")
    @classmethod
    def _plants(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for raw in value:
            code = raw.strip().upper()
            if code not in PLANTS:
                raise ValueError(f"unknown plant {raw!r}")
            if code not in out:
                out.append(code)
        if not out:
            raise ValueError("tick at least one plant")
        return out


class PlantModelOfferedIn(StrictModel):
    plant_code: str = Field(min_length=1, max_length=16)
    model_code: str = Field(min_length=1, max_length=64)
    is_offered: bool

    @field_validator("plant_code")
    @classmethod
    def _plant(cls, value: str) -> str:
        code = value.strip().upper()
        if code not in PLANTS:
            raise ValueError(f"unknown plant {value!r}")
        return code

    @field_validator("model_code")
    @classmethod
    def _model(cls, value: str) -> str:
        return value.strip()


class StandardPublishIn(StrictModel):
    plant_code: str = Field(
        min_length=1,
        max_length=16,
        description="AAT, FTM, FVL or SAP. The numbers apply to this plant only (ADR 0012).",
    )
    family_code: str | None = Field(default=None, max_length=8)
    family_name: str | None = Field(default=None, max_length=64)
    ford_h: int = Field(ge=0, le=200)
    ford_v: int = Field(ge=0, le=200)
    min_h: int = Field(ge=0, le=200)
    min_v: int = Field(ge=0, le=200)
    effective_from: date
    source_document: str | None = Field(default=None, max_length=128)
    source_note: str = Field(min_length=1, max_length=500)

    @field_validator("family_name", "source_document")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("family_code")
    @classmethod
    def _family(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().upper()
        return text or None

    @field_validator("source_note")
    @classmethod
    def _note(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("source_note is required")
        return text

    @field_validator("plant_code")
    @classmethod
    def _plant(cls, value: str) -> str:
        code = value.strip().upper()
        if code not in PLANTS:
            raise ValueError(f"unknown plant {value!r}")
        return code

    @model_validator(mode="after")
    def _needs_family(self) -> "StandardPublishIn":
        if not self.family_code and not self.family_name:
            raise ValueError("family_code or family_name is required")
        return self


class ColourMintOut(StrictModel):
    color_name: str
    audit_id: int


class PlantColorPatchOut(StrictModel):
    is_offered: bool
    family_name: str | None
    audit_id: int


class ReloadRefusedOut(StrictModel):
    """T115 (D-115-4): one held sheet an Attach could not reload, and why."""

    load_id: int
    reason: str = Field(description="The replay's own refusal, word for word.")


_RELOADED = (
    "T115 (D-115-4): the held sheets this request reloaded through the one "
    "ingest service (replay of the stored bytes; never a commit) -- every "
    "batch at a plant where the model has just become offered that is "
    "REJECTED_TEMPLATE or PENDING_REVIEW, has no facts, and holds a "
    "MODEL_NOT_OFFERED row. Empty when nothing was held, when the model was "
    "already offered, and always on Remove. Also on the audit row."
)
_REFUSED = (
    "T115 (D-115-4): sheets that matched but whose replay was refused. The "
    "Attach still stands."
)


class PlantModelAttachOut(StrictModel):
    plants: list[str]
    audit_id: int
    reloaded_load_ids: list[int] = Field(default_factory=list, description=_RELOADED)
    reload_refused: list[ReloadRefusedOut] = Field(
        default_factory=list, description=_REFUSED
    )


class PlantModelOfferedOut(StrictModel):
    is_offered: bool
    audit_id: int
    reloaded_load_ids: list[int] = Field(default_factory=list, description=_RELOADED)
    reload_refused: list[ReloadRefusedOut] = Field(
        default_factory=list, description=_REFUSED
    )


class StandardPublishOut(StrictModel):
    plant_code: str
    family_code: str
    family_name: str
    effective_from: date
    audit_action: Literal["standards.publish"] = "standards.publish"
    audit_id: int
    created_at: datetime
