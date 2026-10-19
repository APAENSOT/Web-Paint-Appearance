"""Colour appearance DTOs (T116). One shade per plant x canonical colour.

HEX only, ``#RRGGBB`` uppercase (D-116-5): no RGB / HSV copy, no finish.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import StrictModel

_HEX = re.compile(r"#?[0-9A-Fa-f]{6}")


def normalize_hex(value: str) -> str:
    """``#RRGGBB`` uppercase. ``#`` optional, any case; anything else refused."""
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise ValueError(
            "hex must be six hex digits, optionally after '#' (e.g. #1A2B3C); "
            "3-digit, 8-digit / alpha and empty values are refused"
        )
    return "#" + value.lstrip("#").upper()


class ColorAppearanceOut(StrictModel):
    hex: str = Field(pattern=r"^#[0-9A-F]{6}$", examples=["#1A2B3C"])
    revision: int = Field(ge=1, description="This colour's own revision at this plant.")
    saved_at: datetime
    saved_by: str | None = Field(
        description="app_user.display_name of the person who saved it; null when unknown. Never a UUID."
    )
    inherited_from: str | None = Field(
        description=(
            "Null for the colour's own profile. Otherwise the merged name whose "
            "profile this canonical colour shows because it has none of its own "
            "(D-116-2). Saving the canonical colour then starts its own revision 1."
        )
    )


class ColorAppearanceItem(StrictModel):
    color_name: str = Field(
        description="ref_color.color_name: the canonical identity; joins the Standard catalogue's colour names exactly."
    )
    family_name: str | None = Field(description="ref_plant_color.family_name at this plant, for context only.")
    appearance: ColorAppearanceOut | None = Field(
        description="Null means unconfigured: no profile saved. Nothing is generated."
    )


class ColorAppearancesOut(StrictModel):
    plant_code: str
    items: list[ColorAppearanceItem] = Field(
        description="Every canonical colour offered at the plant, by name."
    )
    unavailable: list[ColorAppearanceItem] = Field(
        description=(
            "Saved profiles not shown in items: colours no longer offered here, "
            "and merged names whose canonical colour shows another profile. Kept "
            "so nothing saved is hidden; not for normal Studio selection."
        )
    )


class ColorAppearanceSaveIn(StrictModel):
    hex: str = Field(description="Six hex digits, '#' optional, any case. Stored as #RRGGBB.")
    expected_revision: int | None = Field(
        ge=1,
        description=(
            "The revision the editor loaded. null = first save of this colour's "
            "own profile (also when items shows an inherited one)."
        ),
    )

    @field_validator("hex")
    @classmethod
    def _hex(cls, value: str) -> str:
        return normalize_hex(value)


class ColorAppearanceSaved(StrictModel):
    color_name: str
    hex: str = Field(pattern=r"^#[0-9A-F]{6}$")
    revision: int = Field(ge=1)
    saved_at: datetime
    saved_by: str | None
    replayed: bool = Field(
        description="True when this is a safe retry of a save already persisted (same person, same hex); nothing new was written."
    )
